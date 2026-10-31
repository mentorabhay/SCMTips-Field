"""What the assistant may know about the open work: the operator's task list, projected.

The source is the same task list the phone reads (``GET /v1/tasks``, ``field_api.tasks.api.list_tasks``), so
the blind-count rule (FR3.029: count tasks carry no expected or counted quantity) holds by construction.
``project_task`` re-applies it with an explicit allow-list: whatever a future list adds, the assistant (and the
model behind it) sees only the fields below, and a count line never carries a quantity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.tasks.api import list_tasks

TASK_FIELDS = ("id", "type", "status", "title", "subtitle", "ref_doc_no", "reason", "due", "priority")
LINE_FIELDS = ("id", "line_no", "material", "description", "uom", "bin", "position", "expected_serial", "status",
               "barcodes")
QTY_FIELDS = ("expected_qty", "counted_qty")  # only on non-count lines
OPEN_STATES = "open,in_progress"
PRIORITY_RANK = MappingProxyType({"urgent": 0, "critical": 0, "high": 1, "medium": 2, "normal": 2, "low": 3})
TYPE_WORDS = MappingProxyType({"receive": ("receipt", "receipts"), "putaway": ("put-away", "put-aways"),
                               "pick": ("pick", "picks"), "count": ("count", "counts"), "audit": ("audit", "audits"),
                               "swap": ("swap", "swaps")})


def project_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Allow-listed copy of one task-list item. Count tasks never carry a quantity on any line."""
    out = {k: task.get(k) for k in TASK_FIELDS}
    blind = task.get("type") == "count"
    lines = []
    for ln in task.get("lines") or []:
        item = {k: ln.get(k) for k in LINE_FIELDS if k in ln}
        if not blind:
            for k in QTY_FIELDS:
                if k in ln:
                    item[k] = ln[k]
        lines.append(item)
    out["lines"] = lines
    return out


def remaining_lines(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(ln) for ln in task.get("lines") or [] if ln.get("status") == "open"]


def urgency_key(task: Mapping[str, Any]) -> tuple[int, int, str, str]:
    """Jobs already started first, then priority, then due date (none last), then age (uuid7 ids sort by time)."""
    started = 0 if task.get("status") == "in_progress" else 1
    rank = PRIORITY_RANK.get(str(task.get("priority") or "medium").lower(), 2)
    return (started, rank, str(task.get("due") or "9999"), str(task.get("id")))


def type_word(task_type: str, n: int = 1) -> str:
    one, many = TYPE_WORDS.get(task_type, (task_type, task_type + "s"))
    return one if n == 1 else many


def count_by_type(tasks: Iterable[Mapping[str, Any]]) -> str:
    """'2 receipts and 1 count'."""
    counts: dict[str, int] = {}
    for t in tasks:
        counts[str(t.get("type"))] = counts.get(str(t.get("type")), 0) + 1
    parts = [f"{n} {type_word(k, n)}" for k, n in counts.items()]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def list_work(principal: Principal, site_id: str) -> list[dict[str, Any]]:
    """Open and started tasks at the site, most urgent first, projected."""
    raw = list_tasks(site_id=site_id, type=None, status=OPEN_STATES, cursor=None, limit=200, principal=principal)
    items: list[dict[str, Any]] = list(raw["items"])
    if not items:
        return []
    with principal_tx(principal) as cur:
        cur.execute("SELECT id::text, priority FROM field.task WHERE id = ANY(%s::uuid[])", ([t["id"] for t in items],))
        prio = {r[0]: r[1] for r in cur.fetchall()}
    tasks = [project_task({**t, "priority": prio.get(t["id"])}) for t in items]
    return sorted(tasks, key=urgency_key)


def task_detail(principal: Principal, site_id: str, task_id: str) -> dict[str, Any] | None:
    """One task of the site in any state (the operator may ask about a job they just finished)."""
    with principal_tx(principal) as cur:
        cur.execute("SELECT type, status, priority FROM field.task WHERE id::text = %s AND site_id::text = %s",
                    (task_id, site_id))
        row = cur.fetchone()
    if not row:
        return None
    raw = list_tasks(site_id=site_id, type=row[0], status=row[1], cursor=None, limit=200, principal=principal)
    for t in raw["items"]:
        if t["id"] == task_id:
            return project_task({**t, "priority": row[2]})
    return None


def site_mode(principal: Principal, site_id: str) -> str | None:
    """'production' | 'sandbox' from field.site.mode (track S adds the column); None if the site is not visible.

    Read through to_jsonb so this works before and after the sandbox migration: without the column every site
    is a production site, which is the column's default."""
    with principal_tx(principal) as cur:
        cur.execute("SELECT COALESCE(to_jsonb(s)->>'mode', 'production') FROM field.site s WHERE s.id::text = %s",
                    (site_id,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def visible_task_ids(principal: Principal, site_id: str, ids: Iterable[str]) -> set[str]:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return set()
    with principal_tx(principal) as cur:
        cur.execute("SELECT id::text FROM field.task WHERE id::text = ANY(%s) AND site_id::text = %s", (wanted, site_id))
        return {r[0] for r in cur.fetchall()}


def match_code(tasks: Iterable[Mapping[str, Any]], code: str) -> list[dict[str, Any]]:
    """Lines whose material, barcodes, bin or expected serial equal ``code`` (trimmed, upper-cased, as the job
    engine compares codes). Each hit: {task_id, task_title, task_type, line_id, line_no, kind, material,
    description, uom, bin}."""
    c = code.strip().upper()
    hits: list[dict[str, Any]] = []
    for t in tasks:
        for ln in t.get("lines") or []:
            codes = {str(ln.get("material") or "").upper(), *(str(b).upper() for b in ln.get("barcodes") or [])}
            kind = None
            if c and c in codes:
                kind = "material"
            elif c and c == str(ln.get("bin") or "").upper():
                kind = "bin"
            elif c and c == str(ln.get("expected_serial") or "").upper():
                kind = "serial"
            if kind:
                hits.append({"task_id": t.get("id"), "task_title": t.get("title"), "task_type": t.get("type"),
                             "line_id": ln.get("id"), "line_no": ln.get("line_no"), "kind": kind,
                             "material": ln.get("material"), "description": ln.get("description"),
                             "uom": ln.get("uom"), "bin": ln.get("bin")})
    return hits


def site_bins(principal: Principal, site_id: str, limit: int = 200) -> list[str]:
    """Active storage bins of one site (field.location rows mapped to an ERP storage bin), by code."""
    with principal_tx(principal) as cur:
        cur.execute("SELECT code FROM field.location WHERE site_id::text = %s AND erp_ref_type = 'storage_bin'"
                    " AND status = 'active' ORDER BY code LIMIT %s", (site_id, limit))
        return [str(r[0]) for r in cur.fetchall()]
