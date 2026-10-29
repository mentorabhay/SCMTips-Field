"""Asset Model Upload and glTF / BOM Validation (Task T4.055 / FR4.051 / FR4.053 / FR4.057 / PR4.08 / TC4.145 / TC4.149).

Handles:
- glTF 2.0 binary (.glb) validation: magic header, max 25 MB, max 300k triangles, zero external URIs.
- BOM CSV validation: required fields, serialised flags, explode vectors.
- Top-level BOM quantity rule: mapped node instances minus sub-part nodes must equal BOM qty (PR4.08).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from field_api.db import get_conn

logger = structlog.get_logger(__name__)

MAX_GLB_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_TRIANGLES = 300_000
GLTF_MAGIC = 0x46546C67  # 'glTF' in little-endian ASCII
JSON_CHUNK_TYPE = 0x4E4F534A  # 'JSON' in little-endian ASCII


class ModelValidationError(Exception):
    """Raised when glTF or BOM validation fails."""

    def __init__(self, code: str, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues or []


def validate_glb_binary(glb_bytes: bytes) -> tuple[str, int, dict[str, Any]]:
    """Validate glTF 2.0 binary header, size, triangle count, and lack of external URIs.

    Returns:
        (sha256_hex, triangle_count, gltf_json)
    """
    file_size = len(glb_bytes)
    if file_size > MAX_GLB_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error_code": "FIELD-MOD-413-SIZE",
                "message": f"Model size {file_size / (1024 * 1024):.1f} MB exceeds 25 MB limit",
            },
        )

    if file_size < 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-MOD-422-INVALID",
                "message": "File is too small to be a valid glTF binary",
            },
        )

    # 1. Header parsing (12 bytes)
    magic, version, length = struct.unpack_from("<III", glb_bytes, 0)
    if magic != GLTF_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-MOD-422-INVALID",
                "message": f"Invalid glTF magic: 0x{magic:08x}",
            },
        )
    if version != 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-MOD-422-INVALID",
                "message": f"Unsupported glTF version: {version}. Expected 2.",
            },
        )

    # 2. Chunk 0 parsing (JSON chunk)
    chunk_len, chunk_type = struct.unpack_from("<II", glb_bytes, 12)
    if chunk_type != JSON_CHUNK_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "FIELD-MOD-422-INVALID", "message": "First chunk must be JSON"},
        )

    json_bytes = glb_bytes[20 : 20 + chunk_len]
    try:
        gltf_json = json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-MOD-422-INVALID",
                "message": f"Malformed glTF JSON chunk: {e}",
            },
        )

    # 3. Check for forbidden external URIs (buffers and images)
    for buf_idx, buf in enumerate(gltf_json.get("buffers", [])):
        uri = buf.get("uri", "")
        if uri and not uri.startswith("data:"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "FIELD-MOD-422-EXTERNAL-URI",
                    "message": f"External URI in buffer {buf_idx} ('{uri}') is forbidden; all assets must be embedded",
                },
            )

    for img_idx, img in enumerate(gltf_json.get("images", [])):
        uri = img.get("uri", "")
        if uri and not uri.startswith("data:"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "FIELD-MOD-422-EXTERNAL-URI",
                    "message": f"External URI in image {img_idx} ('{uri}') is forbidden; all textures must be embedded",
                },
            )

    # 4. Triangle count calculation
    accessors = gltf_json.get("accessors", [])
    triangle_count = 0
    for mesh in gltf_json.get("meshes", []):
        for prim in mesh.get("primitives", []):
            mode = prim.get("mode", 4)  # 4 is TRIANGLES
            if mode != 4:
                continue
            if "indices" in prim:
                idx_acc = prim["indices"]
                if 0 <= idx_acc < len(accessors):
                    triangle_count += accessors[idx_acc].get("count", 0) // 3
            elif "attributes" in prim and "POSITION" in prim["attributes"]:
                pos_acc = prim["attributes"]["POSITION"]
                if 0 <= pos_acc < len(accessors):
                    triangle_count += accessors[pos_acc].get("count", 0) // 3

    if triangle_count > MAX_TRIANGLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "FIELD-MOD-422-TRIANGLES",
                "message": f"Triangle count {triangle_count:,} exceeds limit of {MAX_TRIANGLES:,}",
            },
        )

    sha256_hex = hashlib.sha256(glb_bytes).hexdigest()
    return sha256_hex, triangle_count, gltf_json


def parse_and_validate_bom_csv(
    bom_csv_text: str,
    gltf_node_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse BOM CSV and enforce top-level quantity and hierarchy rules (PR4.08 / TC4.149).

    Expected CSV columns:
        part_no, description, qty, is_serialised, parent_part_no, node_path, node_names,
        explode_vector_x, explode_vector_y, explode_vector_z

    Returns:
        (parsed_items, validation_issues)
    """
    reader = csv.DictReader(io.StringIO(bom_csv_text.strip()))
    items: list[dict[str, Any]] = []
    issues: list[str] = []

    for row_idx, row in enumerate(reader, start=1):
        p_no = row.get("part_no", "").strip()
        if not p_no:
            issues.append(f"Row {row_idx}: Missing part_no")
            continue

        desc = row.get("description", p_no).strip()
        try:
            qty = int(row.get("qty", "1").strip())
        except ValueError:
            qty = 1
            issues.append(f"Row {row_idx} ({p_no}): Invalid quantity")

        is_serial = row.get("is_serialised", "false").strip().lower() in ("true", "1", "yes")
        parent_pno = row.get("parent_part_no", "").strip() or None
        n_path = row.get("node_path", "").strip()

        # Parse node names (pipe or comma separated)
        raw_nodes = row.get("node_names", "").strip()
        if "|" in raw_nodes:
            n_names = [n.strip() for n in raw_nodes.split("|") if n.strip()]
        elif "," in raw_nodes:
            n_names = [n.strip() for n in raw_nodes.split(",") if n.strip()]
        elif raw_nodes:
            n_names = [raw_nodes]
        else:
            n_names = []

        try:
            ev_x = float(row.get("explode_vector_x", "0.0") or 0.0)
            ev_y = float(row.get("explode_vector_y", "0.0") or 0.0)
            ev_z = float(row.get("explode_vector_z", "0.0") or 0.0)
        except ValueError:
            ev_x, ev_y, ev_z = 0.0, 0.0, 0.0

        items.append(
            {
                "part_no": p_no,
                "description": desc,
                "qty": qty,
                "is_serialised": is_serial,
                "parent_part_no": parent_pno,
                "node_path": n_path,
                "node_names": n_names,
                "explode_vector": [ev_x, ev_y, ev_z],
                "explode_vector_x": ev_x,
                "explode_vector_y": ev_y,
                "explode_vector_z": ev_z,
            }
        )

    # Enforce Top-Level BOM Quantity Rule (PR4.08 / FR4.057 / TC4.149)
    # Each top-level BOM item quantity must equal mapped node count,
    # EXCLUDING nodes mapped to its sub-parts.
    sub_parts_by_parent: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        p = it["parent_part_no"]
        if p:
            sub_parts_by_parent.setdefault(p, []).append(it)

    for it in items:
        if it["parent_part_no"] is None:  # Top-level item
            own_nodes = set(it["node_names"])
            # Collect all child nodes
            child_nodes: set[str] = set()
            for child in sub_parts_by_parent.get(it["part_no"], []):
                child_nodes.update(child["node_names"])

            # Net mapped nodes for top-level item
            net_nodes = own_nodes - child_nodes
            # If item has explicit node names list, length must equal qty
            effective_count = len(net_nodes) if own_nodes else it["qty"]
            if effective_count != it["qty"]:
                issues.append(
                    f"Quantity mismatch for '{it['part_no']}': BOM specifies qty {it['qty']}, "
                    f"but model has {effective_count} mapped node instances (excluding sub-parts). [FIELD-MOD-422-QTY-MISMATCH]"
                )

    return items, issues


