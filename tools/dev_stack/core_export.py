"""Load the core's drone-world export into erp-sim (`stack seed-core-export <dir>`; M4 contract section 4, F4, Q9).

The SCMTIPS core writes its SAMPLE world (the drone OEM) to ``samples/exports/erp-sim/`` (core commit 374702a,
``uv run scmtips-sample-exports write``): ``plants.csv``, ``storage_locations.csv``, ``materials.csv``,
``suppliers.csv``, ``stock.csv``, ``purchase_orders.csv`` and ``manifest.json``, in the core's own codes
(``PLANT-GOA``, ``CP-204``, ``PO-26-1002``, ``SUP-S02``). Its Field site pack (``samples/exports/field-site-pack/``:
``sites.csv``, ``bins.csv``, ``labels.csv``) is read by ``parse_site_pack`` and created through field-api by the stack.

The loader stays tolerant of other shapes and reports what it assumed. It recognises:

- JSON: an exchange-contract ``erp_extract`` envelope (``{"parts": {"inventory": [...], "open_supply": [...]}}``),
  an object of tables (``{"items": [...], "locations": [...], ...}``), or a list of rows named by the file name;
  ``manifest.json`` (the core's) is read for its export name and version only;
- CSV: one table per file, named by the file name (header row, comma separated).

Tables (file / key names, case-insensitive): items (items, materials, item_master, products), locations
(locations, plants, sites), storage_locations (storage_locations, slocs), inventory (inventory, stock, on_hand),
open_supply (open_supply, purchase_orders, open_pos, pos, po_lines, supply), suppliers (suppliers, vendors).
``bom`` and anything else is reported and ignored. Columns use the exchange contract's names, with a few aliases
(material -> item_code, plant -> location_code, ...).

A PO line is ``ref`` + ``po_item``: the core's export gives the PO number exactly as the core knows it
(``PO-26-1002``) and the item in ``po_item``. Without a ``po_item`` column, an SAP-style ``<digits>-<digits>`` ref
(``4500001234-10``, the exchange contract's example) is split into PO and item; any other ref is the PO number with
item 10.

Loaded into erp-sim with the core's codes as the ERP's codes (so the feed rows need no FIELD_CORE_CODE_MAP): plants
and their storage locations (a plant without one gets FIELD_CORE_EXPORT_SLOC, default 0001), materials with their
barcode (default: the code), absolute on-hand per storage location, every open PO line as an erp-sim purchase order
(supplier, delivery date, the core's status and lane: what the snapshot to the core reads back, M4 Q10), and one
inbound delivery (ASN) per PO whose items reference the PO lines, so receiving it posts a GR 101 against them.
Re-running is safe: existing rows are updated, and an ASN is made only for a PO line that has open quantity (order
less its goods receipts 101) and no open ASN yet. ``--reset`` (the demo run, M4-C17) first puts the export's plants
back to exactly the export (``reset_export_plants``): earlier goods receipts against its PO lines are cancelled, and
PO lines and stock rows the export does not hold are removed from those plants, so the next ASN can be received again.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TABLES = {
    "items": ("items", "item", "materials", "material", "item_master", "products"),
    "locations": ("locations", "location", "plants", "plant", "sites"),
    "storage_locations": ("storage_locations", "storage_location", "slocs"),
    "inventory": ("inventory", "stock", "on_hand"),
    "open_supply": ("open_supply", "purchase_orders", "open_pos", "pos", "po_lines", "supply"),
    "suppliers": ("suppliers", "supplier", "vendors"),
}
COLUMNS = {
    "item_code": ("item_code", "material", "material_no", "item"),
    "description": ("description", "item_name", "title", "name"),
    "uom": ("uom", "base_uom", "unit"),
    "barcode": ("barcode", "ean", "gtin"),
    "location_code": ("location_code", "plant", "location", "site_code"),
    "location_name": ("location_name", "name", "description"),
    "storage_location": ("storage_location", "sloc", "lgort"),
    "on_hand_qty": ("on_hand_qty", "on_hand", "quantity", "qty"),
    "kind": ("kind", "type"),
    "ref": ("ref", "po_ref", "po", "purchase_order", "po_number"),
    "po_item": ("po_item", "line", "item_no", "purchase_order_item"),
    "qty": ("qty", "quantity", "open_qty"),
    "due_date": ("due_date", "delivery_date", "date"),
    "status": ("status",),
    "supplier_code": ("supplier_code", "supplier", "vendor"),
    "lane_code": ("lane_code", "lane"),
}
CLOSED = ("received", "closed", "cancelled", "canceled", "done")
SAP_REF = re.compile(r"^(\d+)-(\d{1,6})$")  # 4500001234-10: PO and item in one ref (contract example)


@dataclass
class Export:
    items: dict[str, dict[str, str]] = field(default_factory=dict)
    locations: dict[str, str] = field(default_factory=dict)
    storage_locations: dict[tuple[str, str], str] = field(default_factory=dict)  # (plant, sloc) -> name
    inventory: dict[tuple[str, str], float] = field(default_factory=dict)  # (item, plant) -> plant total
    stock: dict[tuple[str, str, str], float] = field(default_factory=dict)  # (item, plant, sloc or "") -> on-hand
    po_lines: list[dict[str, Any]] = field(default_factory=list)
    suppliers: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _table_of(name: str) -> str | None:
    n = name.strip().lower()
    return next((t for t, names in TABLES.items() if n in names), None)


def _col(row: dict[str, Any], key: str, table: str) -> str:
    names = COLUMNS[key]
    if table in ("locations", "storage_locations") and key == "location_code":
        names = (*names, "code")
    if table == "items" and key == "item_code":
        names = (*names, "code")
    if table == "suppliers" and key == "supplier_code":
        names = (*names, "code")
    if table == "storage_locations" and key == "location_name":
        names = ("name", "description")
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for n in names:
        v = low.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _num(v: str, what: str, notes: list[str]) -> float | None:
    try:
        return float(v.replace(",", "")) if v else None
    except ValueError:
        notes.append(f"ignored {what} {v!r}: not a number")
        return None


def split_ref(ref: str, po_item: str) -> tuple[str, str]:
    """(PO number, PO item) of an open-supply row; see the module doc."""
    if po_item:
        return ref, po_item.lstrip("0") or "0"
    m = SAP_REF.match(ref)
    if m:
        return m.group(1), m.group(2).lstrip("0") or "0"
    return ref, "10"


def _rows_from_file(path: Path, ex: Export) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            yield path.stem, list(csv.DictReader(fh))
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if path.name.lower() == "manifest.json" and isinstance(data, dict) and "export" in data:
        ex.manifest = {k: data[k] for k in ("export", "version", "world", "dataset") if k in data}
        return
    if isinstance(data, list):
        yield path.stem, [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("rows"), list) and data.get("message"):  # an exchange message with rows
            yield str(data["message"]), [r for r in data["rows"] if isinstance(r, dict)]
            return
        parts = data.get("parts")
        tables: dict[str, Any] = parts if isinstance(parts, dict) else data
        for k, v in tables.items():
            if isinstance(v, list):
                yield str(k), [r for r in v if isinstance(r, dict)]
    else:
        ex.notes.append(f"{path.name}: not a JSON list or object, ignored")


def parse_export(folder: Path) -> Export:
    ex = Export()
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".json"))
    if not files:
        ex.notes.append(f"no .csv or .json files in {folder}")
    for path in files:
        try:
            tables = list(_rows_from_file(path, ex))
        except (ValueError, OSError, csv.Error) as e:
            ex.notes.append(f"{path.name}: unreadable ({type(e).__name__}), ignored")
            continue
        for name, rows in tables:
            table = _table_of(name)
            if table is None:
                ex.notes.append(f"{path.name}: table {name!r} ignored ({len(rows)} rows)")
                continue
            _load_table(ex, table, rows, path.name)
    for code, _ in list(ex.inventory):
        ex.items.setdefault(code, {"description": code, "uom": "EA", "barcode": code})
    for line in ex.po_lines:
        ex.items.setdefault(line["item_code"], {"description": line["item_code"], "uom": line["uom"] or "EA",
                                                "barcode": line["item_code"]})
        ex.locations.setdefault(line["location_code"], line["location_code"])
    for _, loc in list(ex.inventory):
        ex.locations.setdefault(loc, loc)
    for loc, _ in list(ex.storage_locations):
        ex.locations.setdefault(loc, loc)
    return ex


def _load_table(ex: Export, table: str, rows: list[dict[str, Any]], src: str) -> None:  # noqa: C901
    for row in rows:
        if table == "items":
            code = _col(row, "item_code", table).upper()
            if code:
                ex.items[code] = {"description": (_col(row, "description", table) or code)[:40],
                                  "uom": (_col(row, "uom", table) or "EA").upper(),
                                  "barcode": _col(row, "barcode", table) or code}
        elif table == "locations":
            code = _col(row, "location_code", table).upper()
            if code:
                ex.locations[code] = _col(row, "location_name", table) or code
        elif table == "storage_locations":
            code, sl = _col(row, "location_code", table).upper(), _col(row, "storage_location", table).upper()
            if code and sl:
                ex.storage_locations[(code, sl)] = _col(row, "location_name", table) or "core export"
        elif table == "suppliers":
            code = _col(row, "supplier_code", table).upper()
            if code:
                ex.suppliers[code] = _col(row, "description", table) or code
        elif table == "inventory":
            code, loc = _col(row, "item_code", table).upper(), _col(row, "location_code", table).upper()
            sl = _col(row, "storage_location", table).upper()
            qty = _num(_col(row, "on_hand_qty", table), "on_hand_qty", ex.notes)
            if code and loc and qty is not None:
                ex.stock[(code, loc, sl)] = qty
                ex.inventory[(code, loc)] = sum(q for (c, p, _), q in ex.stock.items() if (c, p) == (code, loc))
        else:
            kind = (_col(row, "kind", table) or "PO").upper()
            status = _col(row, "status", table).lower()
            if kind != "PO" or status in CLOSED:
                continue
            ref = _col(row, "ref", table)
            po, item = split_ref(ref, _col(row, "po_item", table))
            qty = _num(_col(row, "qty", table), "qty", ex.notes)
            code, loc = _col(row, "item_code", table).upper(), _col(row, "location_code", table).upper()
            if not (po and code and loc and qty and qty > 0):
                ex.notes.append(f"{src}: open_supply row {ref or '?'} ignored (needs ref, item_code, location_code, qty)")
                continue
            ex.po_lines.append({"po": po, "po_item": item, "item_code": code, "location_code": loc, "qty": qty,
                                "due_date": _col(row, "due_date", table),
                                "storage_location": _col(row, "storage_location", table).upper(),
                                "uom": _col(row, "uom", table).upper(), "status": status or "open",
                                "supplier": _col(row, "supplier_code", table).upper(),
                                "lane_code": _col(row, "lane_code", table).upper()})


def default_sloc(sloc: str | None = None) -> str:
    return sloc or os.getenv("FIELD_CORE_EXPORT_SLOC") or "0001"


def plant_slocs(ex: Export, sloc: str | None = None) -> dict[str, list[str]]:
    """Storage locations per plant: the export's, else the default one."""
    out: dict[str, list[str]] = {p: [] for p in ex.locations}
    for plant, sl in ex.storage_locations:
        out.setdefault(plant, []).append(sl)
    return {p: sorted(s) or [default_sloc(sloc)] for p, s in out.items()}


