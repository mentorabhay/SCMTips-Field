"""C3 scenario seed (M5-T06): field_api.tools.seed_c3 through the OEM port's seed capability against the real OEM
simulator (in-process ASGI, schema oemsim): the five scenarios, the label sheet, stable codes on a re-run, the first
checks reset, and the refusing real-OEM adapter."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from field_api.tools import seed_c3
from field_oem.real.adapter import RealOemAdapter
from field_oem.sim.adapter import SimOemAdapter
from oem_sim import keys
from oem_sim.app import app as oem_app
from oem_sim.routes import check_unit, reset

pytestmark = pytest.mark.unit


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimOemAdapter]:
    monkeypatch.setenv(keys.SEED_ENV, "seed-e2e-" + "abcdef0123456789" * 3)
    monkeypatch.delenv("ERPSIM_ADMIN_TOKEN", raising=False)
    reset()
    yield SimOemAdapter("http://testserver/_oem", client=lambda: TestClient(oem_app, base_url="http://testserver/_oem"))
    reset()


def _first(serial: str, checker: str) -> bool:
    out = check_unit(serial, checker, None)
    assert out is not None
    return bool(out["first_check"]["first"])


def test_m5_t06_seed_makes_every_scenario_and_the_label_sheet(port: SimOemAdapter, tmp_path: Path) -> None:
    out = io.StringIO()
    labels = tmp_path / "var" / "c3_labels.html"
    assert seed_c3.main(["--labels-out", str(labels)], out=out, port=port) == 0
    lines = out.getvalue().splitlines()
    assert [ln.split(":")[0] for ln in lines] == ["OK L1", "OK L2", "OK L3", "OK L4", "OK L5", "OK labels"]
    page = labels.read_text(encoding="utf-8")
    assert page.count('<figure class="label">') == 6 and "copy b of 2" in page and "SAMPLE" in page
    first = seed_c3.seed(port).codes
    assert _first("KSO-SAMPLE-0004", "a" * 32) is True
    again = seed_c3.seed(port).codes
    assert again == first  # printed labels stay valid
    assert _first("KSO-SAMPLE-0004", "b" * 32) is True  # the re-run reset the first check
    ks = port.keys("kestrel-sample")
    assert first["L1"].split(".")[1] == ks.keys[0].kid == first["L3"].split(".")[1]


def test_m5_t06_seed_refuses_on_a_real_maker(capsys: pytest.CaptureFixture[str]) -> None:
    assert seed_c3.main([], out=io.StringIO(), port=RealOemAdapter()) == 1
    assert "FAIL c3 seed" in capsys.readouterr().err
