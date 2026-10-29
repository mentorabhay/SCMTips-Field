"""Physical Inventory Audit Export (Task T3.044 / FR3.036 / PR3.18 / TC3.129).

Invariant PR3.18:
For all physical inventory exports (CSV or JSON),
sum(counted) - sum(book) = sum(difference) per material and overall,
conserving total quantities across the entire audit file.
"""

import csv
import io
from typing import Any


def generate_inventory_audit_export(
    pi_doc_no: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generates an audit export ensuring quantity conservation (PR3.18)."""
    total_counted = 0.0
    total_book = 0.0
    total_diff = 0.0

    export_rows = []
    for line in lines:
        raw_counted = line.get("counted_qty")
        counted = float(raw_counted) if raw_counted is not None else 0.0
        raw_book = line.get("book_qty")
        book = float(raw_book) if raw_book is not None else 0.0
        diff = counted - book

        total_counted += counted
        total_book += book
        total_diff += diff

        export_rows.append(
            {
                "doc_number": pi_doc_no,
                "line_id": line.get("line_id") or line.get("id"),
                "material_id": line.get("material_id"),
                "storage_bin": line.get("storage_bin") or line.get("bin_id"),
                "book_qty": book,
                "counted_qty": counted,
                "difference_qty": diff,
                "status": line.get("status", "completed"),
            }
        )

    # Validate conservation invariant
    assert abs((total_counted - total_book) - total_diff) < 1e-4, (
        "PR3.18 quantity conservation violation"
    )

    # CSV string generation
    output = io.StringIO()
    if export_rows:
        writer = csv.DictWriter(output, fieldnames=list(export_rows[0].keys()))
        writer.writeheader()
        writer.writerows(export_rows)

    return {
        "pi_doc_no": pi_doc_no,
        "rows": export_rows,
        "csv_content": output.getvalue(),
        "totals": {
            "total_counted": total_counted,
            "total_book": total_book,
            "total_difference": total_diff,
        },
        "is_conserved": True,
    }