RESET_MARK = "seed-core-export --reset"


def reset_export_plants(cur: Any, ex: Export, slocs: dict[str, list[str]], client: str = "100") -> dict[str, int]:
    """``--reset`` (the demo run, M4-C17): erp-sim's plants of the export go back to exactly what the export holds,
    so a demo can run again after the core's SAMPLE reset (K4: erp-sim, not reset with the core, raised no receive
    task). Only the export's plants are touched:

    1. goods receipts 101 against the export's PO lines are cancelled with the simulator's own item cancel (the flag
       ``POST .../CancelMaterialDocumentItem`` sets; the documents stay), so each line has its open quantity again;
    2. PO lines in those plants that the export does not hold (left by earlier tests or code-map runs) are removed,
       with a PO header left without lines;
    3. stock rows in those plants that the export does not hold are removed.

    The upsert that follows sets stock, PO lines and their status to the export's values, and an ASN is made for every
    PO line that has open quantity and no open ASN."""
    plants = sorted(ex.locations)
    keep = sorted({(ln["po"], ln["po_item"]) for ln in ex.po_lines})
    pos, items = [p for p, _ in keep], [i for _, i in keep]
    cur.execute("UPDATE erpsim.document_item di SET item_data = di.item_data || jsonb_build_object('cancelled', true,"
                " 'cancelled_by', %s::text) FROM unnest(%s::text[], %s::text[]) AS k(po, item)"
                " WHERE di.client = %s AND di.movement_type = '101' AND di.plant = ANY(%s)"
                " AND di.item_data->>'PurchaseOrder' = k.po AND di.item_data->>'PurchaseOrderItem' = k.item"
                " AND COALESCE((di.item_data->>'cancelled')::boolean, false) = false",
                (RESET_MARK, pos, items, client, plants))
    cancelled = int(cur.rowcount or 0)
    cur.execute("DELETE FROM erpsim.purchase_order_item i WHERE i.client = %s AND i.plant = ANY(%s) AND NOT EXISTS"
                " (SELECT 1 FROM unnest(%s::text[], %s::text[]) AS k(po, item)"
                "  WHERE k.po = i.purchase_order AND k.item = i.item_no) RETURNING i.purchase_order",
                (client, plants, pos, items))
    removed = [str(r[0]) for r in cur.fetchall()]
    gone = sorted(set(removed))
    if gone:
        cur.execute("DELETE FROM erpsim.purchase_order h WHERE h.client = %s AND h.purchase_order = ANY(%s)"
                    " AND NOT EXISTS (SELECT 1 FROM erpsim.purchase_order_item i"
                    "  WHERE i.client = h.client AND i.purchase_order = h.purchase_order)", (client, gone))
    stock_keys = sorted({(code, loc, sl or slocs[loc][0]) for (code, loc, sl) in ex.stock})
    cur.execute("DELETE FROM erpsim.stock s WHERE s.client = %s AND s.plant = ANY(%s) AND NOT EXISTS"
                " (SELECT 1 FROM unnest(%s::text[], %s::text[], %s::text[]) AS k(material, plant, sloc)"
                "  WHERE k.material = s.material_no AND k.plant = s.plant AND k.sloc = s.storage_location)",
                (client, plants, [k[0] for k in stock_keys], [k[1] for k in stock_keys], [k[2] for k in stock_keys]))
    stock_gone = int(cur.rowcount or 0)
    return {"gr_items_cancelled": cancelled, "po_lines_removed": len(removed), "stock_rows_removed": stock_gone}


