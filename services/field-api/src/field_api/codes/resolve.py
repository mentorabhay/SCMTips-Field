"""What a scanned code is on a site (M3 contract sections 2 and 7).

``resolve_code(principal, site_id, code)`` is the CodeResolver seam of track A (the assistant's
``lookup_code`` tool); ``GET /v1/codes/{code}`` (codes/api.py) answers with the same shape.

A code is, in this order:
- ``material``: the material number, its GTIN, or any of its barcodes (field.material_barcode, synced from
  the ERP's MEAN / A_ProductUnitsOfMeasureEAN), among the active materials of the site's plant;
- ``bin``: an active storage bin of the site (field.location, erp_ref_type storage_bin);
- ``serial``: a serial number of equipment the field knows (tower units);
- ``unknown``: none of these. On a sandbox site an unknown code can become a material (sandbox/service.py);
  on a production site it is refused.

Codes compare trimmed and case-insensitively, like the confirmations of the job runner.
Everything runs in the principal's RLS scope: a site outside it is 404.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, TypedDict

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.errors import FieldError

CodeKind = Literal["material", "bin", "serial", "unknown"]


class CodeMaterial(TypedDict):
    material: str
    description: str
    uom: str


class CodeLookup(TypedDict):
    code: str
    kind: CodeKind
    material: CodeMaterial | None
    bin: str | None
    site_mode: str


class SiteInfo(TypedDict):
    id: str
    name: str
    mode: str
    plant: str | None
    storage_locations: list[str]


ERR_SITE = FieldError(code="FIELD-SITE-404-NOT-FOUND", status=404, title="Site not found")


def norm(code: str | None) -> str:
    return (code or "").strip().upper()


def site_info(cur: Any, site_id: str) -> SiteInfo:
    cur.execute(
        "SELECT id, name, mode, erp_plant, erp_storage_locations FROM field.site WHERE id::text = %s",
        (site_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ERR_SITE
    return {"id": str(row[0]), "name": str(row[1]), "mode": str(row[2]), "plant": row[3],
            "storage_locations": list(row[4] or [])}


def find_material(cur: Any, plant: str | None, code: str) -> tuple[str, CodeMaterial] | None:
    """(material id, material) whose number, GTIN or barcode is ``code``, among the plant's active materials."""
    c = norm(code)
    cur.execute(
        """
        SELECT m.id, m.erp_material_no, m.description, m.base_uom FROM field.material m
         WHERE m.status = 'active' AND (%(plant)s::text IS NULL OR m.plant = %(plant)s)
           AND (upper(m.erp_material_no) = %(c)s OR upper(m.gtin) = %(c)s
                OR EXISTS (SELECT 1 FROM field.material_barcode b
                            WHERE b.material_id = m.id AND upper(b.barcode) = %(c)s))
         ORDER BY (upper(m.erp_material_no) = %(c)s) DESC, m.erp_material_no
         LIMIT 1
        """,
        {"plant": plant, "c": c},
    )
    row = cur.fetchone()
    if not row:
        return None
    return str(row[0]), {"material": str(row[1]), "description": str(row[2] or ""), "uom": str(row[3] or "EA")}


def barcodes_of(cur: Any, material_ids: Iterable[str]) -> dict[str, list[str]]:
    """material id -> its barcodes (sorted; may be empty)."""
    ids = sorted({m for m in material_ids if m})
    out: dict[str, list[str]] = {m: [] for m in ids}
    if not ids:
        return out
    cur.execute(
        "SELECT material_id, barcode FROM field.material_barcode WHERE material_id = ANY(%s::uuid[])"
        " ORDER BY material_id, barcode",
        (ids,),
    )
    for mid, code in cur.fetchall():
        out.setdefault(str(mid), []).append(str(code))
    return out


def codes_of_material(cur: Any, material_id: str | None, material_no: str | None, gtin: str | None) -> set[str]:
    """Every normalised code that identifies the line's material: number, GTIN and barcodes."""
    codes = {norm(material_no), norm(gtin)}
    if material_id:
        codes.update(norm(b) for b in barcodes_of(cur, [material_id]).get(material_id, []))
    codes.discard("")
    return codes


def lookup(cur: Any, site: SiteInfo, code: str) -> CodeLookup:
    c = norm(code)
    out: CodeLookup = {"code": code.strip(), "kind": "unknown", "material": None, "bin": None,
                       "site_mode": site["mode"]}
    if not c:
        return out
    found = find_material(cur, site["plant"], c)
    if found:
        out["kind"], out["material"] = "material", found[1]
        return out
    cur.execute(
        "SELECT code FROM field.location WHERE site_id = %s AND upper(code) = %s AND erp_ref_type = 'storage_bin'"
        " AND status = 'active' LIMIT 1",
        (site["id"], c),
    )
    row = cur.fetchone()
    if row:
        out["kind"], out["bin"] = "bin", str(row[0])
        return out
    cur.execute("SELECT 1 FROM field.equipment WHERE upper(serial_no) = %s LIMIT 1", (c,))
    if cur.fetchone():
        out["kind"] = "serial"
    return out


def resolve_code(principal: Principal, site_id: str, code: str) -> CodeLookup:
    """The CodeResolver of the M3 contract (section 7): what ``code`` is on ``site_id`` for this principal."""
    if "*" not in principal.site_ids and site_id not in principal.site_ids:
        raise FieldError(code="FIELD-AUTH-403-SCOPE", status=403, title="Site not in scope")
    with principal_tx(principal) as cur:
        return lookup(cur, site_info(cur, site_id), code)
