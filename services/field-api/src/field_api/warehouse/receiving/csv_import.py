"""CSV Inbound Delivery Import with Guided-Load Conventions (Task T3.017 / FR3.002 / TC3.102).

Implements:
- SAP delivery export CSV parsing with column mapping.
- Material matching ladder:
  - Exact material code match: 1.0 (Auto-accept)
  - Barcode / GTIN match: 0.98 (Auto-accept)
  - Fuzzy text similarity:
    - Auto-accept when top score >= 0.95 AND no rival within 0.05.
    - Otherwise marked as 'review' (ambiguous or low confidence).
- Two-stage workflow:
  1. Preview: returns summary with auto-accepted count and review rows.
  2. Confirm: creates tasks and task_lines after review decisions.
"""

import csv
import difflib
import io
import os
import uuid
from typing import Any

import psycopg
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


class CsvColumnMapping(BaseModel):
    delivery_document: str = "DeliveryDocument"
    item_no: str = "DeliveryDocumentItem"
    material: str = "Material"
    quantity: str = "ActualDeliveryQuantity"
    uom: str = "DeliveryQuantityUnit"
    plant: str = "ReceivingPlant"
    storage_location: str = "StorageLocation"


class ImportedRow(BaseModel):
    row_index: int
    delivery_document: str
    item_no: int
    raw_material: str
    matched_material_id: str | None = None
    matched_material_code: str | None = None
    match_score: float = 0.0
    status: str = "auto_accepted"  # 'auto_accepted' | 'review' | 'rejected'
    quantity: float
    uom: str = "EA"
    plant: str = "1010"
    storage_location: str = "101A"
    rival_score: float | None = None


class CsvImportPreview(BaseModel):
    preview_token: str
    total_rows: int
    auto_accepted_count: int
    review_count: int
    rows: list[ImportedRow]


# In-memory preview cache for confirm stage: token -> (tenant_id, site_id, rows)
_PREVIEWS: dict[str, tuple[str, str, list[dict[str, Any]]]] = {}


def match_material_ladder(
    raw_mat: str,
    known_materials: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float, float | None, str]:
    """Apply the material matching ladder.

    Returns:
        (matched_material, top_score, runner_up_score, decision)
        decision is 'auto_accepted' if top_score >= 0.95 and no rival within 0.05, else 'review'.
    """
    cleaned = raw_mat.strip()
    if not cleaned or not known_materials:
        return None, 0.0, None, "review"

    # 1. Exact match on code
    for mat in known_materials:
        if mat["code"].upper() == cleaned.upper():
            return mat, 1.0, None, "auto_accepted"

    # 2. Exact match on GTIN / barcode
    for mat in known_materials:
        if mat.get("gtin") and mat["gtin"] == cleaned:
            return mat, 0.98, None, "auto_accepted"

    # 3. Fuzzy match against code and name
    scored: list[tuple[float, dict[str, Any]]] = []
    for mat in known_materials:
        s1 = difflib.SequenceMatcher(None, cleaned.upper(), mat["code"].upper()).ratio()
        s2 = (
            difflib.SequenceMatcher(None, cleaned.lower(), mat["name"].lower()).ratio()
            if mat.get("name")
            else 0.0
        )
        best_s = max(s1, s2)
        scored.append((round(best_s, 3), mat))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, None, "review"

    top_score, top_mat = scored[0]
    rival_score = scored[1][0] if len(scored) > 1 else None

    # Auto-accept rule: top_score >= 0.95 with no rival within 0.05
    if top_score >= 0.95 and (rival_score is None or (top_score - rival_score) >= 0.05):
        return top_mat, top_score, rival_score, "auto_accepted"
    else:
        return top_mat, top_score, rival_score, "review"


