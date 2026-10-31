"""Assistant session records (M3 contract §4): field.assistant_session and field.assistant_turn, under RLS.

Heard text, said text and photos are kept 30 days; the worker's retention job clears them
(field.worker_purge_assistant_content). Documents of a session are the SAP documents (field.erp_document with a
number) of the jobs its turns were about, created while the session was open.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.errors import FieldError
from field_api.http.pagination import decode_cursor, encode_cursor

CSV_COLUMNS = ("session_id", "turn_id", "at", "event", "heard", "said", "code", "task_id", "ai", "cost_usd",
               "latency_ms", "actions", "tool_calls", "photo_ref")

_DOCS_SQL = """
    (SELECT COALESCE(array_agg(DISTINCT d.doc_number ORDER BY d.doc_number), '{}')
       FROM field.erp_document d
      WHERE d.doc_number IS NOT NULL
        AND d.created_at >= s.started_at AND d.created_at <= COALESCE(s.ended_at, NOW())
        AND d.payload->>'task_id' IN (SELECT t.task_id::text FROM field.assistant_turn t
                                       WHERE t.session_id = s.id AND t.task_id IS NOT NULL))
"""


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def create_session(principal: Principal, site_id: str, mode: str) -> str:
    with principal_tx(principal) as cur:
        cur.execute(
            "INSERT INTO field.assistant_session (tenant_id, site_id, principal_id, device_id, mode)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
            (principal.tenant_id, site_id, principal.id, principal.device_id, mode),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def load_session(principal: Principal, session_id: str) -> dict[str, Any] | None:
    with principal_tx(principal) as cur:
        cur.execute(
            "SELECT id::text, site_id::text, principal_id, mode, started_at, ended_at, dialog"
            " FROM field.assistant_session WHERE id::text = %s",
            (session_id,),
        )
        r = cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "site_id": r[1], "principal_id": r[2], "mode": r[3], "started_at": r[4], "ended_at": r[5],
            "dialog": r[6]}


def recent_turns(principal: Principal, session_id: str, n: int = 6) -> list[dict[str, Any]]:
    """The last ``n`` turns, oldest first (conversation history for the model, "repeat" for rules)."""
    with principal_tx(principal) as cur:
        cur.execute(
            "SELECT event, heard, said, code FROM field.assistant_turn WHERE session_id::text = %s"
            " ORDER BY at DESC, id DESC LIMIT %s",
            (session_id, n),
        )
        rows = cur.fetchall()
    return [{"event": r[0], "heard": r[1], "said": r[2], "code": r[3]} for r in reversed(rows)]


def record_turn(principal: Principal, session: dict[str, Any], *, event: str, heard: str | None, said: str,
                actions: list[dict[str, Any]], tool_calls: list[dict[str, Any]], code: str | None,
                photo_ref: str | None, ai: str, cost_usd: Decimal, latency_ms: int, task_id: str | None,
                dialog: dict[str, Any] | None, end: bool) -> str:
    with principal_tx(principal) as cur:
        cur.execute(
            """
            INSERT INTO field.assistant_turn (tenant_id, site_id, session_id, event, heard, said, actions, tool_calls,
                   code, photo_ref, ai, cost_usd, latency_ms, task_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid) RETURNING id::text
            """,
            (principal.tenant_id, session["site_id"], session["id"], event, heard, said, Jsonb(actions),
             Jsonb(tool_calls), code, photo_ref, ai, cost_usd, max(0, latency_ms), task_id),
        )
        row = cur.fetchone()
        cur.execute(
            "UPDATE field.assistant_session SET last_turn_at = NOW(), dialog = %s,"
            " ended_at = CASE WHEN %s THEN NOW() ELSE ended_at END WHERE id::text = %s",
            (Jsonb(dialog) if dialog is not None else None, end, session["id"]),
        )
    assert row is not None
    return str(row[0])


def session_summary(principal: Principal, session_id: str) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT s.started_at,
                   (SELECT count(*) FROM field.assistant_turn t WHERE t.session_id = s.id),
                   (SELECT COALESCE(sum(t.cost_usd), 0) FROM field.assistant_turn t WHERE t.session_id = s.id),
                   (SELECT COALESCE(array_agg(DISTINCT t.task_id::text), '{{}}') FROM field.assistant_turn t
                     WHERE t.session_id = s.id AND t.task_id IS NOT NULL),
                   {_DOCS_SQL}
              FROM field.assistant_session s WHERE s.id::text = %s
            """,  # noqa: S608 - fixed SQL fragment, values are parameters
            (session_id,),
        )
        r = cur.fetchone()
        if not r:
            return {"turns": 0, "jobs": 0, "jobs_done": 0, "documents": [], "cost_usd": 0.0}
        tasks = list(r[3] or [])
        done = 0
        if tasks:
            cur.execute("SELECT count(*) FROM field.task WHERE id::text = ANY(%s) AND status = 'completed'", (tasks,))
            row = cur.fetchone()
            done = int(row[0]) if row else 0
    return {"started_at": _iso(r[0]), "turns": int(r[1]), "jobs": len(tasks), "jobs_done": done,
            "documents": list(r[4] or []), "cost_usd": float(r[2])}


