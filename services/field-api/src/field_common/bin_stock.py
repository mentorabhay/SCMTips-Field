"""Field-side stock by storage bin (FR3.013 / FR3.014), shared by field-api and field-worker.

SAP IM (the SAMPLE plant) books stock per storage location and has no bins, so the field keeps which
bin holds what in ``field.bin_stock``. Put-away adds to the confirmed bin, a posted goods issue takes
from the pick bin, a posted PI difference sets the counted quantity. The put-away proposal and the
pick stops read it.

Every function runs on the caller's cursor (and so inside the caller's transaction and RLS scope).

Walking order: bins are visited in code order (zone-aisle-level, e.g. 02-01-01 < 02-03-04 < 03-05-01).
The graph-distance ordering of FR3.026 needs a site graph; the SAMPLE site has none (T3.035 partial).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg


def storage_bins(cur: psycopg.Cursor[Any], site_id: str) -> list[str]:
    """Active storage bins of a site (field.location, erp_ref_type 'storage_bin'), in walking order."""
    cur.execute(
        "SELECT code FROM field.location WHERE site_id = %s AND erp_ref_type = 'storage_bin' AND status = 'active'"
        " ORDER BY code",
        (site_id,),
    )
    return [str(r[0]) for r in cur.fetchall()]


def walking_order(bins: list[str]) -> list[str]:
    """Stops in walking order: zone, aisle, level (the bin code order). Stable for equal codes."""
    return sorted(bins)


def bin_of_material(cur: psycopg.Cursor[Any], site_id: str, material_no: str) -> str | None:
    """The bin that holds the material (most stock first), or None."""
    cur.execute(
        "SELECT storage_bin FROM field.bin_stock WHERE site_id = %s AND material_no = %s AND quantity > 0"
        " ORDER BY quantity DESC, storage_bin LIMIT 1",
        (site_id, material_no),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def propose_bin(
    cur: psycopg.Cursor[Any], site_id: str, material_no: str, reserved: set[str] | None = None
) -> tuple[str | None, str]:
    """Put-away bin for a material: (bin, rule).

    rule ``fixed``: the bin that already holds this material (one material, one bin);
    rule ``empty``: the first empty bin in walking order that no open put-away line has reserved;
    rule ``shared``: no empty bin is left, so the least-filled bin (a mixed bin; the spec's
    "nearest empty bin" cannot be met). ``(None, 'none')`` when the site has no storage bins.
    """
    fixed = bin_of_material(cur, site_id, material_no)
    if fixed:
        return fixed, "fixed"
    bins = storage_bins(cur, site_id)
    if not bins:
        return None, "none"
    cur.execute(
        "SELECT storage_bin, SUM(quantity) FROM field.bin_stock WHERE site_id = %s AND quantity > 0"
        " GROUP BY storage_bin",
        (site_id,),
    )
    filled = {str(r[0]): Decimal(r[1]) for r in cur.fetchall()}
    cur.execute(
        "SELECT l.storage_bin FROM field.task_line l JOIN field.task t ON t.id = l.task_id"
        " WHERE t.site_id = %s AND t.type = 'putaway' AND l.storage_bin IS NOT NULL"
        " AND l.status NOT IN ('done', 'posted', 'cancelled')",
        (site_id,),
    )
    taken = {str(r[0]) for r in cur.fetchall()} | set(reserved or ())
    for b in bins:
        if b not in filled and b not in taken:
            return b, "empty"
    return min(bins, key=lambda b: (filled.get(b, Decimal(0)), b)), "shared"


def change_stock(
    cur: psycopg.Cursor[Any],
    *,
    tenant_id: str,
    site_id: str,
    storage_bin: str,
    material_no: str,
    delta: Decimal | None = None,
    set_to: Decimal | None = None,
    material_id: str | None = None,
    uom: str = "EA",
) -> Decimal:
    """Add ``delta`` (may be negative; never below zero) or set the quantity; returns the new quantity."""
    if (delta is None) == (set_to is None):
        raise ValueError("give exactly one of delta or set_to")
    cur.execute(
        "SELECT quantity FROM field.bin_stock WHERE site_id = %s AND storage_bin = %s AND material_no = %s FOR UPDATE",
        (site_id, storage_bin, material_no),
    )
    row = cur.fetchone()
    current = Decimal(row[0]) if row else Decimal(0)
    new = set_to if set_to is not None else current + (delta or Decimal(0))
    new = max(Decimal(0), Decimal(new))
    cur.execute(
        """
        INSERT INTO field.bin_stock (tenant_id, site_id, storage_bin, material_no, material_id, quantity, uom)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, site_id, storage_bin, material_no)
        DO UPDATE SET quantity = EXCLUDED.quantity, material_id = COALESCE(EXCLUDED.material_id, field.bin_stock.material_id),
                      updated_at = NOW()
        """,
        (tenant_id, site_id, storage_bin, material_no, material_id, new, uom),
    )
    return new
