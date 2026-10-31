"""Load the core's drone-world export into erp-sim (`stack seed-core-export <dir>`; M4 contract section 4, F4).

The SCMTIPS core session writes its SAMPLE dataset to ``ARO\\samples\\exports\\erp-sim\\`` as "CSV + JSON" with the
material codes, plants and open POs (handover 01 F4, 01a "Codes"). That folder does not exist yet, so its exact
layout is unknown; this loader is tolerant and reports what it assumed. It recognises:

- JSON: an exchange-contract ``erp_extract`` envelope (``{"parts": {"inventory": [...], "open_supply": [...]}}``),
  an object of tables (``{"items": [...], "locations": [...], ...}``), or a list of rows named by the file name;
- CSV: one table per file, named by the file name (header row, comma separated).

Tables (file / key names, case-insensitive): items (items, materials, item_master, products), locations
(locations, plants, sites), inventory (inventory, stock, on_hand), open_supply (open_supply, purchase_orders,
open_pos, pos, po_lines, supply). ``bom`` and anything else is reported and ignored. Columns use the exchange
contract's names, with a few aliases (material -> item_code, plant -> location_code, ...).

Loaded into erp-sim with the core's codes as the ERP's codes (so the feed rows need no mapping): plants, one storage
location per plant (FIELD_CORE_EXPORT_SLOC, default 0001), materials with barcode = code, absolute on-hand, and for
every open PO line one inbound delivery (ASN) per PO whose items reference the PO lines, so receiving it posts a GR
101 against them. Re-running is safe: existing rows are updated, an ASN per PO is made once.
"""

from __future__ import annotations

import csv
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TABLES = {
    "items": ("items", "item", "materials", "material", "item_master", "products"),
    "locations": ("locations", "location", "plants", "plant", "sites"),
    "inventory": ("inventory", "stock", "on_hand"),
    "open_supply": ("open_supply", "purchase_orders", "open_pos", "pos", "po_lines", "supply"),
}
COLUMNS = {
    "item_code": ("item_code", "material", "material_no", "item"),
    "description": ("description", "item_name", "title", "name"),
    "uom": ("uom", "base_uom", "unit"),
    "location_code": ("location_code", "plant", "location", "site_code"),
    "location_name": ("location_name", "name", "description"),
    "on_hand_qty": ("on_hand_qty", "on_hand", "quantity", "qty"),
    "kind": ("kind", "type"),
    "ref": ("ref", "po_ref", "po", "purchase_order", "po_number"),
    "po_item": ("po_item", "line", "item_no", "purchase_order_item"),
    "qty": ("qty", "quantity", "open_qty"),
    "due_date": ("due_date", "delivery_date", "date"),
    "status": ("status",),
}
CLOSED = ("received", "closed", "cancelled", "canceled", "done")


@dataclass
class Export:
    items: dict[str, dict[str, str]] = field(default_factory=dict)
    locations: dict[str, str] = field(default_factory=dict)
    inventory: dict[tuple[str, str], float] = field(default_factory=dict)
    po_lines: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _table_of(name: str) -> str | None:
    n = name.strip().lower()
    return next((t for t, names in TABLES.items() if n in names), None)


def _col(row: dict[str, Any], key: str, table: str) -> str:
    names = COLUMNS[key]
    if table == "locations" and key == "location_code":
        names = (*names, "code")
    if table == "items" and key == "item_code":
        names = (*names, "code")
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


def _rows_from_file(path: Path, notes: list[str]) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            yield path.stem, list(csv.DictReader(fh))
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
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
        notes.append(f"{path.name}: not a JSON list or object, ignored")


def parse_export(folder: Path) -> Export:
    ex = Export()
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".json"))
    if not files:
        ex.notes.append(f"no .csv or .json files in {folder}")
    for path in files:
        try:
            tables = list(_rows_from_file(path, ex.notes))
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
        ex.items.setdefault(code, {"description": code, "uom": "EA"})
    for line in ex.po_lines:
        ex.items.setdefault(line["item_code"], {"description": line["item_code"], "uom": "EA"})
        ex.locations.setdefault(line["location_code"], line["location_code"])
    for _, loc in list(ex.inventory):
        ex.locations.setdefault(loc, loc)
    return ex


