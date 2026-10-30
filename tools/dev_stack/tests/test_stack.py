"""Field-test stack helpers: .env.local generation never leaks or overwrites secrets; pairing payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.dev_stack import stack
from tools.dev_stack.stack import GENERATED_SECRETS, ensure_env_local, pairing_payload, parse_env


def test_env_local_is_created_with_fresh_secrets_and_never_overwritten(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FIELD_ENV=development\nFIELD_JWT_SECRET=\n# comment\nLLAMA_API_KEY=\n", encoding="utf-8")
    target = tmp_path / ".env.local"
    filled = ensure_env_local(example, target)
    assert set(filled) == set(GENERATED_SECRETS)
    env = parse_env(target.read_text(encoding="utf-8"))
    assert all(len(env[k]) == 64 for k in GENERATED_SECRETS)
    assert env["LLAMA_API_KEY"] == "" and env["FIELD_ENV"] == "development"
    before = target.read_text(encoding="utf-8")
    assert ensure_env_local(example, target) == []  # second run keeps every existing value
    assert target.read_text(encoding="utf-8") == before


def test_owner_values_survive(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("FIELD_JWT_SECRET=\n", encoding="utf-8")
    target = tmp_path / ".env.local"
    target.write_text("FIELD_JWT_SECRET=owner-chosen-value-that-is-long-enough-000000\nLLAMA_API_KEY=x\n", encoding="utf-8")
    ensure_env_local(example, target)
    env = parse_env(target.read_text(encoding="utf-8"))
    assert env["FIELD_JWT_SECRET"].startswith("owner-chosen") and env["LLAMA_API_KEY"] == "x"


def test_pairing_payload_is_the_contract_the_app_parses() -> None:
    p = json.loads(pairing_payload("http://192.168.1.23:8000/", "tok", "t", "s", "Site"))
    assert p == {"v": 1, "api": "http://192.168.1.23:8000", "token": "tok", "tenant": "t", "site": "s", "site_name": "Site"}


def test_parse_env_ignores_comments_and_quotes() -> None:
    assert parse_env('# x\nA=1\nB="two"\n\nC\n') == {"A": "1", "B": "two"}


def test_ports_default_avoid_scmtips_core_and_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.dev_stack import stack

    monkeypatch.delenv("FIELD_STACK_CORE_PORT", raising=False)
    assert stack.port("fake-core") == 8011  # 8001 is where SCMTips core itself often runs
    monkeypatch.setenv("FIELD_STACK_CORE_PORT", "8123")
    monkeypatch.setenv("FIELD_CORE_JWKS_URL", "http://127.0.0.1:8001/.well-known/jwks.json")  # stale .env.local value
    stack.apply_ports()
    import os

    assert os.environ["FIELD_CORE_JWKS_URL"] == "http://127.0.0.1:8123/.well-known/jwks.json"
    assert os.environ["FIELD_ERP_SIM_URL"] == f"http://127.0.0.1:{stack.port('erp-sim')}"


def test_port_in_use_sees_another_program() -> None:
    import socket

    from tools.dev_stack import stack

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        held = s.getsockname()[1]
        assert stack.port_in_use(held) is True
    assert stack.port_in_use(held) is False


def test_up_refuses_when_another_program_holds_a_port(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Owner's PC, 2026-10-31: something else held 8001; fake-core died on bind and the health probe
    was answered by the other program. With an explicit port, `up` must stop before starting anything."""
    import argparse

    from tools.dev_stack import stack

    monkeypatch.setattr(stack, "ensure_env_local", lambda: [])
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "running", lambda name: None)
    monkeypatch.setattr(stack, "PORTS_FILE", stack.ROOT / "var" / "test_ports_refuse.json")
    monkeypatch.setenv("FIELD_STACK_CORE_PORT", "8011")  # an explicit port is never moved
    monkeypatch.setattr(stack, "port_in_use", lambda p: p == 8011)
    started: list[str] = []
    monkeypatch.setattr(stack, "ensure_database", lambda: started.append("db"))
    def fake_start(name: str, cmd: list[str]) -> int:
        started.append(name)
        return 1

    monkeypatch.setattr(stack, "start", fake_start)
    assert stack.cmd_up(argparse.Namespace(local_only=True)) == 1
    assert started == []
    assert "FIELD_STACK_CORE_PORT" in capsys.readouterr().out