def list_sessions(principal: Principal, site_id: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    """Newest first, keyset on (started_at, id); ``cursor`` is the signed next_cursor of the previous page."""
    before_at: str | None = None
    before_id: str | None = None
    if cursor:
        raw = decode_cursor(cursor)
        if not raw or "|" not in raw:
            raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Invalid cursor")
        before_at, before_id = raw.split("|", 1)
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT s.id::text, s.site_id::text, s.principal_id, s.mode, s.started_at, s.ended_at,
                   (SELECT count(*) FROM field.assistant_turn t WHERE t.session_id = s.id),
                   {_DOCS_SQL},
                   (SELECT COALESCE(sum(t.cost_usd), 0) FROM field.assistant_turn t WHERE t.session_id = s.id)
              FROM field.assistant_session s
             WHERE (%s::uuid IS NULL OR s.site_id = %s::uuid)
               AND (%s::timestamptz IS NULL OR (s.started_at, s.id) < (%s::timestamptz, %s::uuid))
             ORDER BY s.started_at DESC, s.id DESC LIMIT %s
            """,  # noqa: S608 - fixed SQL fragment, values are parameters
            (site_id, site_id, before_at, before_at, before_id, limit + 1),
        )
        rows = cur.fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{"id": r[0], "site_id": r[1], "principal_id": r[2], "mode": r[3], "started_at": _iso(r[4]),
              "ended_at": _iso(r[5]), "turns": int(r[6]), "documents": list(r[7] or []), "cost_usd": float(r[8])}
             for r in rows]
    nxt = encode_cursor(f"{rows[-1][4].isoformat()}|{rows[-1][0]}") if more and rows else None
    return {"items": items, "next_cursor": nxt}


def session_detail(principal: Principal, session_id: str) -> dict[str, Any] | None:
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            SELECT s.id::text, s.site_id::text, s.principal_id, s.device_id::text, s.mode, s.started_at, s.ended_at,
                   {_DOCS_SQL}
              FROM field.assistant_session s WHERE s.id::text = %s
            """,  # noqa: S608 - fixed SQL fragment, values are parameters
            (session_id,),
        )
        s = cur.fetchone()
        if not s:
            return None
        cur.execute(
            "SELECT id::text, at, event, heard, said, actions, tool_calls, code, photo_ref, ai, cost_usd, latency_ms,"
            " task_id::text, purged_at FROM field.assistant_turn WHERE session_id::text = %s ORDER BY at, id",
            (session_id,),
        )
        turns = [{"id": t[0], "at": _iso(t[1]), "event": t[2], "heard": t[3], "said": t[4], "actions": t[5],
                  "tool_calls": t[6], "code": t[7], "photo_ref": t[8], "ai": t[9], "cost_usd": float(t[10]),
                  "latency_ms": t[11], "task_id": t[12], "purged_at": _iso(t[13])} for t in cur.fetchall()]
    return {"id": s[0], "site_id": s[1], "principal_id": s[2], "device_id": s[3], "mode": s[4],
            "started_at": _iso(s[5]), "ended_at": _iso(s[6]), "documents": list(s[7] or []), "turns": turns,
            "cost_usd": float(sum(Decimal(str(t["cost_usd"])) for t in turns))}


def turn_photo_ref(principal: Principal, session_id: str, turn_id: str) -> str | None:
    with principal_tx(principal) as cur:
        cur.execute("SELECT photo_ref FROM field.assistant_turn WHERE id::text = %s AND session_id::text = %s",
                    (turn_id, session_id))
        r = cur.fetchone()
    return str(r[0]) if r and r[0] else None


def _cell(v: Any) -> str:
    """CSV cell; values that a spreadsheet would run as a formula are prefixed with a quote."""
    text = "" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def turns_csv(detail: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    rows: Iterable[dict[str, Any]] = detail["turns"]
    for t in rows:
        w.writerow([_cell(x) for x in (detail["id"], t["id"], t["at"], t["event"], t["heard"], t["said"], t["code"],
                                       t["task_id"], t["ai"], t["cost_usd"], t["latency_ms"], t["actions"],
                                       t["tool_calls"], t["photo_ref"])])
    return buf.getvalue()