def _load_table(ex: Export, table: str, rows: list[dict[str, Any]], src: str) -> None:  # noqa: C901
    for row in rows:
        if table == "items":
            code = _col(row, "item_code", table).upper()
            if code:
                ex.items[code] = {"description": (_col(row, "description", table) or code)[:40],
                                  "uom": (_col(row, "uom", table) or "EA").upper()}
        elif table == "locations":
            code = _col(row, "location_code", table).upper()
            if code:
                ex.locations[code] = _col(row, "location_name", table) or code
        elif table == "inventory":
            code, loc = _col(row, "item_code", table).upper(), _col(row, "location_code", table).upper()
            qty = _num(_col(row, "on_hand_qty", table), "on_hand_qty", ex.notes)
            if code and loc and qty is not None:
                ex.inventory[(code, loc)] = qty
        else:
            kind = (_col(row, "kind", table) or "PO").upper()
            status = _col(row, "status", table).lower()
            if kind != "PO" or status in CLOSED:
                continue
            ref = _col(row, "ref", table)
            po, sep, item = ref.partition("-")
            item = item if sep else (_col(row, "po_item", table) or "10")
            qty = _num(_col(row, "qty", table), "qty", ex.notes)
            code, loc = _col(row, "item_code", table).upper(), _col(row, "location_code", table).upper()
            if not (po and code and loc and qty and qty > 0):
                ex.notes.append(f"{src}: open_supply row {ref or '?'} ignored (needs ref, item_code, location_code, qty)")
                continue
            ex.po_lines.append({"po": po, "po_item": item.lstrip("0") or "0", "item_code": code, "location_code": loc,
                                "qty": qty, "due_date": _col(row, "due_date", table)})


def load_into_erpsim(cur: Any, ex: Export, sloc: str | None = None, client: str = "100") -> dict[str, int]:
    """Write the export into erp-sim (one transaction on ``cur``). Returns counts."""
    sl = sloc or os.getenv("FIELD_CORE_EXPORT_SLOC") or "0001"
    for code, name in ex.locations.items():
        cur.execute("INSERT INTO erpsim.plant (client, plant, name) VALUES (%s, %s, %s)"
                    " ON CONFLICT (client, plant) DO UPDATE SET name = EXCLUDED.name", (client, code, name[:60]))
        cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                    " VALUES (%s, %s, %s, 'core export') ON CONFLICT DO NOTHING", (client, code, sl))
    for code, it in ex.items.items():
        cur.execute("INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (client, material_no) DO UPDATE SET description = EXCLUDED.description,"
                    " base_uom = EXCLUDED.base_uom", (client, code, it["description"], it["uom"]))
        cur.execute("INSERT INTO erpsim.material_barcode (client, material_no, barcode, uom, is_main)"
                    " VALUES (%s, %s, %s, %s, true) ON CONFLICT DO NOTHING", (client, code, code, it["uom"]))
    for (code, loc), qty in ex.inventory.items():
        cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)"
                    " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (client, plant, storage_location, material_no)"
                    " DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = NOW()",
                    (client, loc, sl, code, qty, ex.items.get(code, {}).get("uom", "EA")))
    asns = 0
    by_po: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in ex.po_lines:
        by_po.setdefault((line["po"], line["location_code"]), []).append(line)
    for (po, loc), lines in by_po.items():
        cur.execute("SELECT 1 FROM erpsim.inbound_delivery WHERE client = %s AND header_data->>'PurchaseOrder' = %s",
                    (client, po))
        if cur.fetchone():
            continue
        deliv = _free_delivery_no(cur, client)
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status,"
                    " header_data) VALUES (%s, %s, %s, %s, 'open', %s)",
                    (client, deliv, loc, sl, json.dumps({"PurchaseOrder": po, "Source": "core-export"})))
        for n, line in enumerate(lines, start=1):
            cur.execute("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no,"
                        " delivery_qty, actual_qty, uom, status, purchase_order, purchase_order_item)"
                        " VALUES (%s, %s, %s, %s, %s, 0, %s, 'open', %s, %s)",
                        (client, deliv, f"{n * 10:06d}", line["item_code"], line["qty"],
                         ex.items.get(line["item_code"], {}).get("uom", "EA"), po, line["po_item"]))
        asns += 1
    return {"plants": len(ex.locations), "materials": len(ex.items), "stock_rows": len(ex.inventory),
            "po_lines": len(ex.po_lines), "asns_created": asns}


def _free_delivery_no(cur: Any, client: str) -> str:
    for _ in range(50):
        cand = f"18{int(time.time() * 1000) % 10**8:08d}"
        cur.execute("SELECT 1 FROM erpsim.inbound_delivery WHERE client = %s AND delivery_document = %s",
                    (client, cand))
        if cur.fetchone() is None:
            return cand
        time.sleep(0.002)
    raise RuntimeError("could not allocate a free delivery number")
