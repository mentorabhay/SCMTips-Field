"""Assistant session records and the supervisor reads (M3 contract §4), on Postgres with forced RLS."""

from __future__ import annotations

import csv
import io
import os
import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token

pytestmark = pytest.mark.unit
api = TestClient(app)
ITEM_KEYS = {"id", "site_id", "principal_id", "mode", "started_at", "ended_at", "turns", "documents", "cost_usd"}


@pytest.fixture(autouse=True)
def ai_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")


def _post(s: dict[str, Any], body: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    r = api.post("/v1/assistant/turns", json={"site_id": s["site"], **body},
                 headers={"Authorization": f"Bearer {token or s['op']}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _get(path: str, token: str, **params: Any) -> Any:
    return api.get(path, params=params, headers={"Authorization": f"Bearer {token}"})


def _session(s: dict[str, Any]) -> str:
    sid = _post(s, {"event": "session_start"})["session_id"]
    _post(s, {"event": "utterance", "text": "start receipt", "session_id": sid})
    _post(s, {"event": "utterance", "text": "=HYPERLINK(\"x\")", "session_id": sid,
              "client_state": {"task_id": s["receive"]}})
    return str(sid)


def test_list_detail_and_documents(site: dict[str, Any], h: SimpleNamespace) -> None:
    sid = _session(site)
    h.admin_sql(site["tenant"], "INSERT INTO field.erp_document (tenant_id, site_id, doc_type, doc_number, fiscal_year,"
                                " movement_type, payload, status) VALUES (%s, %s, 'GR', '5000000123', '2026', '101',"
                                " jsonb_build_object('task_id', %s::text), 'posted')",
                (site["tenant"], site["site"], site["receive"]))
    h.admin_sql(site["tenant"], "INSERT INTO field.erp_document (tenant_id, site_id, doc_type, doc_number, fiscal_year,"
                                " movement_type, payload, status) VALUES (%s, %s, 'GR', '5000000999', '2026', '101',"
                                " jsonb_build_object('task_id', %s::text), 'posted')",
                (site["tenant"], site["site"], str(uuid.uuid4())))  # another job: not this session's
    r = _get("/v1/assistant/sessions", site["sup"], site_id=site["site"])
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and set(items[0]) == ITEM_KEYS
    it = items[0]
    assert (it["id"], it["site_id"], it["principal_id"], it["mode"], it["turns"], it["documents"]) == (
        sid, site["site"], "op-1", "production", 3, ["5000000123"])
    assert it["ended_at"] is None and it["cost_usd"] == 0.0
    d = _get(f"/v1/assistant/sessions/{sid}", site["sup"]).json()
    assert d["documents"] == ["5000000123"] and [t["event"] for t in d["turns"]] == [
        "session_start", "utterance", "utterance"]
    t = d["turns"][1]
    assert set(t) >= {"id", "at", "event", "heard", "said", "actions", "tool_calls", "code", "photo_ref", "ai",
                      "cost_usd", "latency_ms"}
    assert t["heard"] == "start receipt" and t["actions"] == [{"type": "open_task", "task_id": site["receive"]}]
    assert t["task_id"] == site["receive"] and t["ai"] == "rules"
    summary = _post(site, {"event": "utterance", "text": "summary", "session_id": sid})
    assert "1 SAP document" in summary["say"]


def test_csv_export_escapes_formulas(site: dict[str, Any]) -> None:
    sid = _session(site)
    r = _get(f"/v1/assistant/sessions/{sid}/export.csv", site["sup"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert f"assistant-session-{sid}.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 3 and rows[0]["event"] == "session_start" and rows[0]["session_id"] == sid
    assert rows[2]["heard"].startswith("'=HYPERLINK")


def test_reads_need_review_permission_and_respect_tenancy(site: dict[str, Any]) -> None:
    sid = _session(site)
    for path in ("/v1/assistant/sessions", f"/v1/assistant/sessions/{sid}", f"/v1/assistant/sessions/{sid}/export.csv"):
        assert _get(path, site["op"]).status_code == 403
        assert _get(path, site["viewer"]).status_code == 403
        assert api.get(path).status_code == 401
    other = create_dev_token("sup-x", str(uuid.uuid4()), ["field.supervisor"], site_ids=["*"])
    assert _get(f"/v1/assistant/sessions/{sid}", other).status_code == 404
    assert _get("/v1/assistant/sessions", other).json()["items"] == []
    scoped = create_dev_token("sup-y", site["tenant"], ["field.supervisor"], site_ids=[str(uuid.uuid4())])
    assert _get(f"/v1/assistant/sessions/{sid}", scoped).status_code == 404  # site_scope RLS
    assert _get("/v1/assistant/sessions", scoped, site_id=site["site"]).status_code == 403
    assert _get("/v1/assistant/sessions/not-a-uuid", site["sup"]).status_code == 422


def test_pagination_and_session_end(site: dict[str, Any]) -> None:
    sids = [_post(site, {"event": "session_start"})["session_id"] for _ in range(3)]
    _post(site, {"event": "session_end", "session_id": sids[0]})
    page = _get("/v1/assistant/sessions", site["sup"], site_id=site["site"], limit=2).json()
    assert [i["id"] for i in page["items"]] == [sids[2], sids[1]] and page["next_cursor"]
    rest = _get("/v1/assistant/sessions", site["sup"], site_id=site["site"], limit=2, cursor=page["next_cursor"]).json()
    assert [i["id"] for i in rest["items"]] == [sids[0]] and rest["next_cursor"] is None
    assert rest["items"][0]["ended_at"] is not None
    bad = _get("/v1/assistant/sessions", site["sup"], cursor="forged.cursor")
    assert bad.status_code == 422


def test_sandbox_session_mode_is_recorded(site: dict[str, Any], h: SimpleNamespace) -> None:
    h.set_sandbox(site)
    sid = _post(site, {"event": "session_start"})["session_id"]
    assert _get(f"/v1/assistant/sessions/{sid}", site["sup"]).json()["mode"] == "sandbox"


def test_tables_have_forced_rls(site: dict[str, Any], h: SimpleNamespace) -> None:
    rows = h.admin_sql(site["tenant"], "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                                       "(SELECT array_agg(policyname ORDER BY policyname) FROM pg_policies p "
                                       " WHERE p.schemaname = 'field' AND p.tablename = c.relname)"
                                       " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                                       " WHERE n.nspname = 'field' AND c.relkind = 'r' AND c.relname LIKE 'assistant_%%' ORDER BY 1")
    assert rows == [("assistant_session", True, True, ["site_scope", "tenant_isolation"]),
                    ("assistant_turn", True, True, ["site_scope", "tenant_isolation"])]
    app_url = os.environ["FIELD_DATABASE_URL"]
    with psycopg.connect(app_url) as c, c.cursor() as cur:  # app role, no tenant set: sees nothing
        cur.execute("SELECT count(*) FROM field.assistant_turn")
        assert cur.fetchone() == (0,)
