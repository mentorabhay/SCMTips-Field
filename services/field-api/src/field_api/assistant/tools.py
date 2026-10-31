"""Server-side tools of the Field Assistant (M3 contract §4): list_work, task_detail, lookup_code,
add_sandbox_item, session_summary, and (M4) new sandbox receipts and counts.

The model is offered list_work, task_detail, lookup_code and session_summary. Since M4 (rules first, owner's field
test of 31 Oct 2026) every effect is rules-only: the unknown-code dialog that adds an item and the new receipt or
count are answered by rules and never reach the model, so add_sandbox_item is no longer a model tool and a model
that calls it anyway gets "unknown tool".

Guarantees that do not depend on the model:
- task data comes through ``work.project_task``: count tasks never carry book, expected or counted quantities;
- add_sandbox_item runs only on a sandbox site, only through the injected port, only for the code the operator
  scanned in this dialog, and only after the operator answered "What is it?" and "How many?" (or said an explicit
  yes in this turn);
- new receipts and counts are created only on a sandbox site, only through the injected ports;
- tool calls are recorded per turn (name, arguments, ok) for the session record.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from field_api.assistant import records, work
from field_api.assistant.ports import AssistantPorts
from field_api.auth.jwt import Principal
from field_api.errors import FieldError

logger = structlog.get_logger(__name__)

SANDBOX_TASK_TYPES = frozenset({"receive", "count"})


@dataclass
class TurnContext:
    principal: Principal
    site_id: str
    session_id: str
    site_mode: str
    ports: AssistantPorts
    idempotency_key: str
    task_id: str | None = None
    dialog: dict[str, Any] | None = None
    explicit_yes: bool = False


@dataclass
class AssistantTools:
    ctx: TurnContext
    calls: list[dict[str, Any]] = field(default_factory=list)
    added: dict[str, Any] | None = None
    _work: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------ data
    def work(self) -> list[dict[str, Any]]:
        if self._work is None:
            self._work = work.list_work(self.ctx.principal, self.ctx.site_id)
        return self._work

    def list_work(self) -> list[dict[str, Any]]:
        """Compact list for the model: no lines (task_detail has them)."""
        out = []
        for t in self.work():
            lines = t.get("lines") or []
            out.append({"id": t["id"], "type": t["type"], "status": t["status"], "title": t["title"],
                        "subtitle": t["subtitle"], "priority": t.get("priority"), "due": t.get("due"),
                        "reason": t.get("reason"), "lines_total": len(lines),
                        "lines_open": len(work.remaining_lines(t))})
        return out

    def task_detail(self, task_id: str | None) -> dict[str, Any] | None:
        if not task_id:
            return None
        for t in self.work():
            if t["id"] == task_id:
                return t
        return work.task_detail(self.ctx.principal, self.ctx.site_id, task_id)

    def current_task(self) -> dict[str, Any] | None:
        return self.task_detail(self.ctx.task_id)

    @property
    def can_resolve(self) -> bool:
        return self.ctx.ports.resolve_code is not None

    @property
    def can_add(self) -> bool:
        return self.ctx.ports.add_item is not None

    @property
    def can_create(self) -> bool:
        return self.ctx.ports.create_receipt is not None and self.ctx.ports.create_count is not None

    def site_bins(self) -> list[str]:
        return work.site_bins(self.ctx.principal, self.ctx.site_id)

    def _created(self, name: str, args: dict[str, Any], fn: Callable[[], Any]) -> dict[str, Any]:
        if self.ctx.site_mode != "sandbox":
            result: dict[str, Any] = {"ok": False, "error": "This is a production site.", "code": "production"}
        else:
            try:
                r = fn()
                result = {"ok": True, "task_id": r["task_id"], "ref_doc_no": r["ref_doc_no"]}
                self._work = None  # the work list changed
            except FieldError as e:
                result = {"ok": False, "error": e.title, "code": e.code}
        self.calls.append({"name": name, "args": args, "ok": bool(result.get("ok"))})
        return result

    def new_receipt(self) -> dict[str, Any]:
        """A new, empty home receipt on this sandbox site (rules only)."""
        port = self.ctx.ports.create_receipt
        if port is None:
            return {"ok": False, "error": "Creating receipts is not available in this build.", "code": "not_wired"}
        return self._created("new_receipt", {}, lambda: port(self.ctx.principal, self.ctx.site_id))

    def new_count(self, storage_bin: str) -> dict[str, Any]:
        """A new, empty blind count of one bin of this sandbox site (rules only)."""
        port = self.ctx.ports.create_count
        if port is None:
            return {"ok": False, "error": "Creating counts is not available in this build.", "code": "not_wired"}
        return self._created("new_count", {"bin": storage_bin},
                             lambda: port(self.ctx.principal, self.ctx.site_id, storage_bin))

    def lookup_code(self, code: str) -> dict[str, Any]:
        code = (code or "").strip()
        tasks = list(self.work())
        cur = self.current_task()
        if cur is not None and all(t["id"] != cur["id"] for t in tasks):
            tasks.insert(0, cur)
        hits = work.match_code(tasks, code) if code else []
        if cur is not None:
            hits.sort(key=lambda h: h["task_id"] != cur["id"])
        resolver = self.ctx.ports.resolve_code
        if resolver is not None and code:
            r = resolver(self.ctx.principal, self.ctx.site_id, code)
            out: dict[str, Any] = {"code": r["code"], "kind": r["kind"],
                                   "material": dict(r["material"]) if r["material"] else None,
                                   "bin": r["bin"], "site_mode": r["site_mode"], "source": "codes"}
        else:
            first = hits[0] if hits else None
            kind = first["kind"] if first else "unknown"
            out = {"code": code, "kind": kind,
                   "material": ({"material": first["material"], "description": first["description"],
                                 "uom": first["uom"]} if first and kind == "material" else None),
                   "bin": first["bin"] if first and kind == "bin" else None,
                   "site_mode": self.ctx.site_mode, "source": "task_lines"}
        out["task_lines"] = [{k: h[k] for k in ("task_id", "task_title", "task_type", "line_id", "line_no", "kind")}
                             for h in hits[:5]]
        return out

    def session_summary(self) -> dict[str, Any]:
        return records.session_summary(self.ctx.principal, self.ctx.session_id)

    # ------------------------------------------------------------------ the one tool with an effect
    def add_sandbox_item(self, code: str, description: str, qty: Any = None, *,
                         answered_dialog: bool = False) -> dict[str, Any]:
        add = self.ctx.ports.add_item
        if add is None:
            return {"ok": False, "error": "Adding items is not available in this build."}
        if self.ctx.site_mode != "sandbox":
            return {"ok": False, "error": "This is a production site: new items cannot be added."}
        pending = self.ctx.dialog or {}
        if pending.get("kind") != "sandbox_item" or str(pending.get("code") or "") != (code or "").strip():
            return {"ok": False, "error": "Only the unknown code scanned in this dialog can be added."}
        if not (answered_dialog or self.ctx.explicit_yes):
            return {"ok": False, "error": "Ask the operator first; add only after they say yes."}
        description = " ".join(str(description or "").split())[:80]
        if not description:
            return {"ok": False, "error": "The item needs a name."}
        quantity: Decimal | None = None
        if qty is not None and qty != "":
            try:
                quantity = Decimal(str(qty))
            except InvalidOperation:
                return {"ok": False, "error": "The quantity must be a number."}
            if not quantity.is_finite() or quantity < 0:
                return {"ok": False, "error": "The quantity must be zero or more."}
        task_id = str(pending.get("task_id") or self.ctx.task_id or "")
        task = self.task_detail(task_id) if task_id else None
        if task is None or task["type"] not in SANDBOX_TASK_TYPES:
            return {"ok": False, "error": "Open a receipt or a count first."}
        try:
            r = add(self.ctx.principal, task_id, pending["code"], description, quantity,
                    f"{self.ctx.idempotency_key}:sandbox-item")
        except FieldError as e:
            return {"ok": False, "error": e.title, "code": e.code}
        self.added = {"task_id": task_id, "code": pending["code"], "description": description,
                      "qty": None if quantity is None else str(quantity), "line_id": r["line_id"],
                      "material": r["material"], "created_material": bool(r["created_material"])}
        self._work = None  # the task changed
        return {"ok": True, **self.added}

    # ------------------------------------------------------------------ model dispatch
    def run(self, name: str, arguments: str | dict[str, Any] | None) -> dict[str, Any]:
        """Execute one model tool call; never raises (the model gets an error object instead)."""
        args: Any
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
        except ValueError:
            args = None
        if not isinstance(args, dict):
            result: dict[str, Any] = {"ok": False, "error": "arguments must be a JSON object"}
        else:
            a: dict[str, Any] = args
            fn: Callable[[], Any] | None = {
                "list_work": lambda: {"ok": True, "tasks": self.list_work()},
                "task_detail": lambda: ({"ok": True, "task": t} if (t := self.task_detail(str(a.get("task_id") or "")))
                                        else {"ok": False, "error": "no such task at this site"}),
                "lookup_code": lambda: {"ok": True, **self.lookup_code(str(a.get("code") or ""))},
                "session_summary": lambda: {"ok": True, **self.session_summary()},
            }.get(name)
            if fn is None:
                result = {"ok": False, "error": f"unknown tool {name}"}
            else:
                try:
                    result = fn()
                except FieldError as e:
                    result = {"ok": False, "error": e.title}
        self.calls.append({"name": name, "args": args if isinstance(args, dict) else None,
                           "ok": bool(result.get("ok"))})
        return result


def tool_specs() -> list[dict[str, Any]]:
    """OpenAI-compatible function tools offered to the model: reads only (every effect is rules-only, M4)."""

    def fn(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {
            "type": "object", "properties": props, "required": required, "additionalProperties": False}}}

    return [
        fn("list_work", "Open and started jobs at this site, most urgent first (no lines).", {}, []),
        fn("task_detail", "One job with its lines. Count jobs never include quantities.",
           {"task_id": {"type": "string"}}, ["task_id"]),
        fn("lookup_code", "What a scanned code is (material, bin, serial or unknown) and which job lines have it.",
           {"code": {"type": "string"}}, ["code"]),
        fn("session_summary", "What this work session did so far: turns, jobs, SAP documents.", {}, []),
    ]
