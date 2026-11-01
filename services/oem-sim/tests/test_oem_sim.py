"""OEM simulator (M5-T02, M5-T03): keys, registry, the atomic first-check claim, admin routes, pages, the erp-sim mount.

Runs on the real simulator database (schema oemsim, ERPSIM_DATABASE_URL / OEMSIM_DATABASE_URL).
"""

from __future__ import annotations

import base64
import json
import re
import threading
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from erp_sim.app import app as erp_app
from fastapi.testclient import TestClient
from oem_sim import keys, labels
from oem_sim.app import app
from oem_sim.routes import UnitIn, check_unit, reset, upsert_unit

ADMIN = {"X-Sim-Admin-Token": "dev-sim-admin-token"}
SEED = "test-seed-" + "0123456789abcdef" * 3


@pytest.fixture(autouse=True)
def _seed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(keys.SEED_ENV, SEED)
    monkeypatch.delenv("ERPSIM_ADMIN_TOKEN", raising=False)
    reset()
    yield
    reset()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _verify(code: str, jwks: dict[str, Any]) -> dict[str, Any]:
    prefix, kid, payload, sig = code.split(".")
    assert prefix == "SEAL1"
    key = next(k for k in jwks["keys"] if k["kid"] == kid)
    Ed25519PublicKey.from_public_bytes(_unb64(key["x"])).verify(_unb64(sig), keys.SIGN_DOMAIN + _unb64(payload))
    body = json.loads(_unb64(payload))
    assert _unb64(payload) == json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return dict(body)


def _unit(serial: str = "KSO-T-0001", **kw: object) -> dict[str, object]:
    base: dict[str, object] = {"serial": serial, "sku": "KSO-BIN-842", "sealed_at": "2026-09-28",
                               "events": [{"type": "manufactured", "at": "2026-09-28"},
                                          {"type": "shipped_to_seller", "at": "2026-10-02"}]}
    return {**base, **kw}