def _needs_asn(cur: Any, client: str, line: dict[str, Any]) -> bool:
    """A PO line gets an ASN when it has open quantity (order less the goods receipts 101 that count, as erp-sim's
    PO read computes it) and no open ASN item references it yet."""
    cur.execute("SELECT 1 FROM erpsim.inbound_delivery d JOIN erpsim.inbound_delivery_item i"
                " USING (client, delivery_document) WHERE d.client = %s AND d.status = 'open' AND i.status = 'open'"
                " AND i.purchase_order = %s AND i.purchase_order_item = %s LIMIT 1", (client, line["po"], line["po_item"]))
    if cur.fetchone():
        return False
    cur.execute("SELECT COALESCE(SUM(di.quantity), 0) FROM erpsim.document_item di"
                " JOIN erpsim.document d USING (client, doc_number, fiscal_year)"
                " WHERE di.client = %s AND di.movement_type = '101' AND di.item_data->>'PurchaseOrder' = %s"
                " AND di.item_data->>'PurchaseOrderItem' = %s AND d.status <> 'reversed'"
                " AND COALESCE((di.item_data->>'cancelled')::boolean, false) = false",
                (client, line["po"], line["po_item"]))
    row = cur.fetchone()
    return float(row[0] if row else 0) < float(line["qty"])


