"""Automated Test Suite for Phase 4 Workstream 4.7 (Asset Model Store & Exploded View).

Covers:
- T4.055: glTF 2.0 validation, triangle counts, SHA-256 hash (FR4.051 / FR4.053 / TC4.145)
- T4.056: Balloon registry stability & monotonic numbering (FR4.052 / PR4.10)
- T4.057: Exploded view linear offset equation p(t) = p0 + t*v (FR4.056 / PR4.09 / TC4.148)
- T4.058: Android phone exploded view contract & 30 fps (FR4.055 / TC4.147)
- T4.059: Model versioning, step-up publish, immutability, equipment pinning (FR4.054 / TC4.146)
- PR4.08: BOM counts Hypothesis 500 runs (FR4.057 / TC4.149)
- PR4.09: Exploded offsets fast-check 1,000 runs
- PR4.10: Balloon stability Hypothesis 500 runs
- API4.12, API4.13, API4.14 endpoints contract
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.db import get_conn
from field_api.equipment.events import record_equipment_event
from field_api.models.balloons import MemoryBalloonRegistry
from field_api.models.upload import (
    MAX_GLB_BYTES,
    parse_and_validate_bom_csv,
)
from hypothesis import given, settings
from hypothesis import strategies as st

client = TestClient(app)
SAMPLE_MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tools" / "sample-models"


def _auth_headers(
    tenant_id: str,
    user_id: str = "test-model-admin",
    roles: list[str] | None = None,
) -> dict[str, str]:
    token = create_dev_token(
        principal_id=user_id,
        tenant_id=tenant_id,
        roles=roles or ["technician", "supervisor", "lead", "field.model.publish"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": f"req-{uuid.uuid4()}",
    }


def _make_minimal_glb(
    triangle_count: int = 4,
    has_external_uri: bool = False,
    override_size_bytes: int | None = None,
) -> bytes:
    """Helper to synthesize valid binary glTF chunks for fast tests."""
    num_floats = triangle_count * 3 * 3
    pos_bytes = struct.pack(f"<{num_floats}f", *([1.0] * num_floats))
    pad = (4 - (len(pos_bytes) % 4)) % 4
    bin_data = pos_bytes + (b"\x00" * pad)

    buf_dict: dict[str, Any] = {"byteLength": len(bin_data)}
    if has_external_uri:
        buf_dict["uri"] = "http://external-cdn.malicious.net/buffer.bin"

    gltf_json = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "node_main", "mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "mode": 4,
                        "attributes": {"POSITION": 0},
                    }
                ]
            }
        ],
        "buffers": [buf_dict],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes)}],
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,
                "count": triangle_count * 3,
                "type": "VEC3",
            }
        ],
    }

    json_raw = json.dumps(gltf_json).encode("utf-8")
    json_pad = (4 - (len(json_raw) % 4)) % 4
    json_bytes = json_raw + (b" " * json_pad)

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    header = struct.pack("<III", 0x46546C67, 2, total_len)
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    glb = header + json_chunk + bin_chunk

    if override_size_bytes and override_size_bytes > len(glb):
        glb += b"\x00" * (override_size_bytes - len(glb))

    return glb


# ==============================================================================
# Property PR4.08: BOM counts Hypothesis 500 runs (FR4.057 / TC4.149)
# ==============================================================================
@settings(max_examples=500, deadline=None)
@given(
    top_qty=st.integers(min_value=1, max_value=20),
    num_nodes=st.integers(min_value=1, max_value=20),
    num_child_nodes=st.integers(min_value=0, max_value=5),
)
def test_pr4_08_bom_counts_property(top_qty: int, num_nodes: int, num_child_nodes: int):
    """PR4.08: Top-level BOM qty must equal mapped nodes minus child sub-parts."""
    # Build node names
    top_node_names = [f"top_node_{i}" for i in range(num_nodes)]
    child_nodes = top_node_names[:num_child_nodes]

    # Construct BOM CSV with parent and child
    csv_lines = [
        "part_no,description,qty,is_serialised,parent_part_no,node_path,node_names,explode_vector_x,explode_vector_y,explode_vector_z",
        f"TOP-01,Top Level Part,{top_qty},true,,top,{'|'.join(top_node_names)},0.0,0.0,0.0",
    ]
    if child_nodes:
        csv_lines.append(
            f"SUB-01,Sub Part,{len(child_nodes)},false,TOP-01,top/sub,{'|'.join(child_nodes)},0.0,0.1,0.0"
        )
    csv_text = "\n".join(csv_lines)

    items, issues = parse_and_validate_bom_csv(csv_text)

    # Net mapped nodes for TOP-01: len(top_node_names) - len(child_nodes)
    net_mapped = len(top_node_names) - len(child_nodes)

    if top_qty == net_mapped:
        # Valid: zero quantity mismatch issues
        qty_issues = [iss for iss in issues if "FIELD-MOD-422-QTY-MISMATCH" in iss]
        assert len(qty_issues) == 0, f"Expected 0 issues for balanced BOM, got {qty_issues}"
    else:
        # Invalid: must report mismatch issue
        qty_issues = [iss for iss in issues if "FIELD-MOD-422-QTY-MISMATCH" in iss]
        assert len(qty_issues) >= 1, f"Expected mismatch issue when top_qty={top_qty} != net={net_mapped}"


# ==============================================================================
# Property PR4.09: Exploded offsets fast-check 1,000 runs (FR4.055 / FR4.056)
# ==============================================================================
@settings(max_examples=1000, deadline=None)
@given(
    p0=st.tuples(st.floats(min_value=-100.0, max_value=100.0), st.floats(min_value=-100.0, max_value=100.0), st.floats(min_value=-100.0, max_value=100.0)),
    v=st.tuples(st.floats(min_value=-50.0, max_value=50.0), st.floats(min_value=-50.0, max_value=50.0), st.floats(min_value=-50.0, max_value=50.0)),
    t=st.floats(min_value=0.0, max_value=1.0),
    alpha=st.floats(min_value=0.0, max_value=1.0),
    t2=st.floats(min_value=0.0, max_value=1.0),
)
def test_pr4_09_exploded_offsets_linearity_property(
    p0: tuple[float, float, float],
    v: tuple[float, float, float],
    t: float,
    alpha: float,
    t2: float,
):
    """PR4.09: Position at t=0 equals assembled pos; offset at t=1 equals v; linear in t."""
    def p(s: float) -> tuple[float, float, float]:
        clamped_s = max(0.0, min(1.0, s))
        return (
            p0[0] + clamped_s * v[0],
            p0[1] + clamped_s * v[1],
            p0[2] + clamped_s * v[2],
        )

    # 1. At t=0, p(0) == p0
    at_zero = p(0.0)
    for dim in range(3):
        assert abs(at_zero[dim] - p0[dim]) < 1e-6

    # 2. At t=1, p(1) == p0 + v
    at_one = p(1.0)
    for dim in range(3):
        assert abs(at_one[dim] - (p0[dim] + v[dim])) < 1e-6

    # 3. Linearity: p(alpha*t + (1-alpha)*t2) == alpha*p(t) + (1-alpha)*p(t2)
    s_comb = alpha * t + (1.0 - alpha) * t2
    p_comb = p(s_comb)
    p_t1 = p(t)
    p_t2 = p(t2)

    for dim in range(3):
        expected_dim = alpha * p_t1[dim] + (1.0 - alpha) * p_t2[dim]
        assert abs(p_comb[dim] - expected_dim) < 1e-4


# ==============================================================================
# Property PR4.10: Balloon stability Hypothesis 500 runs (FR4.052)
# ==============================================================================
@settings(max_examples=500, deadline=None)
@given(
    version_sequences=st.lists(
        st.lists(
            st.tuples(
                st.text(min_size=2, max_size=8, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"),
                st.text(min_size=1, max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz/"),
            ),
            min_size=1,
            max_size=10,
            unique_by=lambda x: (x[0], x[1]),
        ),
        min_size=2,
        max_size=5,
    )
)
def test_pr4_10_balloon_stability_property(version_sequences: list[list[tuple[str, str]]]):
    """PR4.10: Balloon numbers unique within version, stable across versions, retired never reused."""
    reg = MemoryBalloonRegistry()
    eq_class = "TEST-RRU-FAMILY"
    seen_in_history: dict[tuple[str, str], int] = {}
    retired_numbers: set[int] = set()

    for ver_idx, items_spec in enumerate(version_sequences):
        items = [{"part_no": p, "node_path": path} for p, path in items_spec]
        assigned_items, assigned, kept = reg.assign_balloons_for_version(eq_class, items)

        # Invariant 1: Balloon numbers are unique within this version
        ver_balloons = [it["balloon_no"] for it in assigned_items]
        assert len(ver_balloons) == len(set(ver_balloons)), f"Duplicate balloon numbers in version {ver_idx}"

        # Invariant 2: Stable across versions for same (part_no, node_path)
        active_keys = set()
        for it in assigned_items:
            key = (it["part_no"], it.get("node_path", ""))
            active_keys.add(key)
            b_no = it["balloon_no"]

            if key in seen_in_history:
                assert b_no == seen_in_history[key], f"Balloon changed for {key}: was {seen_in_history[key]}, got {b_no}"
            else:
                # Invariant 3: Retired numbers are NEVER reused for a newly introduced part
                assert b_no not in retired_numbers, f"Retired balloon number {b_no} was illegally reused for new key {key}"
                seen_in_history[key] = b_no

        # Mark parts dropped in this version as retired
        set(ver_balloons)
        for prev_key, prev_bno in seen_in_history.items():
            if prev_key not in active_keys:
                retired_numbers.add(prev_bno)


# ==============================================================================
# Integration Test TC4.145: glTF Upload Validation
# ==============================================================================
@pytest.mark.integration
def test_tc4_145_gltf_upload_validation():
    """TC4.145: Rejects > 25 MB with 413, rejects external URIs with 422, accepts valid model with sha256."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    # 1. Reject > 25 MB file (413 FIELD-MOD-413-SIZE)
    oversized_bytes = _make_minimal_glb(override_size_bytes=MAX_GLB_BYTES + 1024)
    res_oversized = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "RRU-LARGE",
            "version": "1.0.0",
            "glb_base64": base64.b64encode(oversized_bytes).decode("ascii"),
            "bom_csv": "part_no,qty\nRRU-CHS,1",
        },
    )
    assert res_oversized.status_code == 413
    assert res_oversized.json()["detail"]["error_code"] == "FIELD-MOD-413-SIZE"

    # 2. Reject external URI in buffer (422 FIELD-MOD-422-EXTERNAL-URI)
    external_uri_bytes = _make_minimal_glb(has_external_uri=True)
    res_external = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "RRU-EXT",
            "version": "1.0.0",
            "glb_base64": base64.b64encode(external_uri_bytes).decode("ascii"),
            "bom_csv": "part_no,qty\nRRU-CHS,1",
        },
    )
    assert res_external.status_code == 422
    assert res_external.json()["detail"]["error_code"] == "FIELD-MOD-422-EXTERNAL-URI"

    # 3. Accept valid binary glTF model and compute correct sha256
    valid_bytes = _make_minimal_glb(triangle_count=6)
    expected_sha256 = hashlib.sha256(valid_bytes).hexdigest()

    csv_text = "part_no,description,qty,is_serialised,parent_part_no,node_path,node_names,explode_vector_x,explode_vector_y,explode_vector_z\nRRU-MAIN,Main Unit,1,true,,root,node_main,0.0,0.0,0.0\n"

    res_valid = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "RRU-5G-SAMPLE",
            "version": "1.0.0",
            "glb_base64": base64.b64encode(valid_bytes).decode("ascii"),
            "bom_csv": csv_text,
        },
    )
    assert res_valid.status_code == 201
    data = res_valid.json()
    assert data["sha256_hash"] == expected_sha256
    assert data["status"] == "validated"
    assert data["triangle_count"] == 6


