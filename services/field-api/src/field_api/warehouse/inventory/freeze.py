"""Book Inventory Freeze Snapshot Engine (Task T3.043 / FR3.035 / PR3.16 / TC3.128).

Invariant PR3.16:
For all physical inventory documents with freeze_book = true,
book_qty used for difference calculation strictly equals the frozen snapshot
captured at document creation time, unaffected by subsequent goods movements.
"""

from datetime import UTC, datetime
from typing import Any


class FreezeSnapshotManager:
    """Manages frozen book inventory snapshots."""

    @staticmethod
    def capture_freeze_snapshot(
        lines: list[dict[str, Any]],
        current_erp_stock: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Snapshots book stock at document creation time."""
        snapshot_at = datetime.now(UTC).isoformat()
        frozen_lines = []

        for line in lines:
            mat = line.get("material_id", "")
            loc = line.get("storage_location", "")
            stock_key = f"{mat}:{loc}" if loc else mat
            book_qty = current_erp_stock.get(stock_key, float(line.get("book_qty", 0.0)))

            frozen_copy = dict(line)
            frozen_copy["frozen_book_qty"] = book_qty
            frozen_copy["frozen_at"] = snapshot_at
            frozen_lines.append(frozen_copy)

        return frozen_lines

    @staticmethod
    def resolve_effective_book_qty(
        line: dict[str, Any],
        is_freeze_enabled: bool,
        current_live_stock: float,
    ) -> float:
        """Returns frozen quantity if freeze is enabled; otherwise uses live stock (PR3.16)."""
        if is_freeze_enabled and "frozen_book_qty" in line:
            return float(line["frozen_book_qty"])
        return current_live_stock