def test_m5_t02_keys_need_the_seed_and_publish_one_ed25519_key(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TestClient(app)
    ks = c.get("/_oem/.well-known/oem-keys").json()
    assert ks["oem"] == "kestrel-sample" and ks["sample"] is True and "(SAMPLE)" in ks["name"]
    (k,) = ks["keys"]
    assert k["kty"] == "OKP" and k["crv"] == "Ed25519" and re.fullmatch(r"[0-9a-f]{16}", k["kid"])
    assert len(_unb64(k["x"])) == 32
    monkeypatch.setenv(keys.SEED_ENV, "short")
    r = c.get("/_oem/.well-known/oem-keys")
    assert r.status_code == 503 and r.json()["error"]["code"] == "OEMSIM-503-NO-KEY"
    assert c.post("/_oem/admin/units", json=_unit(), headers=ADMIN).status_code == 503


def test_m5_t02_admin_unit_returns_a_signed_code_that_stays_valid_when_seeded_again() -> None:
    c = TestClient(app)
    assert c.post("/_oem/admin/units", json=_unit()).status_code == 401
    r = c.post("/_oem/admin/units", json=_unit(), headers=ADMIN)
    assert r.status_code == 201
    code = r.json()["code"]
    payload = _verify(code, c.get("/_oem/.well-known/oem-keys").json())
    assert payload == {"v": 1, "oem": "kestrel-sample", "serial": "KSO-T-0001", "sku": "KSO-BIN-842",
                       "sealed_at": "2026-09-28", "nonce": payload["nonce"]}
    again = c.post("/_oem/admin/units", json=_unit(events=[]), headers=ADMIN)
    assert again.status_code == 200 and again.json()["code"] == code  # the printed label stays valid
    assert again.json()["events"] == []  # events are replaced


def test_m5_t02_a_tampered_code_fails_the_signature() -> None:
    c = TestClient(app)
    code = c.post("/_oem/admin/units", json=_unit(), headers=ADMIN).json()["code"]
    prefix, kid, payload, sig = code.split(".")
    body = json.loads(_unb64(payload))
    body["serial"] = "KSO-T-0002"
    forged_payload = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    forged = f"{prefix}.{kid}.{forged_payload.rstrip(b'=').decode()}.{sig}"
    with pytest.raises(InvalidSignature):
        _verify(forged, c.get("/_oem/.well-known/oem-keys").json())


def test_m5_t02_first_check_first_then_same_then_other_checker() -> None:
    c = TestClient(app)
    c.post("/_oem/admin/units", json=_unit(), headers=ADMIN)
    a, b = "a" * 32, "b" * 32
    assert c.post("/_oem/v1/units/KSO-T-0001/checks", json={"checker": a}).status_code == 401
    first = c.post("/_oem/v1/units/KSO-T-0001/checks", json={"checker": a, "area": "Pune"}, headers=ADMIN).json()
    assert first["first_check"]["first"] is True and first["first_check"]["same_checker"] is True
    assert first["first_check"]["area"] == "Pune"
    assert [e["type"] for e in first["unit"]["events"]] == ["manufactured", "shipped_to_seller"]
    same = c.post("/_oem/v1/units/KSO-T-0001/checks", json={"checker": a}, headers=ADMIN).json()["first_check"]
    assert same["first"] is False and same["same_checker"] is True and same["at"] == first["first_check"]["at"]
    other = c.post("/_oem/v1/units/KSO-T-0001/checks", json={"checker": b}, headers=ADMIN).json()["first_check"]
    assert other["first"] is False and other["same_checker"] is False and other["area"] == "Pune"
    r = c.post("/_oem/v1/units/KSO-NOPE-0001/checks", json={"checker": a}, headers=ADMIN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "OEMSIM-404-UNIT"
    bad = c.post("/_oem/v1/units/KSO-T-0001/checks", json={"checker": a, "area": "18.52,73.85"}, headers=ADMIN)
    assert bad.status_code == 422  # coordinates are refused: city level at most
    assert c.get("/_oem/v1/units/KSO-T-0001", headers=ADMIN).json()["first_check"]["area"] == "Pune"


def test_m5_t07_first_check_race_one_of_many_concurrent_checks_wins() -> None:
    upsert_unit(UnitIn.model_validate(_unit()))
    checkers = [f"{i:032x}" for i in range(8)]
    results: list[bool] = []
    barrier = threading.Barrier(len(checkers))

    def go(ch: str) -> None:
        barrier.wait()
        out = check_unit("KSO-T-0001", ch, None)
        assert out is not None
        results.append(bool(out["first_check"]["first"]))

    threads = [threading.Thread(target=go, args=(ch,)) for ch in checkers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]


def test_m5_t02_forgery_is_never_a_registered_unit_and_reset_clears_everything() -> None:
    c = TestClient(app)
    c.post("/_oem/admin/units", json=_unit(), headers=ADMIN)
    r = c.post("/_oem/admin/forgeries", json={"serial": "KSO-T-0001", "sku": "KSO-BIN-842",
                                               "sealed_at": "2026-09-28"}, headers=ADMIN)
    assert r.status_code == 409
    f = c.post("/_oem/admin/forgeries", json={"serial": "KSO-T-0003", "sku": "KSO-BIN-842",
                                               "sealed_at": "2026-09-28", "scenario": "L3"}, headers=ADMIN)
    assert f.status_code == 201 and f.json()["in_registry"] is False
    with pytest.raises(InvalidSignature):
        _verify(f.json()["code"], c.get("/_oem/.well-known/oem-keys").json())
    assert c.post("/_oem/admin/reset", headers=ADMIN).json() == {"status": "reset_completed"}
    assert c.get("/_oem/v1/units/KSO-T-0001", headers=ADMIN).status_code == 404


def test_m5_t03_label_sheet_prints_every_scenario_and_the_clone_twice() -> None:
    c = TestClient(app)
    for sc, serial, copies in (("L1", "KSO-T-0001", 1), ("L4", "KSO-T-0004", 2), ("L5", "KSO-T-0005", 1)):
        c.post("/_oem/admin/units", json=_unit(serial, scenario=sc, title=f"title {sc}", copies=copies), headers=ADMIN)
    c.post("/_oem/admin/forgeries", json={"serial": "KSO-T-0003", "sku": "KSO-BIN-842", "sealed_at": "2026-09-28",
                                          "scenario": "L3", "title": "Counterfeit"}, headers=ADMIN)
    r = c.get("/_oem/labels")
    assert r.status_code == 200 and "SAMPLE" in r.text and "KESTREL" in r.text
    page = r.text
    assert page.count('<figure class="label">') == 5  # L1, L3, L4 a, L4 b, L5
    assert "copy a of 2" in page and "copy b of 2" in page
    assert page.index("L1 title") < page.index("L3 Counterfeit") < page.index("L4 title") < page.index("L5 title")
    assert page.count("rotate(-6 274 163)") == 1  # the tape strip is drawn on the tampered label only
    clone = c.post("/_oem/admin/units", json=_unit("KSO-T-0004", scenario="L4", copies=2), headers=ADMIN).json()
    assert page.count(f"S/N {clone['serial']}") == 2


def test_m5_t03_qr_path_draws_only_dark_modules_of_the_code() -> None:
    svg = labels.label_svg("SEAL1.x.y.z", "KSO-T-0001", "KSO-BIN-842")
    assert svg.startswith("<svg") and svg.endswith("</svg>") and svg.count("<path") == 1
    assert "KSO-T-0001" in svg and "NOT A REAL PRODUCT" in svg
    assert "&lt;script" in labels.label_svg("c", "<script>", "s")


def test_m5_t02_admin_page_lists_units_and_erp_sim_mounts_the_oem_routes() -> None:
    TestClient(app).post("/_oem/admin/units", json=_unit(scenario="L1", title="Genuine new"), headers=ADMIN)
    c = TestClient(erp_app)
    assert c.get("/_oem/health").json()["service"] == "oem-sim"
    ui = c.get("/_oem/ui")
    assert ui.status_code == 200 and "KSO-T-0001" in ui.text and "shipped_to_seller" in ui.text
    assert "not yet" in ui.text
    assert c.get("/_oem/.well-known/oem-keys").status_code == 200


def test_m5_t02_nonce_is_stable_per_serial_and_differs_between_serials() -> None:
    assert keys.nonce_for("KSO-T-0001") == keys.nonce_for("KSO-T-0001") != keys.nonce_for("KSO-T-0002")
    a = keys.seal_code("KSO-T-0001", "KSO-BIN-842", date(2026, 9, 28), keys.nonce_for("KSO-T-0001"))
    b = keys.forged_code("KSO-T-0001", "KSO-BIN-842", date(2026, 9, 28))
    assert a.split(".")[:3] == b.split(".")[:3] and a != b  # same kid and payload, a different signature