def create_asset_model_draft(
    tenant_id: str,
    equipment_class: str,
    version: str,
    glb_bytes: bytes,
    bom_csv_text: str,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Validate and upload draft asset model and BOM (API4.12)."""
    # 1. Validate glb
    sha256_hex, triangles, gltf_json = validate_glb_binary(glb_bytes)

    # 2. Extract glTF node names
    gltf_nodes = {n.get("name") for n in gltf_json.get("nodes", []) if n.get("name")}

    # 3. Parse and validate BOM CSV
    bom_items, issues = parse_and_validate_bom_csv(bom_csv_text, gltf_nodes)

    model_id = str(uuid.uuid4())
    storage_path = f"models/{tenant_id}/{equipment_class}/{version}/{sha256_hex[:16]}.glb"
    initial_status = "invalid" if issues else "validated"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Check version uniqueness
            cur.execute(
                """
                SELECT id, status FROM field.asset_model
                WHERE tenant_id = %s AND equipment_class = %s AND version = %s;
                """,
                (tenant_id, equipment_class, version),
            )
            existing = cur.fetchone()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "FIELD-MOD-409-VERSION",
                        "message": f"Version '{version}' already exists for equipment class '{equipment_class}'",
                    },
                )

            # Insert model
            cur.execute(
                """
                INSERT INTO field.asset_model (
                    id, tenant_id, equipment_class, version, status,
                    sha256_hash, file_size_bytes, triangle_count, glb_storage_path
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                );
                """,
                (
                    model_id,
                    tenant_id,
                    equipment_class,
                    version,
                    initial_status,
                    sha256_hex,
                    len(glb_bytes),
                    triangles,
                    storage_path,
                ),
            )

            # Insert BOM items
            for it in bom_items:
                cur.execute(
                    """
                    INSERT INTO field.asset_model_bom (
                        tenant_id, model_id, part_no, description, qty,
                        is_serialised, parent_part_no, node_path, node_names,
                        explode_vector_x, explode_vector_y, explode_vector_z
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    );
                    """,
                    (
                        tenant_id,
                        model_id,
                        it["part_no"],
                        it["description"],
                        it["qty"],
                        it["is_serialised"],
                        it["parent_part_no"],
                        it["node_path"],
                        it["node_names"],
                        it["explode_vector_x"],
                        it["explode_vector_y"],
                        it["explode_vector_z"],
                    ),
                )
            conn.commit()

    return {
        "id": model_id,
        "model_id": model_id,
        "equipment_class": equipment_class,
        "version": version,
        "status": initial_status,
        "sha256": sha256_hex,
        "sha256_hash": sha256_hex,
        "file_size_bytes": len(glb_bytes),
        "triangle_count": triangles,
        "bom_item_count": len(bom_items),
        "issues": issues,
    }
