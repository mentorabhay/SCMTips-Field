"""Field-test stack helpers: .env.local generation never leaks or overwrites secrets; pairing payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    was answered by the other program. `up` must stop before starting anything."""
    import argparse

    from tools.dev_stack import stack

    monkeypatch.setattr(stack, "ensure_env_local", lambda: [])
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "running", lambda name: None)
    monkeypatch.setattr(stack, "port_in_use", lambda p: p == stack.port("fake-core"))
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