def load_into_erpsim(cur: Any, ex: Export, sloc: str | None = None, client: str = "100",
                     reset: bool = False) -> dict[str, int]:
    """Write the export into erp-sim (one transaction on ``cur``). Returns counts. ``reset``: first make the export's
    plants hold exactly the export again (``reset_export_plants``)."""
    slocs = plant_slocs(ex, sloc)
    reset_counts = reset_export_plants(cur, ex, slocs, client) if reset else {}
    for code, name in ex.locations.items():
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES (%s, %s, %s)"
                    " ON CONFLICT (client, plant) DO UPDATE SET name = EXCLUDED.name", (client, code, name[:60]))
        for sl in slocs[code]:
            cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (client, code, sl, ex.storage_locations.get((code, sl), "core export")[:60]))
    for code, it in ex.items.items():
        cur.execute("INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (client, material_no) DO UPDATE SET description = EXCLUDED.description,"
                    " base_uom = EXCLUDED.base_uom", (client, code, it["description"], it["uom"]))
        cur.execute("INSERT INTO erpsim.material_barcode (client, material_no, barcode, uom, is_main)"
                    " VALUES (%s, %s, %s, %s, true) ON CONFLICT DO NOTHING",
                    (client, code, it.get("barcode") or code, it["uom"]))
    for (code, loc, sl), qty in ex.stock.items():
        cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)"
                    " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (client, plant, storage_location, material_no)"
                    " DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = NOW()",
                    (client, loc, sl or slocs[loc][0], code, qty, ex.items.get(code, {}).get("uom", "EA")))
    by_po: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in ex.po_lines:
        line_sloc = line["storage_location"] or slocs[line["location_code"]][0]
        uom = line["uom"] or ex.items.get(line["item_code"], {}).get("uom", "EA")
        cur.execute("INSERT INTO erpsim.purchase_order (client, purchase_order, supplier) VALUES (%s, %s, %s)"
                    " ON CONFLICT (client, purchase_order) DO UPDATE SET supplier = EXCLUDED.supplier",
                    (client, line["po"], line["supplier"]))
        cur.execute("INSERT INTO erpsim.purchase_order_item (client, purchase_order, item_no, material_no, plant,"
                    " storage_location, order_qty, uom, delivery_date, status, ext)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (client, purchase_order, item_no) DO UPDATE SET material_no = EXCLUDED.material_no,"
                    " plant = EXCLUDED.plant, storage_location = EXCLUDED.storage_location,"
                    " order_qty = EXCLUDED.order_qty, uom = EXCLUDED.uom, delivery_date = EXCLUDED.delivery_date,"
                    " status = EXCLUDED.status, ext = EXCLUDED.ext",
                    (client, line["po"], line["po_item"], line["item_code"], line["location_code"], line_sloc,
                     line["qty"], uom, line["due_date"] or None, line["status"],
                     json.dumps({"lane_code": line["lane_code"]} if line["lane_code"] else {})))
        by_po.setdefault((line["po"], line["location_code"]), []).append({**line, "sloc": line_sloc, "uom": uom})
    asns = 0
    for (po, loc), all_lines in by_po.items():
        lines = [ln for ln in all_lines if _needs_asn(cur, client, ln)]
        if not lines:
            continue
        deliv = _free_delivery_no(cur, client)
        head = {"PurchaseOrder": po, "Source": "core-export", **({"Supplier": lines[0]["supplier"]}
                                                                  if lines[0]["supplier"] else {})}
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status,"
                    " header_data) VALUES (%s, %s, %s, %s, 'open', %s)",
                    (client, deliv, loc, lines[0]["sloc"], json.dumps(head)))
        for n, line in enumerate(lines, start=1):
            cur.execute("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no,"
                        " delivery_qty, actual_qty, uom, status, purchase_order, purchase_order_item)"
                        " VALUES (%s, %s, %s, %s, %s, 0, %s, 'open', %s, %s)",
                        (client, deliv, f"{n * 10:06d}", line["item_code"], line["qty"], line["uom"], po,
                         line["po_item"]))
        asns += 1
    return {**reset_counts, "plants": len(ex.locations), "storage_locations": sum(len(v) for v in slocs.values()),
            "materials": len(ex.items), "stock_rows": len(ex.stock), "po_lines": len(ex.po_lines),
            "asns_created": asns}


