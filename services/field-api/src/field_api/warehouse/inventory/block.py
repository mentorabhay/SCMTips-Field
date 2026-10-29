"""Inventory Posting Block Engine for Task T3.043 / FR3.033."""

from typing import Any


def is_posting_blocked_for_bin(storage_bin: str, active_pi_documents: list[dict[str, Any]]) -> bool:
    """Enforces posting block on storage bins currently undergoing physical inventory counting."""
    for doc in active_pi_documents:
        if doc.get("status") in ("open", "counting", "recount_required"):
            if doc.get("posting_blocked", False) and storage_bin in doc.get("bins", []):
                return True
    return False
