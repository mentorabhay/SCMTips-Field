"""The look port (M5-X01): the section 2 shape from either storage form of stream V's ``field.vision_look``, and
no error when V's table is not on this branch yet."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

from field_api.auth.jwt import Principal
from field_api.claims.looks import LOOK_KEYS, db_get_look, look_from_row


def test_a_body_column_gives_the_section_2_shape(h: SimpleNamespace) -> None:
    lid, cap, task = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    body = h.make_look(lid, cap, task)
    out = look_from_row({"id": uuid.UUID(lid), "body": json.dumps(body), "task_id": uuid.UUID(task)})
    assert out["look_id"] == lid and out["task_id"] == task and out["image"]["capture_id"] == cap
    assert {k: out[k] for k in LOOK_KEYS} == {k: body[k] for k in LOOK_KEYS}


def test_one_column_per_key_wins_over_the_body_and_fills_the_capture() -> None:
    lid, cap = uuid.uuid4(), uuid.uuid4()
    row: dict[str, Any] = {"id": lid, "response": {"counts": {"seen": 1}, "say": "old"}, "capture_id": cap,
                           "counts": {"expected": 5, "seen": 4}, "say": "Four of five.", "image": {"width": 10},
                           "instances": None}
    out = look_from_row(row)
    assert out["counts"] == {"expected": 5, "seen": 4} and out["say"] == "Four of five."
    assert out["image"] == {"width": 10, "capture_id": str(cap)} and out["instances"] == []
    assert out["models"] == [] and out["reasons"] == [] and out["pack"] is None


def test_an_empty_row_is_an_empty_look() -> None:
    out = look_from_row({"id": uuid.uuid4()})
    assert out["instances"] == [] and out["counts"] == {} and out["image"] == {}


def test_the_database_port_answers_none_without_raising(env: dict[str, Any]) -> None:
    p = Principal(id="op-x", tenant_id=env["tenant"], roles=["field.operator"], permissions=[], site_ids=["*"])
    assert db_get_look(p, str(uuid.uuid4())) is None  # V's table absent (this branch) or no such row
    assert db_get_look(p, "not-a-uuid") is None
