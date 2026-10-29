"""Warehouse Metrics and Dock-to-Stock Durations (Task T3.027 / FR3.016 / FR3.056 / TC3.113).

Calculates dock-to-stock durations (from receipt arrival at dock to putaway bin confirmation)
and computes p50 / p90 percentiles without external heavy math dependencies.
"""

from datetime import datetime
from typing import Any


def compute_dock_to_stock_duration_minutes(
    dock_arrival: datetime | str,
    stock_putaway: datetime | str,
) -> float:
    """Calculate elapsed minutes between dock arrival and putaway confirmation."""
    t0 = (
        datetime.fromisoformat(str(dock_arrival).replace("Z", "+00:00"))
        if isinstance(dock_arrival, str)
        else dock_arrival
    )
    t1 = (
        datetime.fromisoformat(str(stock_putaway).replace("Z", "+00:00"))
        if isinstance(stock_putaway, str)
        else stock_putaway
    )
    diff_s = (t1 - t0).total_seconds()
    return round(diff_s / 60.0, 2)


def compute_percentile(sorted_values: list[float], percentile: float) -> float:
    """Compute percentile using standard linear interpolation."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    n = len(sorted_values)
    idx = (n - 1) * (percentile / 100.0)
    low = int(idx)
    high = min(low + 1, n - 1)
    weight = idx - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def compute_dock_to_stock_metrics(
    records: list[dict[str, Any]] | list[float],
) -> dict[str, Any]:
    """Compute p50, p90, mean, min, and max dock-to-stock durations in minutes.

    Can accept either a list of minute floats or a list of dicts with 'dock_arrival' and 'stock_putaway'.
    TC3.113 asserts p50 = 38 min and p90 = 104 min for its 10-HU test fixture.
    """
    if not records:
        return {
            "p50_minutes": 0.0,
            "p90_minutes": 0.0,
            "mean_minutes": 0.0,
            "min_minutes": 0.0,
            "max_minutes": 0.0,
            "sample_count": 0,
        }

    durations: list[float] = []
    if isinstance(records[0], (int, float)):
        durations = [float(x) for x in records]
    else:
        for r in records:
            d = compute_dock_to_stock_duration_minutes(r["dock_arrival"], r["stock_putaway"])
            durations.append(d)

    durations.sort()
    p50 = compute_percentile(durations, 50.0)
    p90 = compute_percentile(durations, 90.0)
    mean = sum(durations) / len(durations)

    return {
        "p50_minutes": round(p50, 1),
        "p90_minutes": round(p90, 1),
        "mean_minutes": round(mean, 1),
        "min_minutes": round(float(durations[0]), 1),
        "max_minutes": round(float(durations[-1]), 1),
        "sample_count": len(durations),
    }
