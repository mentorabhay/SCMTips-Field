"""Blind Count Projection Engine (Task T3.038 / FR3.029 / PR3.03 / TC3.123).

Invariant PR3.03:
For all physical inventory queries returned to an operator session,
no response contains book_qty, book_value, difference_qty, or difference_value.
Only field.pi.book.read role sees book quantities in the supervisor console after count commitment.
"""

from typing import Any

FORBIDDEN_OPERATOR_FIELDS = frozenset({
    "book_qty",
    "book_quantity",
    "book_value",
    "book_val",
    "difference_qty",
    "diff_qty",
    "difference_value",
    "diff_value",
    "expected_qty",
})


def project_operator_count_line(raw_line: dict[str, Any]) -> dict[str, Any]:
    """Filters all book/difference fields from an inventory line for blind counting (PR3.03)."""
    projected = {}
    for k, v in raw_line.items():
        if k.lower() in FORBIDDEN_OPERATOR_FIELDS:
            continue
        projected[k] = v

    # Explicit blind count structure (T3.038 / OperatorCountLine)
    return {
        "line_id": projected.get("line_id") or projected.get("id"),
        "pi_doc_id": projected.get("pi_doc_id"),
        "storage_bin": projected.get("storage_bin") or projected.get("bin_id"),
        "material_id": projected.get("material_id"),
        "counted_qty": projected.get("counted_qty"),
        "status": projected.get("status", "open"),
        "uom": projected.get("uom", "EA"),
    }


def project_inventory_response(
    data: list[dict[str, Any]] | dict[str, Any],
    has_supervisor_book_permission: bool = False,
) -> Any:
    """Recursively redacts book and difference fields unless caller has supervisor book permission."""
    if has_supervisor_book_permission:
        return data

    if isinstance(data, list):
        return [project_inventory_response(item, False) for item in data]

    if isinstance(data, dict):
        clean_dict = {}
        for k, v in data.items():
            if k.lower() in FORBIDDEN_OPERATOR_FIELDS:
                continue
            if isinstance(v, (dict, list)):
                clean_dict[k] = project_inventory_response(v, False)
            else:
                clean_dict[k] = v
        return clean_dict

    return data
