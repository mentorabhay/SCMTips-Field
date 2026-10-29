"""Cycle Count Rule Scheduler and Background Poller (Task T3.037 / FR3.028 / TC3.122).

Enforces:
1. ABC classification counting frequencies (A: 30 days, B: 90 days, C: 180 days).
2. Dynamic exception triggers (short_pick, putaway_mismatch).
3. Groups due items into batches <= FIELD_PI_MAX_ITEMS.
"""

from datetime import datetime, timedelta
from typing import Any

DEFAULT_ABC_INTERVALS_DAYS = {
    "A": 30,
    "B": 90,
    "C": 180,
}

FIELD_PI_MAX_ITEMS = 50


class CycleCountScheduler:
    """Evaluates items due for physical cycle counting."""

    @staticmethod
    def is_item_due(
        last_counted_at: datetime | None,
        abc_class: str,
        now: datetime | None = None,
        has_exception_trigger: bool = False,
    ) -> bool:
        """Determines if item is due based on ABC cycle interval or exception trigger."""
        if has_exception_trigger:
            return True  # Immediate cycle count required (e.g. short-pick)

        if last_counted_at is None:
            return True  # Never counted

        current_time = now or datetime.utcnow()
        interval_days = DEFAULT_ABC_INTERVALS_DAYS.get(abc_class.upper(), 90)
        due_date = last_counted_at + timedelta(days=interval_days)
        return current_time >= due_date

    @staticmethod
    def group_due_items_into_batches(
        due_items: list[dict[str, Any]],
        max_batch_size: int = FIELD_PI_MAX_ITEMS,
    ) -> list[list[dict[str, Any]]]:
        """Batches due items into requests <= FIELD_PI_MAX_ITEMS."""
        batches = []
        for i in range(0, len(due_items), max_batch_size):
            batches.append(due_items[i : i + max_batch_size])
        return batches
