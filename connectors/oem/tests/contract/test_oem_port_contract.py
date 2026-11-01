"""OemPort contract (M5-T04): the simulator adapter against the real OEM simulator app, the test double, and the
refusing real-OEM adapter. The same assertions hold for both answering adapters."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from field_oem.ports.oem_port import OemNotConfigured, OemPort, OemUnavailable, UnitNotFound
from field_oem.real.adapter import RealOemAdapter
from field_oem.sim.adapter import SimOemAdapter, parse_keys
from field_oem_testing.memory import MemoryOem
from oem_sim import keys as sim_keys
from oem_sim.app import app as oem_app
from oem_sim.routes import UnitIn, reset, upsert_unit

SEED = "contract-seed-" + "fedcba9876543210" * 3


@pytest.fixture
def sim(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimOemAdapter]:
    monkeypatch.setenv(sim_keys.SEED_ENV, SEED)
    monkeypatch.delenv("ERPSIM_ADMIN_TOKEN", raising=False)
    reset()
    upsert_unit(UnitIn.model_validate({"serial": "KSO-C-0001", "sku": "KSO-BIN-842", "sealed_at": "2026-09-28",
                                       "events": [{"type": "manufactured", "at": "2026-09-28"},
                                                  {"type": "activated", "at": "2026-10-12", "area": "Pune"}]}))
    yield SimOemAdapter("http://testserver/_oem", client=lambda: TestClient(oem_app, base_url="http://testserver/_oem"))
    reset()


@pytest.fixture
def memory() -> MemoryOem:
    m = MemoryOem()
    m.add_unit("KSO-C-0001", events=[("manufactured", date(2026, 9, 28)), ("activated", date(2026, 10, 12))])
    return m


def _port_contract(port: OemPort) -> None:
    assert isinstance(port, OemPort)
    assert port.knows("kestrel-sample") and not port.knows("someone-else")
    ks = port.keys("kestrel-sample")
    assert ks.keys and all(len(k.public) == 32 for k in ks.keys) and ks.find(ks.keys[0].kid) is not None
    a = port.check_unit("kestrel-sample", "KSO-C-0001", "a" * 32, None)
    assert a.unit.serial == "KSO-C-0001" and a.unit.sku == "KSO-BIN-842"
    assert [e.type for e in a.unit.events] == ["manufactured", "activated"]
    assert a.unit.events[1].at == date(2026, 10, 12)
    assert a.first_check.first and a.first_check.same_checker
    b = port.check_unit("kestrel-sample", "KSO-C-0001", "b" * 32, None)
    assert not b.first_check.first and not b.first_check.same_checker and b.first_check.at == a.first_check.at
    with pytest.raises(UnitNotFound):
        port.check_unit("kestrel-sample", "KSO-C-9999", "a" * 32, None)


def test_m5_t04_sim_adapter_meets_the_port_contract(sim: SimOemAdapter) -> None:
    _port_contract(sim)
    assert sim.check_unit("kestrel-sample", "KSO-C-0001", "c" * 32, None).unit.events[1].area == "Pune"


def test_m5_t04_memory_double_meets_the_port_contract(memory: MemoryOem) -> None:
    _port_contract(memory)


def test_m5_t04_sim_adapter_caches_keys_and_refresh_forces_a_fetch(sim: SimOemAdapter) -> None:
    now = [0.0]
    sim._clock = lambda: now[0]
    sim.keys_ttl = 300
    first = sim.keys("kestrel-sample")
    sim.keys("kestrel-sample")
    assert sim.fetches == 1
    sim.keys("kestrel-sample", refresh=True)
    assert sim.fetches == 2
    now[0] = 301.0
    assert sim.keys("kestrel-sample") == first and sim.fetches == 3


def test_m5_t04_sim_adapter_maps_failures_to_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down = SimOemAdapter("http://oem.invalid", client=lambda: httpx.Client(
        transport=httpx.MockTransport(refuse), base_url="http://oem.invalid"))
    with pytest.raises(OemUnavailable):
        down.keys("kestrel-sample")
    with pytest.raises(OemUnavailable):
        down.check_unit("kestrel-sample", "KSO-C-0001", "a" * 32, None)

    def bad(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("oem-keys"):
            return httpx.Response(200, json={"keys": [{"kty": "RSA"}]})
        return httpx.Response(200, json={"unit": {"serial": "x"}})

    odd = SimOemAdapter("http://oem.invalid", client=lambda: httpx.Client(
        transport=httpx.MockTransport(bad), base_url="http://oem.invalid"))
    with pytest.raises(OemUnavailable):
        odd.keys("kestrel-sample")
    with pytest.raises(OemUnavailable):
        odd.check_unit("kestrel-sample", "KSO-C-0001", "a" * 32, None)
    refused = SimOemAdapter("http://oem.invalid", client=lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"code": "OEMSIM-401-ADMIN"}})),
        base_url="http://oem.invalid"))
    with pytest.raises(OemUnavailable):  # a refused token is the maker not answering, never "unknown unit"
        refused.check_unit("kestrel-sample", "KSO-C-0001", "a" * 32, None)


def test_m5_t04_parse_keys_drops_malformed_keys() -> None:
    good = {"kty": "OKP", "crv": "Ed25519", "kid": "0123456789abcdef", "x": "A" * 43}
    ks = parse_keys({"oem": "kestrel-sample", "keys": [good, {**good, "kid": "BAD"}, {**good, "x": "!!"}]})
    assert [k.kid for k in ks.keys] == ["0123456789abcdef"]


def test_m5_t04_real_oem_adapter_refuses_honestly() -> None:
    real = RealOemAdapter()
    assert isinstance(real, OemPort) and real.knows("any-maker")
    with pytest.raises(OemNotConfigured):
        real.keys("any-maker")
    with pytest.raises(OemNotConfigured):
        real.check_unit("any-maker", "X-0001", "a" * 32, None)
