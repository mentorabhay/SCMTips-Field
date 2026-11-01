"""The look port (M5-X01): claims and the evidence pack read stream V's look through ``field_api.vision.service``
(``get_look`` / ``look_body`` over ``LOOK_COLS``, one column per top-level key of ``field.vision_look``), so a claim
sees exactly what ``GET /v1/vision/looks/{id}`` answers. The unit tests check the normalisation; the integration
tests run the database port, the claims API and the evidence pack on a real ``field.vision_look`` row."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from field_api.app import app
from field_api.assistant.model import ModelRouter, get_router
from field_api.auth.jwt import Principal
from field_api.claims.looks import LOOK_KEYS, db_get_look, look_from_body
from field_api.vision.service import look_body


def _v_row(look: dict[str, Any], *, capture_in_image: bool = True) -> tuple[Any, ...]:
    """A ``field.vision_look`` row in V's LOOK_COLS order, built from a section 2 look (label raw split out)."""
    raw = {str(i["n"]): i["label"]["raw"] for i in look["instances"]}
    inst = [{**i, "label": {k: v for k, v in i["label"].items() if k != "raw"}} for i in look["instances"]]
    image = dict(look["image"]) if capture_in_image else {k: v for k, v in look["image"].items() if k != "capture_id"}
    return (uuid.UUID(look["look_id"]), uuid.UUID(look["task_id"]), None, uuid.UUID(look["image"]["capture_id"]),
            "grocery", "pack", look["source"], image, inst, raw, look["counts"], look["pack"], look["expiry"],
            look["proposal"], look["say"], look["models"], look["reasons"], None, datetime.now(UTC), 0, 0,
            look.get("final", True), look.get("say_next"))


def _insert_look(h: SimpleNamespace, env: dict[str, Any], look: dict[str, Any]) -> str:
    """Store a look as stream V's service does: one column per top-level key, label raw text in raw_labels."""
    raw = {str(i["n"]): i["label"]["raw"] for i in look["instances"]}
    inst = [{**i, "label": {k: v for k, v in i["label"].items() if k != "raw"}} for i in look["instances"]]
    h.admin_sql(env["tenant"], "INSERT INTO field.vision_look (id, tenant_id, site_id, task_id, line_id, capture_id,"
                               " \"case\", object, source, idempotency_key, principal_id, image, instances, raw_labels,"
                               " counts, pack, expiry, proposal, say, models, reasons) VALUES (%s, %s, %s, %s, %s, %s,"
                               " 'grocery', 'pack', %s, %s, 'op-x', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (look["look_id"], env["tenant"], env["site"], env["task"], env["line"], env["capture"], look["source"],
                 f"look-{uuid.uuid4()}", json.dumps(look["image"]), json.dumps(inst), json.dumps(raw),
                 json.dumps(look["counts"]), json.dumps(look["pack"]), json.dumps(look["expiry"]),
                 json.dumps(look["proposal"]), look["say"], json.dumps(look["models"]), json.dumps(look["reasons"])))
    return str(look["look_id"])


def test_v_look_body_gives_the_section_2_shape(h: SimpleNamespace) -> None:
    lid, cap, task = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    look = h.make_look(lid, cap, task)
    out = look_from_body(look_body(_v_row(look)))
    assert out["look_id"] == lid and out["task_id"] == task and out["line_id"] is None
    assert out["image"]["capture_id"] == cap
    assert {k: out[k] for k in LOOK_KEYS} == {k: look[k] for k in LOOK_KEYS}


def test_a_missing_image_capture_is_filled_from_the_row_capture(h: SimpleNamespace) -> None:
    lid, cap, task = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    out = look_from_body(look_body(_v_row(h.make_look(lid, cap, task), capture_in_image=False)))
    assert out["image"] == {"width": 1920, "height": 1440, "capture_id": cap}


def test_an_empty_body_is_an_empty_look() -> None:
    out = look_from_body({"look_id": str(uuid.uuid4())})
    assert out["instances"] == [] and out["counts"] == {} and out["image"] == {} and out["pack"] is None
    assert out["models"] == [] and out["reasons"] == [] and out["task_id"] is None


def test_the_database_port_answers_none_without_raising(env: dict[str, Any]) -> None:
    p = Principal(id="op-x", tenant_id=env["tenant"], roles=["field.operator"], permissions=[], site_ids=["*"])
    assert db_get_look(p, str(uuid.uuid4())) is None  # no such row
    assert db_get_look(p, "not-a-uuid") is None


def test_the_database_port_reads_a_real_vision_look_under_rls(env: dict[str, Any], h: SimpleNamespace) -> None:
    look = h.make_look(str(uuid.uuid4()), env["capture"], env["task"])
    lid = _insert_look(h, env, look)
    p = Principal(id="op-x", tenant_id=env["tenant"], roles=["field.operator"], permissions=[], site_ids=[env["site"]])
    out = db_get_look(p, lid)
    assert out is not None and out["look_id"] == lid and out["task_id"] == env["task"] and out["line_id"] == env["line"]
    assert out["image"]["capture_id"] == env["capture"] and out["counts"] == look["counts"]
    assert out["instances"][6]["label"]["pieces_per_unit"] == 10
    other_site = Principal(id="op-y", tenant_id=env["tenant"], roles=["field.operator"], permissions=[],
                           site_ids=[str(uuid.uuid4())])
    other_tenant = Principal(id="sup-o", tenant_id=env["other"]["tenant"], roles=["field.supervisor"],
                             permissions=[], site_ids=["*"])
    assert db_get_look(other_site, lid) is None and db_get_look(other_tenant, lid) is None


def test_a_claim_and_the_evidence_pack_on_a_real_vision_look(env: dict[str, Any], h: SimpleNamespace, ai_off: None,
                                                             model_router: ModelRouter) -> None:
    """No look double: POST /v1/claims and GET /v1/evidence/documents read the real field.vision_look row."""
    look = h.make_look(str(uuid.uuid4()), env["capture"], env["task"])
    lid = _insert_look(h, env, look)
    app.dependency_overrides[get_router] = lambda: model_router
    try:
        client = TestClient(app)
        r = client.post("/v1/claims", json={"look_id": lid}, headers=h.auth(env["op"]))
        assert r.status_code == 201, r.text
        c = r.json()
        assert c["look_id"] == lid and c["task_id"] == env["task"] and c["source"] == "template"
        assert c["lines"] == [{"reason": "damaged", "units": 2, "pieces": 24},
                              {"reason": "pack_size", "units": 2, "pieces": 4}]
        env = {**env, "look": lid}
        doc = h.post_document(env)
        r = client.get(f"/v1/evidence/documents/{doc['doc_number']}", params={"year": doc["year"]},
                       headers=h.auth(env["sup"]))
        assert r.status_code == 200, r.text
        pack = r.json()
        assert pack["look"]["look_id"] == lid and pack["look"]["capture_id"] == env["capture"]
        assert pack["look"]["counts"] == look["counts"] and pack["claim"]["claim_id"] == c["claim_id"]
        assert "BRANDX" not in r.text  # raw label text stays in V's raw_labels, never in the pack
    finally:
        app.dependency_overrides.pop(get_router, None)