def parse_and_preview_csv(
    tenant_id: str,
    site_id: str,
    csv_text: str,
    mapping: CsvColumnMapping | None = None,
    known_materials: list[dict[str, Any]] | None = None,
    db_url: str = DATABASE_URL,
) -> CsvImportPreview:
    """Parse CSV, execute matching ladder, and produce preview."""
    col_map = mapping or CsvColumnMapping()

    # Load materials for tenant if not passed
    materials = known_materials
    if materials is None:
        materials = []
        with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f"SET app.tenant_id = '{tenant_id}';")
            cur.execute("SELECT id, erp_material_no, description, gtin FROM field.material WHERE tenant_id = %s;", (tenant_id,))
            for r in cur.fetchall():
                materials.append({"id": str(r[0]), "code": r[1], "name": r[2] or "", "gtin": r[3]})

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[ImportedRow] = []
    auto_count = 0
    review_count = 0

    for idx, r in enumerate(reader, start=1):
        # Case-insensitive column lookup
        norm_r = {k.strip().lower(): v.strip() for k, v in r.items() if k}

        deliv = norm_r.get(col_map.delivery_document.lower(), f"CSV-{idx:04d}")
        item_no = int(norm_r.get(col_map.item_no.lower(), idx * 10))
        raw_mat = norm_r.get(col_map.material.lower(), "")
        qty = float(norm_r.get(col_map.quantity.lower(), 1.0))
        uom = norm_r.get(col_map.uom.lower(), "EA")
        plant = norm_r.get(col_map.plant.lower(), "1010")
        sloc = norm_r.get(col_map.storage_location.lower(), "101A")

        matched_mat, top_s, rival_s, decision = match_material_ladder(raw_mat, materials)

        if decision == "auto_accepted":
            auto_count += 1
        else:
            review_count += 1

        rows.append(
            ImportedRow(
                row_index=idx,
                delivery_document=deliv,
                item_no=item_no,
                raw_material=raw_mat,
                matched_material_id=matched_mat["id"] if matched_mat else None,
                matched_material_code=matched_mat["code"] if matched_mat else None,
                match_score=top_s,
                rival_score=rival_s,
                status=decision,
                quantity=qty,
                uom=uom,
                plant=plant,
                storage_location=sloc,
            )
        )

    token = f"prev_{uuid.uuid4().hex}"
    _PREVIEWS[token] = (tenant_id, site_id, [r.model_dump() for r in rows])

    return CsvImportPreview(
        preview_token=token,
        total_rows=len(rows),
        auto_accepted_count=auto_count,
        review_count=review_count,
        rows=rows,
    )


def confirm_csv_import(
    preview_token: str,
    approved_overrides: dict[int, str] | None = None,  # row_index -> material_id
    db_url: str = DATABASE_URL,
) -> tuple[int, int]:
    """Confirm preview and create receive tasks and task_lines."""
    if preview_token not in _PREVIEWS:
        raise ValueError("Invalid or expired preview token")

    tenant_id, site_id, rows = _PREVIEWS[preview_token]
    overrides = approved_overrides or {}

    tasks_by_delivery: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        row_idx = r["row_index"]
        status = r["status"]
        if row_idx in overrides:
            r["matched_material_id"] = overrides[row_idx]
            status = "approved"

        if status not in ("auto_accepted", "approved"):
            # Skip unapproved review rows
            continue

        deliv = r["delivery_document"]
        tasks_by_delivery.setdefault(deliv, []).append(r)

    tasks_created = 0
    lines_created = 0

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{tenant_id}';")

        for deliv, items in tasks_by_delivery.items():
            task_id = uuid7_str()
            cur.execute(
                """
                INSERT INTO field.task (
                    id, tenant_id, site_id, type, status, priority, title,
                    ref_doc_no, last_change_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, 'receive', 'pending', 'normal', %s, %s, NOW(), NOW(), NOW())
                ON CONFLICT DO NOTHING;
                """,
                (task_id, tenant_id, site_id, f"Receive {deliv}", deliv),
            )
            tasks_created += 1

            for it in items:
                line_id = uuid7_str()
                mat_id = it.get("matched_material_id")
                qty = it.get("quantity", 0.0)
                uom = it.get("uom", "EA")
                item_no = it.get("item_no", 10)

                cur.execute(
                    """
                    INSERT INTO field.task_line (
                        id, tenant_id, site_id, task_id, line_no, material_id,
                        expected_qty, uom, captured_qty, counted_qty, status,
                        created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 'pending', NOW(), NOW());
                    """,
                    (line_id, tenant_id, site_id, task_id, item_no, mat_id, qty, uom),
                )
                lines_created += 1

    # Invalidate token after confirmation
    _PREVIEWS.pop(preview_token, None)
    return tasks_created, lines_created