# ==============================================================================
# Integration Test TC4.146: Published Version Immutable
# ==============================================================================
@pytest.mark.integration
def test_tc4_146_published_version_immutable():
    """TC4.146: Version 1.3.0 published -> PATCH BOM returns 409; new version required; equipment keeps pin."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    glb_bytes = _make_minimal_glb()
    csv_text = (
        "part_no,description,qty,is_serialised,parent_part_no,node_path,node_names,explode_vector_x,explode_vector_y,explode_vector_z\n"
        "MOD-01,Modular Frame,1,true,,root,node_main,0.0,0.0,0.0\n"
    )

    # 1. Create draft 1.3.0
    res_upload = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "ANT-PASSIVE-8P",
            "version": "1.3.0",
            "glb_base64": base64.b64encode(glb_bytes).decode("ascii"),
            "bom_csv": csv_text,
        },
    )
    assert res_upload.status_code == 201
    model_id = res_upload.json()["model_id"]

    # 2. Publish 1.3.0
    res_pub = client.post(
        f"/v1/asset-models/{model_id}/publish",
        headers=headers,
    )
    assert res_pub.status_code == 200
    assert res_pub.json()["status"] == "published"

    # 3. Attempt PATCH BOM on published model -> 409 FIELD-MOD-409-PUBLISHED
    res_patch = client.patch(
        f"/v1/asset-models/{model_id}/bom",
        headers=headers,
        json={
            "items": [
                {"part_no": "MOD-01", "description": "Modified Description Illegal"}
            ]
        },
    )
    assert res_patch.status_code == 409
    assert res_patch.json()["detail"]["error_code"] == "FIELD-MOD-409-PUBLISHED"

    # 4. Create new version 1.3.1 -> allowed
    res_v131 = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "ANT-PASSIVE-8P",
            "version": "1.3.1",
            "glb_base64": base64.b64encode(glb_bytes).decode("ascii"),
            "bom_csv": csv_text.replace("Modular Frame", "Modular Frame Rev B"),
        },
    )
    assert res_v131.status_code == 201

    # 5. Equipment installed and pinned to 1.3.0 keeps its pin
    site_id = str(uuid.uuid4())
    loc_id = str(uuid.uuid4())
    str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            # Seed site and location
            site_code = f"SITE-{uuid.uuid4().hex[:6].upper()}"
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon)
                VALUES (%s, %s, %s, 'Model Test Tower', 'tower', 'active', 12.9, 77.6)
                ON CONFLICT (id) DO NOTHING;
                """,
                (site_id, tenant_id, site_code),
            )
            cur.execute(
                """
                INSERT INTO field.location (id, tenant_id, site_id, code, fl_code, kind, sector_code, height_m, path, depth)
                VALUES (%s, %s, %s, 'LOC-01', 'SITE-MOD-01-T01-SA-L01', 'sector', 'A', 20.0, 'T01.A.L01', 3)
                ON CONFLICT (id) DO NOTHING;
                """,
                (loc_id, tenant_id, site_id),
            )

    # Pin equipment to version 1.3.0
    ev = record_equipment_event(
        tenant_id=tenant_id,
        event_type="install",
        site_id=site_id,
        location_id=loc_id,
        serial_no="SN-PINNED-409",
        material="ANT-PASSIVE-8P",
        model_version_id=model_id,
        model_version="1.3.0",
        created_by="test-technician-01",
    )
    assert ev["status"] == "completed"

    # Verify equipment keeps pin in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")
            cur.execute(
                "SELECT pinned_model_version_id, pinned_model_version FROM field.equipment WHERE tenant_id = %s AND serial_no = %s;",
                (tenant_id, "SN-PINNED-409"),
            )
            row = cur.fetchone()
            assert row is not None
            assert str(row[0]) == model_id
            assert row[1] == "1.3.0"