def test_saved_demo_site_is_reused_only_if_it_still_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.dev_stack import stack

    monkeypatch.setattr(stack, "site_exists", lambda site_id: site_id == "alive")
    kept = {"tenant": "t", "site": "alive", "site_name": "n"}
    assert stack.ensure_demo_site(dict(kept)) == kept
    calls: list[str] = []

    class Resp:
        status_code = 201

        def raise_for_status(self) -> Resp:
            return self

        def json(self) -> dict[str, str]:
            calls.append("post")
            return {"access_token": "x", "id": "new-site", "name": "SAMPLE warehouse (field test)"}

    monkeypatch.setattr("tools.dev_stack.stack.httpx.post", lambda *a, **k: Resp())
    monkeypatch.setattr(stack, "_field_token", lambda tok: "field")
    monkeypatch.setattr(stack, "STATE", stack.ROOT / "var" / "test_dev_stack_state.json")
    try:
        out = stack.ensure_demo_site({"tenant": "t", "site": "gone", "site_name": "old"})
    finally:
        stack.STATE.unlink(missing_ok=True)
    assert out["site"] == "new-site" and out["tenant"] == "t" and calls


def test_busy_default_ports_move_to_the_next_free_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Owner's PC, 2026-10-31: 8000 was taken after 8001. `up` now moves on, saves the choice, and the
    QR code / smoke / delivery commands read the same saved ports."""
    from tools.dev_stack import stack

    for var, _ in stack.PORTS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(stack, "PORTS_FILE", tmp_path / "ports.json")
    monkeypatch.setattr(stack, "running", lambda name: None)
    monkeypatch.setattr(stack, "owner_of_port", lambda p: "pid 1 (other.exe)")
    busy = {8000, 8001, 8011}
    monkeypatch.setattr(stack, "port_in_use", lambda p: p in busy)
    chosen = stack.choose_ports()
    # 8000/8001 busy, 8002 already given to erp-sim -> field-api gets 8003; fake-core 8011 busy -> 8012
    assert chosen == {"fake-core": 8012, "erp-sim": 8002, "field-api": 8003}
    assert stack.port("field-api") == 8003
    assert json.loads((tmp_path / "ports.json").read_text(encoding="utf-8")) == chosen
    assert stack.local("fake-core") == "http://127.0.0.1:8012"


def test_pair_survives_a_console_without_block_characters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    """Owner's PC, 2026-10-31: qrcode.print_ascii raised UnicodeEncodeError on the cp1252 console and
    pair exited 1. The SVG is written first and the console failure is only a notice."""
    import argparse

    import qrcode

    from tools.dev_stack import stack

    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(stack, "ensure_demo_site", lambda s: {"tenant": "t", "site": "s", "site_name": "Site"})
    monkeypatch.setattr(stack, "_core_token", lambda *a: "tok")

    def no_blocks(self: object, **kw: object) -> None:
        raise UnicodeEncodeError("charmap", "█", 0, 1, "character maps to <undefined>")

    monkeypatch.setattr(qrcode.QRCode, "print_ascii", no_blocks)
    args = argparse.Namespace(user="op", hours=1, api="http://192.168.1.2:8003", no_ascii=False, no_open=True)
    assert stack.cmd_pair(args) == 0
    assert (tmp_path / "var" / "pairing-qr.svg").stat().st_size > 1000
    assert "cannot draw the QR code" in capsys.readouterr().out


def test_m2_commands_and_phone_hash_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """M2 contract §4/§8: the smoke hashes exactly as the phone does; outbound/count/tower/smoke --all exist."""
    import hashlib

    import httpx

    from tools.dev_stack import stack

    seen: list[str] = []

    def recorder(name: str) -> object:
        def run(a: object) -> int:
            seen.append(f"{name}:{getattr(a, 'bin', None)}:{getattr(a, 'all', None)}")
            return 0
        return run

    for cmd in ("outbound", "count", "tower", "smoke"):
        monkeypatch.setattr(stack, f"cmd_{cmd}", recorder(cmd))
    assert stack.main(["outbound"]) == 0 and stack.main(["count", "03-05-02"]) == 0
    assert stack.main(["tower"]) == 0 and stack.main(["smoke", "--all"]) == 0
    assert seen == ["outbound:None:None", "count:03-05-02:None", "tower:None:None", "smoke:None:True"]
    lines = [("b", 2.0), ("a", 0.0)]
    assert stack.Phone.staged_hash(lines) == hashlib.sha256(b"a:0.000|b:2.000").hexdigest()
    task = {"lines": [{"id": "x", "counted_qty": 0.0}, {"id": "y"}]}
    assert stack.Phone.listed(task) == [("x", 0.0), ("y", 0.0)]
    pick = httpx.Response(201, json={"counted_qty": 3.0, "picked_qty": 3.0})
    assert stack.Phone.counted(pick, 9) == 3.0
    assert stack.Phone.counted(httpx.Response(201, json={}), 9) == 9.0


def test_label_sheet_lists_every_code_each_job_asks_for() -> None:
    tasks: list[dict[str, Any]] = [
        {
            "id": "s",
            "type": "swap",
            "title": "Swap RRU",
            "lines": [
                {"line_no": 10, "position": "Sector A · slot 3", "expected_serial": "RRU-SN-OLD"}
            ],
        },
        {
            "id": "p",
            "type": "pick",
            "title": "Pick 80",
            "lines": [
                {"line_no": 20, "bin": "02-01-02", "material": "SAMPLE-MAT-0009"},
                {"line_no": 10, "bin": "02-01-01", "material": "SAMPLE-MAT-0001"},
            ],
        },
        {
            "id": "r",
            "type": "receive",
            "title": "Delivery 18",
            "lines": [{"line_no": 10, "material": "SAMPLE-MAT-0005", "uom": "EA"}],
        },
        {"id": "e", "type": "putaway", "title": "Empty", "lines": []},
    ]
    sheet = stack.label_sheet(tasks, ["RRU-SN-NEW"])
    assert [t for t, _ in sheet] == [
        "Receive: Delivery 18",
        "Pick: Pick 80",
        "Swap: Swap RRU",
    ]  # job order, empty job left out
    pick = dict(sheet[1][1])
    assert list(pick)[:4] == [
        "02-01-01",
        "SAMPLE-MAT-0001",
        "02-01-02",
        "SAMPLE-MAT-0009",
    ]  # walking order
    assert "refused" in pick["03-07-01"]
    swap = dict(sheet[2][1])
    assert (
        swap["RRU-SN-OLD"].endswith("old unit (remove)")
        and swap["RRU-SN-NEW"] == "new unit from store (install)"
    )
    assert stack.UNEXPECTED_SERIAL in swap


def test_label_page_carries_each_code_as_text_and_qr() -> None:
    page = stack.render_labels(
        [
            (
                "Count: bin 02-01-01",
                [
                    ("02-01-01", "the bin being counted"),
                    ("SAMPLE-MAT-9999", "not in this bin (should be refused)"),
                ],
            )
        ],
        "2026-10-31 10:00",
    )
    assert page.count("<svg") == 2 and "02-01-01" in page and "class='l wrong'" in page
    assert "No open jobs" in stack.render_labels([], "now")
