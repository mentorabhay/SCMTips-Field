"""Row helpers for psycopg cursors: rows -> JSON-ready dicts (C4)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def jsonable(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [jsonable(x) for x in v]
    return v


def fetch_dicts(cur: Any) -> list[dict[str, Any]]:
    cols = [d.name for d in cur.description]
    return [{c: jsonable(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]


def fetch_dict(cur: Any) -> dict[str, Any] | None:
    rows = fetch_dicts(cur)
    return rows[0] if rows else None
