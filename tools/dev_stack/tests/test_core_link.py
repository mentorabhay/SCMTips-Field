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
    """apply_ports writes os.environ directly: register every variable it touches with monkeypatch first, so the
    values never leak into later tests (e.g. a device-status template would make field-api ask the core)."""
    for v in (*CORE_VARS, "FIELD_ERP_SIM_URL", "FIELD_CORE_TARGET", "FAKE_CORE_INVENTORY_FEED_ID",
              "FAKE_CORE_SUPPLY_FEED_ID", "FAKE_CORE_DEMO_PASSWORD"):
        monkeypatch.setenv(v, "")
        monkeypatch.delenv(v)
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


# --- M4 Q9: the core's real export (samples/exports/erp-sim and field-site-pack, core commit 374702a), trimmed ------

CORE_EXPORT = Path(__file__).resolve().parent / "fixtures" / "core_export"
CLIENT = "910"


def test_m4_c14_split_ref_takes_the_cores_po_number_as_it_is() -> None:
    from tools.dev_stack.core_export import split_ref

    assert split_ref("PO-26-1002", "10") == ("PO-26-1002", "10")
    assert split_ref("PO-26-1002", "") == ("PO-26-1002", "10")  # no item column: the ref is the PO number
    assert split_ref("4500001234-10", "") == ("4500001234", "10")  # the contract's SAP-style example
    assert split_ref("4500001234", "020") == ("4500001234", "20")


def test_m4_c14_the_cores_export_loads_with_its_own_codes_and_purchase_orders() -> None:
    ex = parse_export(CORE_EXPORT / "erp-sim")
    assert ex.manifest == {"export": "erp-sim", "version": 1, "world": "SAMPLE drone OEM", "dataset": "manufacturing-v1"}
    assert ex.notes == []  # every file is one of the loader's tables (suppliers too)
    assert set(ex.locations) == {"DC-MIL", "PLANT-GOA"}
    assert ex.storage_locations == {("DC-MIL", "0001"): "Finished goods store", ("PLANT-GOA", "0001"): "Main store"}
    assert ex.items["CP-204"] == {"description": "Brushless motor, 2806", "uom": "EA", "barcode": "CP-204"}
    assert ex.stock[("CP-204", "PLANT-GOA", "0001")] == 1680 and ex.inventory[("FG-100", "DC-MIL")] == 140
    assert ex.suppliers == {"SUP-S02": "Supplier S-02, Shenzhen", "SUP-S05": "Supplier S-05, Kumamoto"}
    lines = {ln["po"]: ln for ln in ex.po_lines}
    assert lines["PO-26-1002"] == {
        "po": "PO-26-1002", "po_item": "10", "item_code": "CP-204", "location_code": "PLANT-GOA", "qty": 1600.0,
        "due_date": "2026-11-20", "storage_location": "0001", "uom": "EA", "status": "open", "supplier": "SUP-S02",
        "lane_code": "L02"}
    # SAP client 910, not the dev stack's 100: the real codes (PLANT-GOA, PO-26-1002) of the stack's drone world stay as
    # `stack seed-core-export` loaded them
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        counts = load_into_erpsim(cur, ex, client=CLIENT)
        c.commit()
    assert {k: counts[k] for k in ("plants", "storage_locations", "materials", "stock_rows", "po_lines")} == {
        "plants": 2, "storage_locations": 2, "materials": 4, "stock_rows": 4, "po_lines": 2}
    from erp_sim.app import app as erpsim_app
    from field_sap.sim.adapter import SimAdapter

    sim = SimAdapter(app=erpsim_app, sap_client=CLIENT)
    assert asyncio.run(sim.read_stock("CP-204", "PLANT-GOA", "0001")) == 1680
    po = {ln.purchase_order: ln for ln in asyncio.run(sim.list_purchase_order_items("PLANT-GOA"))}
    got = po["PO-26-1005"]
    assert (got.item, got.material, got.storage_location, float(got.order_qty), got.delivery_date, got.supplier,
            got.status, got.lane) == ("10", "CP-207", "0001", 600.0, "2026-12-18", "SUP-S05", "open", "L07")
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:  # the PO's ASN references the core's PO number and item
        cur.execute("SELECT d.storage_location, d.header_data->>'Supplier', i.purchase_order, i.purchase_order_item"
                    " FROM erpsim.inbound_delivery d JOIN erpsim.inbound_delivery_item i USING (client, delivery_document)"
                    " WHERE d.client = %s AND d.header_data->>'PurchaseOrder' = 'PO-26-1002' ORDER BY d.created_at LIMIT 1",
                    (CLIENT,))
        assert cur.fetchone() == ("0001", "SUP-S02", "PO-26-1002", "10")
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        assert load_into_erpsim(cur, ex, client=CLIENT)["asns_created"] == 0  # re-running: no second ASN per PO
        c.commit()


def test_m4_c14_the_site_pack_creates_field_sites_on_the_cores_plants_through_the_api() -> None:
    from fastapi.testclient import TestClient
    from field_api.app import app
    from field_api.auth.jwt import create_dev_token

    from tools.dev_stack.core_export import create_sites, parse_site_pack

    pack = parse_site_pack(CORE_EXPORT / "field-site-pack")
    assert pack.notes == []
    assert [(s["code"], s["kind"], s["erp_plant"], s["erp_storage_locations"], s["timezone"]) for s in pack.sites] == [
        ("DC-MIL", "warehouse", "DC-MIL", ["0001"], "Europe/Rome"), ("PLANT-GOA", "plant", "PLANT-GOA", ["0001"],
                                                                     "Europe/Rome")]
    assert pack.bins["PLANT-GOA"][1] == {"zone": "CP", "code": "CP-04", "erp_ref": "PLANT-GOA/0001/CP-04"}
    tenant = str(uuid.uuid4())
    token = create_dev_token(principal_id="site-pack-admin", tenant_id=tenant, roles=["field.admin"], site_ids=["*"])
    client = TestClient(app)
    sites: dict[str, str] = {}
    locs: dict[str, dict[str, str]] = {}
    made = create_sites("", token, tenant, pack, sites, locs, post=client.post)
    assert made == {"sites": 2, "sites_kept": 0, "zones": 5, "bins": 6}
    r = client.get(f"/v1/sites/{sites['PLANT-GOA']}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert (r.json()["erp_plant"], r.json()["erp_storage_locations"], r.json()["kind"], r.json()["mode"]) == (
        "PLANT-GOA", ["0001"], "plant", "production")
    assert set(locs[sites["PLANT-GOA"]]) == {"GR", "GR-01", "CP", "CP-04", "CP-07", "RM", "RM-07"}
    again = create_sites("", token, tenant, pack, sites, locs, post=client.post)
    assert again == {"sites": 0, "sites_kept": 2, "zones": 0, "bins": 0}