def _free_delivery_no(cur: Any, client: str) -> str:
    for _ in range(50):
        cand = f"18{int(time.time() * 1000) % 10**8:08d}"
        cur.execute("SELECT 1 FROM erpsim.inbound_delivery WHERE client = %s AND delivery_document = %s",
                    (client, cand))
        if cur.fetchone() is None:
            return cand
        time.sleep(0.002)
    raise RuntimeError("could not allocate a free delivery number")


# --- the Field site pack ------------------------------------------------------------------------------------------

@dataclass
class SitePack:
    sites: list[dict[str, Any]] = field(default_factory=list)  # code, name, kind, erp_plant, erp_storage_locations
    bins: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # site code -> zone, code, erp_ref
    labels: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


FIELD_SITE_KINDS = ("warehouse", "tower", "plant", "yard", "other")


def parse_site_pack(folder: Path) -> SitePack:
    """The core's ``samples/exports/field-site-pack``: sites.csv, bins.csv, labels.csv (others ignored)."""
    pack = SitePack()

    def rows(name: str) -> list[dict[str, str]]:
        p = folder / name
        if not p.exists():
            pack.notes.append(f"{name} not in {folder}")
            return []
        with p.open(encoding="utf-8-sig", newline="") as fh:
            return [{str(k).strip().lower(): str(v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]

    for r in rows("sites.csv"):
        code = (r.get("site_code") or r.get("code") or "").upper()
        if not re.fullmatch(r"[A-Z0-9-]{2,32}", code):
            pack.notes.append(f"sites.csv: site {code!r} ignored (Field site codes are [A-Z0-9-]{{2,32}})")
            continue
        kind = (r.get("kind") or "warehouse").lower()
        pack.sites.append({
            "code": code, "name": (r.get("name") or code)[:120],
            "kind": kind if kind in FIELD_SITE_KINDS else "warehouse",
            "erp_plant": (r.get("erp_plant") or r.get("core_location_code") or code).upper(),
            "erp_storage_locations": [s for s in (r.get("erp_storage_locations") or "").upper().split("|") if s],
            "timezone": r.get("timezone") or "UTC",
            **({"lat": float(r["lat"]), "lon": float(r["lon"])} if r.get("lat") and r.get("lon") else {}),
        })
    known = {s["code"] for s in pack.sites}
    for r in rows("bins.csv"):
        site, zone, code = (r.get("site_code") or "").upper(), (r.get("zone") or "").upper(), (r.get("code") or "").upper()
        if site not in known or not re.fullmatch(r"[A-Z0-9-]{1,24}", code) or not re.fullmatch(r"[A-Z0-9-]{1,24}", zone):
            pack.notes.append(f"bins.csv: bin {site}/{zone}/{code} ignored")
            continue
        pack.bins.setdefault(site, []).append({"zone": zone, "code": code, "erp_ref": r.get("erp_ref") or ""})
    pack.labels = [r for r in rows("labels.csv") if (r.get("site_code") or "").upper() in known]
    return pack


def create_sites(api: str, token: str, tenant: str, pack: SitePack, existing: dict[str, str],
                 locations: dict[str, dict[str, str]], post: Any = None) -> dict[str, int]:
    """The pack's sites and bins through field-api, as the owner would (POST /v1/sites, POST /v1/locations), by a
    field.admin token of ``tenant``. ``existing``: site code -> id already there; ``locations``: site id -> {code: id}
    already there. Idempotent: nothing that exists is created again. Returns counts."""
    import uuid

    import httpx

    send = post or httpx.post
    h = {"Authorization": f"Bearer {token}"}
    made = {"sites": 0, "sites_kept": 0, "zones": 0, "bins": 0}
    for s in pack.sites:
        sid = existing.get(s["code"])
        if sid:
            made["sites_kept"] += 1
        else:
            body = {k: s[k] for k in ("code", "name", "kind", "erp_plant", "erp_storage_locations", "timezone")}
            body |= {k: s[k] for k in ("lat", "lon") if k in s}
            r = send(f"{api}/v1/sites", json=body, headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
            if r.status_code != 201:
                raise RuntimeError(f"create site {s['code']}: HTTP {r.status_code} {r.text[:300]}")
            sid = str(r.json()["id"])
            existing[s["code"]] = sid
            made["sites"] += 1
        have = locations.setdefault(sid, {})
        for b in pack.bins.get(s["code"], []):
            if b["zone"] not in have:
                r = send(f"{api}/v1/locations", json={"site_id": sid, "kind": "zone", "code": b["zone"]},
                         headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
                if r.status_code != 201:
                    raise RuntimeError(f"create zone {s['code']}/{b['zone']}: HTTP {r.status_code} {r.text[:200]}")
                have[b["zone"]] = str(r.json()["id"])
                made["zones"] += 1
            if b["code"] in have:
                continue
            r = send(f"{api}/v1/locations", json={
                "site_id": sid, "parent_id": have[b["zone"]], "kind": "position", "code": b["code"],
                **({"erp_ref": b["erp_ref"], "erp_ref_type": "storage_bin"} if b["erp_ref"] else {})},
                headers={**h, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
            if r.status_code != 201:
                raise RuntimeError(f"create bin {s['code']}/{b['code']}: HTTP {r.status_code} {r.text[:200]}")
            have[b["code"]] = str(r.json()["id"])
            made["bins"] += 1
    return made
