"""ERP Sim Number Range Allocation Engine (Task T1.043 / PR1.05).

Allocates strictly monotonic numbers within a transaction:
UPDATE erpsim.number_range SET current = current + 1
WHERE object = :o AND client = :c AND current < upper
RETURNING current
"""

from datetime import UTC, datetime
from typing import Any

import psycopg


class NumberRangeExhaustedError(Exception):
    """Raised when number range reaches its upper bound."""

    pass


def allocate_number(
    cur: psycopg.Cursor[Any],
    client: str,
    object_name: str,
) -> int:
    """Atomically allocate the next number for object_name under client."""
    cur.execute(
        """
        UPDATE erpsim.number_range
        SET current = current + 1
        WHERE client = %s AND object = %s AND current < upper
        RETURNING current;
    """,
        (client, object_name),
    )
    row = cur.fetchone()
    if not row:
        # Check if row exists or exhausted
        cur.execute(
            """
            SELECT current, upper FROM erpsim.number_range
            WHERE client = %s AND object = %s;
        """,
            (client, object_name),
        )
        existing = cur.fetchone()
        if not existing:
            raise KeyError(
                f"Number range object '{object_name}' not configured for client '{client}'"
            )
        raise NumberRangeExhaustedError(
            f"Number range '{object_name}' exhausted (current={existing[0]}, upper={existing[1]})"
        )
    return int(row[0])


def allocate_material_document_number(
    cur: psycopg.Cursor[Any],
    client: str,
) -> tuple[str, str]:
    """Allocate a 10-digit material document number and current fiscal year."""
    num = allocate_number(cur, client, "MATERIAL_DOCUMENT")
    doc_year = str(datetime.now(UTC).year)
    return str(num), doc_year
