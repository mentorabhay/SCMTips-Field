"""The 3-minute demo run (tools/dev_stack/demo_run.py, M4-C17) and the erp-sim reset it relies on.

The run itself needs both stacks (it was proven twice against the real core, docs/evidence/runs/); here: the beats
run in order and stop at the first failure with its recovery, a failing tool or a missing check fails its beat, the
kit's passwords never reach the screen or the log, the receipt beat requires the core's re-plan, the scenario report
is checked, and ``seed-core-export --reset`` really puts erp-sim's plants of the export back (on erp-sim's database).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest

from tools.dev_stack import core_smoke, demo_run, erp_feed, stack
from tools.dev_stack.core_export import load_into_erpsim, parse_export

CORE_EXPORT = Path(__file__).resolve().parent / "fixtures" / "core_export"
ERPSIM = "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim"


class _Runner:
    """A test double of demo_run.run_cmd: one canned (exit code, stdout, stderr) per tool name."""

    def __init__(self, answers: Mapping[str, tuple[int, str, str]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> tuple[int, str, str]:
        self.calls.append(list(cmd))
        key = next((k for k in self.answers if k in " ".join(cmd)), "")
        return self.answers.get(key, (0, "", ""))


def _ctx(tmp_path: Path, runner: _Runner | None = None) -> demo_run.Ctx:
    return demo_run.Ctx(core=tmp_path, scenario="magnet-export-curbs", po="PO-26-1002", web="http://app.localhost:3100",
                        wait=1.0, core_env={}, run=runner, po_item="CP-204", po_plant="PLANT-GOA")


def test_m4_c17_the_beats_run_in_order_and_stop_at_the_first_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                      capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[int] = []

    def ok(n: int) -> Any:
        def step(ctx: demo_run.Ctx, out: demo_run.Outcome) -> None:
            seen.append(n)
            out.checked.append(f"beat {n} check")
        return step

    def broken(ctx: demo_run.Ctx, out: demo_run.Outcome) -> None:
        seen.append(4)
        raise demo_run.BeatFailed("check failed: the core auto-drafted a decision")

    monkeypatch.setattr(demo_run, "STEPS", {**{n: ok(n) for n in range(8)}, 4: broken})
    ctx = _ctx(tmp_path)
    outcomes = demo_run.play(ctx)
    assert seen == [0, 1, 2, 3, 4]  # nothing after the failed beat runs
    assert [o.ok for o in outcomes] == [True, True, True, True, False]
    text = "\n".join(ctx.log)
    assert "beat 4 FAILED" in text and "recovery: the core: `uv run scmtips-scenario inject" in text
    assert "file / fallback for the video: the signals workbook file" in text
    assert "beat 3 ok" in text and "beat 5" not in text


def test_m4_c17_a_failing_tool_fails_its_beat_and_withheld_output_stays_withheld(tmp_path: Path) -> None:
    runner = _Runner({"scmtips-local-demo": (3, "Org admin  admin@x  Secr3t-Pw-123\n", "boom: the worker is down\n")})
    ctx = _ctx(tmp_path, runner)
    out = demo_run.Outcome(1, "t", ok=False, seconds=0)
    with pytest.raises(demo_run.BeatFailed, match="exited with code 3"):
        demo_run._exec(ctx, out, ["uv", "run", "scmtips-local-demo", "--with-team"], tmp_path, {}, show=False)
    text = "\n".join(ctx.log)
    assert "Secr3t-Pw-123" not in text and "boom: the worker is down" in text


def test_m4_c17_the_reset_beat_never_shows_or_logs_the_kits_passwords(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    runner = _Runner({"scmtips-demo reset": (0, "demo reset: 12 rows deleted, the sample is loading again\n", ""),
                      "scmtips-local-demo": (0, "Org admin  admin@scmtips.local  Secr3t-Pw-123\n"
                                                " Credentials file: .local/demo-account.json\n", "")})

    class _Web:
        def __init__(self, base: str, role: str) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(demo_run, "_uv", lambda: "uv")
    monkeypatch.setattr(demo_run, "pending_deliveries", lambda: {"another-tenant": 2})
    monkeypatch.setattr(core_smoke, "CoreWeb", _Web)
    monkeypatch.setattr(core_smoke, "core_base", lambda: "http://core")
    monkeypatch.setattr(core_smoke, "core_line", lambda web, ref, item: {
        "status": "open", "qty": "1600", "location_code": "PLANT-GOA"})
    ctx = _ctx(tmp_path, runner)
    out = demo_run.Outcome(1, "t", ok=False, seconds=0)
    demo_run.beat_reset(ctx, out)
    assert "Secr3t-Pw-123" not in "\n".join(ctx.log) and "Secr3t-Pw-123" not in capsys.readouterr().out
    assert len(out.checked) == 4 and "is open again" in out.checked[3]
    runner.answers = {**runner.answers, "scmtips-demo reset": (0, "nothing\n", "")}
    with pytest.raises(demo_run.BeatFailed, match="reset its demo organisation"):
        demo_run.beat_reset(ctx, demo_run.Outcome(1, "t", ok=False, seconds=0))


def test_m4_c17_the_reset_waits_until_no_feed_row_for_the_core_is_pending(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _Runner({})
    ctx = _ctx(tmp_path, runner)
    ctx.tenant = "core-tenant"
    monkeypatch.setattr(demo_run, "pending_deliveries", lambda: {"core-tenant": 3})
    with pytest.raises(core_smoke.SmokeFailure, match="pending feed rows"):
        demo_run.beat_reset(ctx, demo_run.Outcome(1, "t", ok=False, seconds=0))
    assert runner.calls == []  # the core was not reset: an older row would have landed after the reset


RECEIPT = ("export mode: erp-sim holds the core PO under its own codes, no code map\n"
           "core after: PO-26-1002 status received qty 1600.0000 (was open 1600.0000)\n")


def test_m4_c17_the_receipt_beat_requires_the_cores_re_plan(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _Runner({"smoke --core": (0, RECEIPT + "re-plan: no new base plan run within 120 s\n", "")}))
    with pytest.raises(demo_run.BeatFailed, match="re-planned"):
        demo_run.beat_receipt(ctx, demo_run.Outcome(6, "t", ok=False, seconds=0))
    runner = _Runner({"smoke --core": (0, RECEIPT + "re-plan: base plan run a1 -> b2; CP-204 now on_hand 3280\n", "")})
    ctx = _ctx(tmp_path, runner)
    out = demo_run.Outcome(6, "t", ok=False, seconds=0)
    demo_run.beat_receipt(ctx, out)
    assert len(out.checked) == 3
    assert runner.calls[0][-4:] == ["smoke", "--core", "--wait", "1"]


def test_m4_c17_the_scenario_report_is_checked_and_names_the_decision(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_run, "_uv", lambda: "uv")
    rep = {"transport": "signal_file", "signal": {"id": "s1", "band_label": "HIGH"}, "exposure": {"starvation": []},
           "decision": {"id": "d-42", "auto_drafted": True, "options": ["reallocate"]},
           "brief": {"accepted": True, "changed_number_refused": True}, "unmet": []}
    ctx = _ctx(tmp_path, _Runner({"inject": (0, "warning\n" + json.dumps(rep), "")}))
    demo_run.beat_inject(ctx, demo_run.Outcome(4, "t", ok=False, seconds=0))
    assert ctx.decision == "d-42"
    bad = {**rep, "unmet": ["decision options ['reroute']"]}
    ctx = _ctx(tmp_path, _Runner({"inject": (0, json.dumps(bad), "")}))
    with pytest.raises(demo_run.BeatFailed, match="unmet"):
        demo_run.beat_inject(ctx, demo_run.Outcome(4, "t", ok=False, seconds=0))
    ctx = _ctx(tmp_path, _Runner({"inject": (0, "no json here", "")}))
    with pytest.raises(demo_run.BeatFailed, match="no JSON report"):
        demo_run.beat_inject(ctx, demo_run.Outcome(4, "t", ok=False, seconds=0))


def test_m4_c17_the_approval_beat_approves_exactly_the_injected_decision(tmp_path: Path) -> None:
    runner = _Runner({"--approver": (0, "decision d-42: 1 waiting\n 'approve option two' -> read-back\n", "")})
    ctx = _ctx(tmp_path, runner)
    ctx.decision = "d-42"
    demo_run.beat_approve(ctx, demo_run.Outcome(5, "t", ok=False, seconds=0))
    assert runner.calls[0][-5:] == ["--approver", "--decision", "d-42", "--wait", "1"]


def test_m4_c17_core_commands_get_the_callers_env_without_field_values_or_its_venv() -> None:
    env = demo_run.core_env_from({"PATH": "/bin", "VIRTUAL_ENV": "/field/.venv", "FIELD_CORE_SMOKE_ADMIN_PASSWORD": "x",
                                  "LR_DEMO_MODE": "true"})
    assert env == {"PATH": "/bin", "LR_DEMO_MODE": "true"}


def test_m4_c17_the_po_comes_from_the_cores_export(tmp_path: Path) -> None:
    core = tmp_path / "core"
    (core / "samples" / "exports").mkdir(parents=True)
    import shutil

    shutil.copytree(CORE_EXPORT / "erp-sim", core / "samples" / "exports" / "erp-sim")
    assert demo_run.export_po(core, "PO-26-1002") == ("CP-204", "PLANT-GOA", "open")
    with pytest.raises(demo_run.BeatFailed, match="not a PO line"):
        demo_run.export_po(core, "PO-99")


def test_m4_c17_main_refuses_a_missing_core_checkout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_run.main(["--core", str(tmp_path / "nope")]) == 1
    assert "FAIL: --core" in capsys.readouterr().out


def test_m4_c17_wait_equal_repeats_the_compare_until_the_core_has_committed() -> None:
    answers = [["on-hand RM-307@PLANT-GOA: erp-sim 2600, core 1620.0"], []]
    now = [0.0]
    sleeps: list[float] = []
    def sleep(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    got = erp_feed.wait_equal(lambda: answers.pop(0), wait=10, clock=lambda: now[0], sleep=sleep)
    assert got == [] and sleeps == [2.0]
    late = erp_feed.wait_equal(lambda: ["PO 4543482659 RM-978CB: not at the core"], wait=3, clock=lambda: now[0],
                               sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert late == ["PO 4543482659 RM-978CB: not at the core"]  # still different when the wait ran out: a failure


def test_m4_c17_decision_only_with_the_approver_against_the_real_core(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "apply_ports", lambda: None)
    monkeypatch.setattr(core_smoke, "smoke_approver_real",
                        lambda api, st, w, scenario=None, decision=None: calls.append(f"approver {decision}"))
    ns = argparse.Namespace(api="http://127.0.0.1:8020", wait=7.0, all=False, home=False, core=False, approver=True,
                            scenario=None, decision="d-42")
    monkeypatch.setenv("FIELD_CORE_TARGET", "standin")
    assert stack.cmd_smoke(ns) == 1  # the stand-in has no such decision: refused, never skipped
    monkeypatch.setenv("FIELD_CORE_TARGET", "core")
    ns.scenario = "magnet-export-curbs"
    assert stack.cmd_smoke(ns) == 1  # one or the other
    ns.scenario = None
    assert stack.cmd_smoke(ns) == 0
    assert calls == ["approver d-42"]


DOCS_ROOT = Path(__file__).resolve().parents[3]


def test_m4_c17_the_demo_run_page_matches_the_orchestrator() -> None:
    page = (DOCS_ROOT / "docs" / "DEMO_RUN.md").read_text(encoding="utf-8")
    table = [ln for ln in page.splitlines() if re.match(r"^\| [0-7] \|", ln)]
    assert [int(ln.split("|")[1]) for ln in table[:8]] == [b.n for b in demo_run.BEATS]
    stack_src = (DOCS_ROOT / "tools" / "dev_stack" / "stack.py").read_text(encoding="utf-8")
    for flag in ("--reset", "--decision", "--erp-feed", '"seed-core-export"', '"--core"', '"--approver"'):
        assert flag in stack_src, flag
    assert demo_run.DEFAULT_PO in page and demo_run.DEFAULT_SCENARIO in page
    for script in ("demo-run.ps1", "demo-run.cmd", "demo-run.sh"):
        assert (DOCS_ROOT / "scripts" / "dev" / script).is_file()
        assert f"scripts/dev/{script}" in page.replace("\\", "/") or script in page


# --- seed-core-export --reset on erp-sim's database (SAP client 930: never the dev stack's 100) -------------------

CLIENT = "930"


def _client(cur: psycopg.Cursor[Any]) -> None:
    cur.execute("INSERT INTO erpsim.number_range (client, object, current, lower, upper)"
                " VALUES (%s, 'MATERIAL_DOCUMENT', 4930000000, 4930000000, 4939999999) ON CONFLICT DO NOTHING",
                (CLIENT,))


def _line(po: str) -> Any:
    from erp_sim.app import app as erpsim_app
    from field_sap.sim.adapter import SimAdapter

    sim = SimAdapter(app=erpsim_app, sap_client=CLIENT)
    return {ln.purchase_order: ln for ln in asyncio.run(sim.list_purchase_order_items("PLANT-GOA"))}.get(po)


def _open_asn(cur: psycopg.Cursor[Any], po: str) -> str | None:
    cur.execute("SELECT d.delivery_document FROM erpsim.inbound_delivery d JOIN erpsim.inbound_delivery_item i"
                " USING (client, delivery_document) WHERE d.client = %s AND d.status = 'open' AND i.status = 'open'"
                " AND i.purchase_order = %s", (CLIENT, po))
    row = cur.fetchone()
    return str(row[0]) if row else None


def test_m4_c17_reset_puts_the_exports_plants_back_so_the_receipt_can_run_again() -> None:
    from erp_sim.app import app as erpsim_app
    from field_sap.ports.erp_port import ErpPostingRequest
    from field_sap.sim.adapter import SimAdapter

    ex = parse_export(CORE_EXPORT / "erp-sim")
    stray_po = f"45{uuid.uuid4().int % 10**8:08d}"
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        _client(cur)
        load_into_erpsim(cur, ex, client=CLIENT, reset=True)  # a known start, whatever earlier runs left
        # what an earlier test or a code-map run leaves in the export's plant: a PO line and a stock row it lacks
        cur.execute("INSERT INTO erpsim.purchase_order (client, purchase_order, supplier) VALUES (%s, %s, '')",
                    (CLIENT, stray_po))
        cur.execute("INSERT INTO erpsim.purchase_order_item (client, purchase_order, item_no, material_no, plant,"
                    " storage_location, order_qty, uom, status) VALUES (%s, %s, '10', 'CP-207', 'PLANT-GOA', '0001',"
                    " 12, 'EA', 'open')", (CLIENT, stray_po))
        cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom) VALUES"
                    " (%s, 'PLANT-GOA', '0002', 'CP-204', 99, 'EA') ON CONFLICT DO NOTHING", (CLIENT,))
        deliv = _open_asn(cur, "PO-26-1002")
        c.commit()
    assert deliv is not None
    sim = SimAdapter(app=erpsim_app, sap_client=CLIENT)  # the demo's receipt: the ASN received, GR 101 against the PO
    asyncio.run(sim.post_inbound_goods_receipt(ErpPostingRequest(
        idempotency_key=f"c17_{uuid.uuid4().hex[:12]}", doc_family="GoodsReceipt", site_id="CORE", plant="PLANT-GOA",
        posting_date="2026-11-03", header_data={"DeliveryDocument": deliv}, items=())))
    received = _line("PO-26-1002")
    assert received is not None and float(received.received_qty) == 1600
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:  # a plain re-seed: the received line gets no new ASN
        assert load_into_erpsim(cur, ex, client=CLIENT)["asns_created"] == 0
        assert _open_asn(cur, "PO-26-1002") is None
        c.commit()
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:  # the demo's re-seed after the core's reset
        counts = load_into_erpsim(cur, ex, client=CLIENT, reset=True)
        c.commit()
        assert counts["gr_items_cancelled"] == 1 and counts["po_lines_removed"] == 1
        assert counts["stock_rows_removed"] == 1 and counts["asns_created"] == 1
        assert _open_asn(cur, "PO-26-1002") not in (None, deliv)
        cur.execute("SELECT count(*) FROM erpsim.purchase_order WHERE client = %s AND purchase_order = %s",
                    (CLIENT, stray_po))
        assert cur.fetchone() == (0,)
        cur.execute("SELECT item_data->>'cancelled_by' FROM erpsim.document_item WHERE client = %s"
                    " AND item_data->>'PurchaseOrder' = 'PO-26-1002'", (CLIENT,))
        assert {r[0] for r in cur.fetchall()} == {"seed-core-export --reset"}  # cancelled, never deleted
    again = _line("PO-26-1002")
    assert again is not None and float(again.received_qty) == 0 and float(again.order_qty) == 1600
    assert asyncio.run(sim.read_stock("CP-204", "PLANT-GOA")) == 1680  # the export's stock, the stray row gone
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:  # and again: nothing more to do
        assert load_into_erpsim(cur, ex, client=CLIENT, reset=True)["asns_created"] == 0
        c.commit()
