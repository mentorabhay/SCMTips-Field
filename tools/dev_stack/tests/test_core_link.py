"""M4 stream C in the dev stack: the core target settings, the stand-in's demo sign-in print (dev values only,
never a secret), and `stack seed-core-export` (tolerant loader of the core's erp-sim export)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from tools.dev_stack import stack
from tools.dev_stack.core_export import load_into_erpsim, parse_export

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "docs" / "integration" / "exchange-contract-v1" / "examples" / "erp_extract.json"
ERPSIM = os.getenv("ERPSIM_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim")
CORE_VARS = ("FIELD_CORE_BASE_URL", "FIELD_CORE_JWKS_URL", "FIELD_CORE_DEVICE_STATUS_URL",
             "FIELD_CORE_INVENTORY_FEED_URL", "FIELD_CORE_SUPPLY_FEED_URL")


@pytest.fixture
def clean_core_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in (*CORE_VARS, "FIELD_CORE_TARGET", "FAKE_CORE_INVENTORY_FEED_ID", "FAKE_CORE_SUPPLY_FEED_ID"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("FIELD_STACK_CORE_PORT", "8211")


def test_m4_c05_standin_target_points_every_core_url_at_the_stack(clean_core_env: None,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CORE_TARGET", "standin")
    stack.apply_ports()
    assert os.environ["FIELD_CORE_BASE_URL"] == "http://127.0.0.1:8211"
    assert os.environ["FIELD_CORE_JWKS_URL"] == "http://127.0.0.1:8211/v1/core/jwks.json"
    assert os.environ["FIELD_CORE_DEVICE_STATUS_URL"] == (
        "http://127.0.0.1:8211/v1/core/devices/{device_id}/status?tenant_id={tenant_id}")
    assert os.environ["FIELD_CORE_INVENTORY_FEED_URL"] == "http://127.0.0.1:8211/v1/inbound/feeds/standin-inventory"
    assert os.environ["FIELD_CORE_SUPPLY_FEED_URL"] == "http://127.0.0.1:8211/v1/inbound/feeds/standin-open-supply"


def test_m4_c05_core_target_keeps_the_owners_values(clean_core_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_CORE_TARGET", "core")
    monkeypatch.setenv("FIELD_CORE_JWKS_URL", "http://127.0.0.1:8000/v1/core/jwks.json")
    monkeypatch.setenv("FIELD_CORE_INVENTORY_FEED_URL", "http://127.0.0.1:8000/v1/inbound/feeds/abc")
    stack.apply_ports()
    assert os.environ["FIELD_CORE_JWKS_URL"] == "http://127.0.0.1:8000/v1/core/jwks.json"
    assert os.environ["FIELD_CORE_INVENTORY_FEED_URL"] == "http://127.0.0.1:8000/v1/inbound/feeds/abc"
    assert "FIELD_CORE_SUPPLY_FEED_URL" not in os.environ
    monkeypatch.delenv("FIELD_CORE_TARGET")
    stack.apply_ports()  # unset: the pre-M4 behaviour
    assert os.environ["FIELD_CORE_JWKS_URL"] == "http://127.0.0.1:8211/.well-known/jwks.json"


def test_m4_c05_env_local_gets_feed_secrets_and_the_target(tmp_path: Path) -> None:
    old = tmp_path / ".env.local"
    old.write_text("FIELD_JWT_SECRET=keep-me-000000000000000000000000000000\n", encoding="utf-8")
    filled = stack.ensure_env_local(tmp_path / "missing.example", old)
    env = stack.parse_env(old.read_text(encoding="utf-8"))
    assert "FIELD_CORE_INVENTORY_FEED_SECRET" in filled and "FIELD_CORE_SUPPLY_FEED_SECRET" in filled
    assert len(env["FIELD_CORE_INVENTORY_FEED_SECRET"]) == 64 and env["FIELD_CORE_TARGET"] == "standin"
    assert env["FIELD_JWT_SECRET"].startswith("keep-me")
    before = old.read_text(encoding="utf-8")
    assert stack.ensure_env_local(tmp_path / "missing.example", old) == [] and old.read_text(encoding="utf-8") == before
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "FIELD_CORE_TARGET=standin" in example and "FIELD_CORE_INVENTORY_FEED_SECRET=\n" in example


def test_m4_c05_demo_print_shows_dev_defaults_never_owner_values(clean_core_env: None, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FIELD_CORE_TARGET", "standin")
    monkeypatch.delenv("FAKE_CORE_DEMO_PASSWORD", raising=False)
    monkeypatch.setenv("FIELD_CORE_INVENTORY_FEED_SECRET", "feed-secret-value-123")
    stack.print_core_target()
    out = capsys.readouterr().out
    assert "NOT the core" in out and "approver@demo.scmtips.test" in out and stack.DEMO_PASSWORD_DEFAULT in out
    assert "feed-secret-value-123" not in out
    monkeypatch.setenv("FAKE_CORE_DEMO_PASSWORD", "owner-chosen-pw-xyz")
    stack.print_core_target()
    assert "owner-chosen-pw-xyz" not in capsys.readouterr().out
    from fake_core.standin.state import DEFAULT_DEMO_PASSWORD, DEFAULT_STEP_UP_CODE

    assert (stack.DEMO_PASSWORD_DEFAULT, stack.STEP_UP_CODE_DEFAULT) == (DEFAULT_DEMO_PASSWORD, DEFAULT_STEP_UP_CODE)


def test_m4_c05_seed_core_export_missing_folder_is_a_clear_failure(tmp_path: Path,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    assert stack.cmd_seed_core_export(argparse.Namespace(dir=str(tmp_path / "erp-sim"))) == 1
    out = capsys.readouterr().out
    assert "does not exist" in out and "samples" in out and "exports" in out


def test_m4_c05_export_json_envelope_and_csv_load_into_erpsim(tmp_path: Path) -> None:
    folder = tmp_path / "erp-sim"
    folder.mkdir()
    shutil.copy(EXAMPLE, folder / "erp_extract.json")  # the exchange contract's own example (RM-307 @ PLANT-GOA)
    tag = uuid.uuid4().hex[:5].upper()
    (folder / "items.csv").write_text(f"item_code,description,uom\nRM-{tag},Magnet set {tag},EA\n", encoding="utf-8")
    (folder / "purchase_orders.csv").write_text(
        "kind,ref,item_code,location_code,qty,due_date,status\n"
        f"PO,45{uuid.uuid4().int % 10**8:08d}-10,RM-{tag},PLANT-GOA,12,2026-11-12,open\n"
        f"PO,4599999999-20,RM-{tag},PLANT-GOA,5,2026-11-12,received\n", encoding="utf-8")
    (folder / "notes.json").write_text(json.dumps({"bom": [{"parent_code": "SA-1"}]}), encoding="utf-8")
    ex = parse_export(folder)
    assert {"RM-307", f"RM-{tag}"} <= ex.items.keys()
    assert ex.locations.keys() == {"PLANT-GOA"} and ex.inventory[("RM-307", "PLANT-GOA")] == 420
    assert len(ex.po_lines) == 2  # RM-307 line from the envelope + the open CSV line; the received one is skipped
    assert any("bom" in n for n in ex.notes)
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        cur.execute("DELETE FROM erpsim.inbound_delivery WHERE header_data->>'PurchaseOrder' = '4500001234'")
        counts = load_into_erpsim(cur, ex)
        c.commit()
    assert counts["asns_created"] == 2 and counts["materials"] >= 2
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        counts_again = load_into_erpsim(cur, ex)  # re-running makes no second ASN per PO
        c.commit()
        assert counts_again["asns_created"] == 0
        cur.execute("SELECT d.delivery_document, i.material_no, i.delivery_qty, i.purchase_order, i.purchase_order_item"
                    " FROM erpsim.inbound_delivery d JOIN erpsim.inbound_delivery_item i USING (client, delivery_document)"
                    " WHERE d.header_data->>'PurchaseOrder' = '4500001234'")
        [(deliv, mat, qty, po, po_item)] = cur.fetchall()
        cur.execute("SELECT quantity FROM erpsim.stock WHERE plant = 'PLANT-GOA' AND material_no = 'RM-307'"
                    " AND storage_location = '0001'")
        stock_row = cur.fetchone()
        assert stock_row is not None and float(stock_row[0]) == 420
    assert (mat, float(qty), po, po_item) == ("RM-307", 1200.0, "4500001234", "10")
    # receiving the ASN posts a GR 101 that carries the PO line, as the feeds need
    from erp_sim.app import app as erpsim_app
    from field_sap.ports.erp_port import ErpPostingRequest
    from field_sap.sim.adapter import SimAdapter

    sim = SimAdapter(app=erpsim_app)
    res = asyncio.run(sim.post_inbound_goods_receipt(ErpPostingRequest(
        idempotency_key=f"ce_{uuid.uuid4().hex[:12]}", doc_family="GoodsReceipt", site_id="CORE", plant="PLANT-GOA",
        posting_date="2026-11-03", header_data={"DeliveryDocument": deliv}, items=())))
    [item] = asyncio.run(sim.read_material_document(res.document_number, res.fiscal_year)).items
    assert (item.purchase_order, item.purchase_order_item, item.plant) == ("4500001234", "10", "PLANT-GOA")
    assert asyncio.run(sim.read_stock("RM-307", "PLANT-GOA")) >= 1620