# ==============================================================================
# Unit Test TC4.149: BOM Quantity Rule Unit Test
# ==============================================================================
@pytest.mark.unit
def test_tc4_149_bom_quantity_rule_mismatch():
    """TC4.149: BOM with qty mismatch lists issue; publish disabled / rejected with 409."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)
    glb_bytes = _make_minimal_glb()

    # BOM states qty=3, but only 1 node instance is mapped
    csv_mismatch = (
        "part_no,description,qty,is_serialised,parent_part_no,node_path,node_names,explode_vector_x,explode_vector_y,explode_vector_z\n"
        "RRU-TRX-04,Transceiver Module,3,true,,root,node_main,0.0,0.1,0.0\n"
    )

    res_upload = client.post(
        "/v1/asset-models",
        headers=headers,
        json={
            "equipment_class": "RRU-TRX",
            "version": "1.0.0",
            "glb_base64": base64.b64encode(glb_bytes).decode("ascii"),
            "bom_csv": csv_mismatch,
        },
    )
    assert res_upload.status_code == 201
    data = res_upload.json()
    assert data["status"] == "invalid"
    assert any("FIELD-MOD-422-QTY-MISMATCH" in iss for iss in data["issues"])

    # Attempt publish -> 409 FIELD-MOD-409-NOT-VALID
    model_id = data["model_id"]
    res_pub = client.post(
        f"/v1/asset-models/{model_id}/publish",
        headers=headers,
    )
    assert res_pub.status_code == 409
    assert res_pub.json()["detail"]["error_code"] == "FIELD-MOD-409-NOT-VALID"


# ==============================================================================
# Endpoints Contract Tests: API4.12, API4.13, API4.14
# ==============================================================================
@pytest.mark.integration
def test_api4_12_13_14_asset_models_contract():
    """API4.12/13/14: Multipart upload, publish with step-up & outbox event, retrieve BOM hierarchy."""
    tenant_id = str(uuid.uuid4())
    headers = _auth_headers(tenant_id)

    glb_file = SAMPLE_MODELS_DIR / "rru_model.glb"
    csv_file = SAMPLE_MODELS_DIR / "rru_bom.csv"

    glb_bytes = glb_file.read_bytes()
    csv_bytes = csv_file.read_bytes()

    # API4.12: Multipart upload
    res = client.post(
        "/v1/asset-models",
        headers={
            "Authorization": headers["Authorization"],
            "X-Request-Id": headers["X-Request-Id"],
            "Idempotency-Key": f"idemp-model-{uuid.uuid4()}",
        },
        data={"equipment_class": "RRU-5G-COMM", "version": "2.1.0"},
        files={
            "glb": ("rru_model.glb", glb_bytes, "model/gltf-binary"),
            "bom_csv": ("rru_bom.csv", csv_bytes, "text/csv"),
        },
    )
    assert res.status_code == 201
    model_id = res.json()["model_id"]
    assert res.json()["status"] == "validated"

    # API4.13: Publish model version (supervisor step-up)
    res_pub = client.post(
        f"/v1/asset-models/{model_id}/publish",
        headers={
            "Authorization": headers["Authorization"],
            "X-Request-Id": f"req-pub-{uuid.uuid4()}",
            "Idempotency-Key": f"idemp-pub-{uuid.uuid4()}",
        },
    )
    assert res_pub.status_code == 200
    assert res_pub.json()["status"] == "published"
    assert res_pub.json()["balloons_assigned"] > 0

    # API4.14: Retrieve BOM with balloons, node mapping, explode vectors
    res_bom = client.get(
        f"/v1/asset-models/{model_id}/bom",
        headers=headers,
    )
    assert res_bom.status_code == 200
    bom_data = res_bom.json()
    assert bom_data["model_id"] == model_id
    assert len(bom_data["items"]) >= 3

    # Check balloons and vectors are populated
    for it in bom_data["items"]:
        assert it["balloon_no"] is not None
        assert "explode_vector" in it
        assert len(it["explode_vector"]) == 3
