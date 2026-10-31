"""ERP Sim Stock Ledger & Conservation Rules (Task T1.048 / PR1.07).

Enforces exact inventory conservation:
- 101 (GR): +qty
- 102 (Reversal of 101): -qty
- 601 (GI): -qty
- 602 (Reversal of 601): +qty
- 701 (PI Gain): +qty
- 702 (PI Loss): -qty
- 321 (Transfer QI to Unrestricted): moves between storage locations or state
"""

from decimal import Decimal
from typing import Any

import psycopg


class InsufficientStockError(Exception):
    """Raised when Goods Issue exceeds available stock without negative stock allowed."""

    def __init__(self, material_no: str, requested: Decimal, available: Decimal) -> None:
        super().__init__(
            f"Deficit of stock for material {material_no}: requested {requested}, available {available} [ZSIM/DEFICIT]"
        )
        self.code = "ZSIM/DEFICIT"


def get_current_stock(
    cur: psycopg.Cursor[Any],
    client: str,
    plant: str,
    storage_location: str,
    material_no: str,
) -> Decimal:
    """Return current stock quantity (or 0.000)."""
    cur.execute(
        """
        SELECT quantity FROM erpsim.stock
        WHERE client = %s AND plant = %s AND storage_location = %s AND material_no = %s;
    """,
        (client, plant, storage_location, material_no),
    )
    row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal("0.000")


def apply_movement(
    cur: psycopg.Cursor[Any],
    client: str,
    plant: str,
    storage_location: str,
    material_no: str,
    quantity: Decimal,
    movement_type: str,
    uom: str = "EA",
) -> Decimal:
    """Apply movement type delta to stock table and return new balance."""
    deltas = {
        "101": Decimal("1.0"),
        "102": Decimal("-1.0"),
        "601": Decimal("-1.0"),
        "602": Decimal("1.0"),
        "701": Decimal("1.0"),
        "702": Decimal("-1.0"),
        "321": Decimal("0.0"),  # Internal status shift
        "561": Decimal("1.0"),  # initial entry of stock balances (M3 sandbox opening stock)
        "562": Decimal("-1.0"),  # reversal of 561
    }

    factor = deltas.get(movement_type, Decimal("1.0"))
    delta_qty = quantity * factor

    current_qty = get_current_stock(cur, client, plant, storage_location, material_no)
    new_qty = current_qty + delta_qty

    cur.execute(
        """
        INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (client, plant, storage_location, material_no)
        DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = NOW();
    """,
        (client, plant, storage_location, material_no, new_qty, uom),
    )

    return new_qty
