"""Field-test stack helpers: .env.local generation never leaks or overwrites secrets; pairing payload."""

from __future__ import annotations

import json
from pathlib import Path

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
