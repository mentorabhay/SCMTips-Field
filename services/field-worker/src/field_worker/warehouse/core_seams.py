"""Core Linkage, Guided-Load Imports, and Late-Receipt Signals (WS3.9 / Tasks T3.068 - T3.072).

Integrates field operations with the core's supply chain seams (planning / APS):
1. Guided-load delivery schedule importer (T3.068 / FR3.056).
2. Late-receipt signal generator (T3.069 / FR3.057).
3. Real-time dock-to-stock and inventory accuracy signal broadcast (T3.070 / FR3.058).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any


class CoreSeamsManager:
    """Manages upstream and downstream synchronization with core planning engines."""

    @staticmethod
    def import_guided_load_schedules(
        schedules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Imports delivery schedules from core planning into guided-load tasks (T3.068)."""
        imported_tasks = []
        for sched in schedules:
            task_id = str(uuid.uuid4())
            imported_tasks.append(
                {
                    "task_id": task_id,
                    "delivery_no": sched.get("delivery_no"),
                    "carrier": sched.get("carrier", "STANDARD_CARRIER"),
                    "expected_arrival": sched.get("expected_arrival"),
                    "priority": sched.get("priority", 50),
                    "line_items_count": len(sched.get("items", [])),
                    "status": "scheduled",
                }
            )
        return imported_tasks

    @staticmethod
    def evaluate_late_receipt_signals(
        deliveries: list[dict[str, Any]],
        current_time: datetime | None = None,
        grace_period_mins: int = 30,
    ) -> list[dict[str, Any]]:
        """Detects overdue inbound shipments and generates late-receipt signals (T3.069 / FR3.057)."""
        now = current_time or datetime.utcnow()
        signals = []

        for deliv in deliveries:
            arrival_str = deliv.get("expected_arrival")
            if not arrival_str:
                continue

            try:
                expected_at = datetime.fromisoformat(arrival_str.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except Exception:
                continue

            deadline = expected_at + timedelta(minutes=grace_period_mins)
            is_arrived = deliv.get("is_arrived", False) or deliv.get("status") in (
                "received",
                "in_progress",
            )

            if now > deadline and not is_arrived:
                delay_mins = (now - expected_at).total_seconds() / 60.0
                signals.append(
                    {
                        "signal_type": "LATE_RECEIPT_ALERT",
                        "delivery_no": deliv.get("delivery_no"),
                        "vendor": deliv.get("vendor", "UNKNOWN_VENDOR"),
                        "expected_arrival": arrival_str,
                        "delay_minutes": delay_mins,
                        "severity": "HIGH" if delay_mins > 120 else "MEDIUM",
                        "emitted_at": now.isoformat(),
                    }
                )

        return signals

    @staticmethod
    def calculate_inventory_accuracy_metric(
        count_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Computes inventory accuracy KPI percentage (T3.070 / FR3.058)."""
        if not count_records:
            return {"accuracy_pct": 100.0, "total_lines": 0, "discrepancies": 0}

        total = len(count_records)
        accurate = sum(1 for r in count_records if float(r.get("difference_qty", 0.0)) == 0.0)
        discrepancies = total - accurate

        accuracy_pct = (accurate / total) * 100.0
        return {
            "accuracy_pct": round(accuracy_pct, 2),
            "total_lines": total,
            "discrepancies": discrepancies,
            "meets_target": accuracy_pct >= 98.0,
        }
