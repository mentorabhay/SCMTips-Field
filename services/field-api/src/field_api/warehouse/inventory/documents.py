"""Physical Inventory Documents Manager (Task T3.036 / FR3.027 / TC3.121).

Manages physical inventory document lifecycle:
plant, storage location, bins or materials, planned count date, freeze_book, posting_blocked.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field


class PiDocumentCreate(BaseModel):
    plant: str
    storage_location: str
    bins: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    planned_count_date: date = Field(default_factory=date.today)
    freeze_book: bool = True
    posting_blocked: bool = True


class PiDocumentRecord(BaseModel):
    id: str
    doc_number: str
    fiscal_year: str
    plant: str
    storage_location: str
    status: str
    freeze_book: bool
    posting_blocked: bool
    created_at: str


class PiDocumentManager:
    """Creates and manages PI documents."""

    @staticmethod
    def create_document(
        req: PiDocumentCreate,
        fiscal_year: str = "2026",
        doc_counter: int = 1,
    ) -> dict[str, Any]:
        doc_id = str(uuid.uuid4())
        doc_no = f"100{str(doc_counter).zfill(7)}"

        return {
            "id": doc_id,
            "doc_number": doc_no,
            "fiscal_year": fiscal_year,
            "plant": req.plant,
            "storage_location": req.storage_location,
            "bins": req.bins,
            "materials": req.materials,
            "planned_count_date": str(req.planned_count_date),
            "freeze_book": req.freeze_book,
            "posting_blocked": req.posting_blocked,
            "status": "open",
            "created_at": datetime.now(UTC).isoformat(),
        }
