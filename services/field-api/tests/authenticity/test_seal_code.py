"""Seal code verification and forgery (M5-T04, M5-T07): docs/design/M5_C3_CONTRACT.md section 2.1."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from field_api.authenticity import seal_code
from field_oem.ports.oem_port import OemKey, OemKeySet, UnitCheck
from field_oem_testing.memory import MemoryOem, canonical_payload, encode, kid_of, raw_public
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_m5_t04_valid_code_verifies_and_reports_its_fields() -> None:
    oem = MemoryOem()
    code = oem.add_unit("KSO-T-0001", sku="KSO-BIN-842", sealed_at=date(2026, 9, 28))
    r = seal_code.verify(code, oem)
    assert r.status == "valid" and r.serial == "KSO-T-0001" and r.sku == "KSO-BIN-842"
    assert r.sealed_at == "2026-09-28" and r.oem == "kestrel-sample" and r.kid == oem.kid
    assert r.oem_name == "Kestrel Optics (SAMPLE)"
    assert seal_code.verify("  " + code + "\n", oem).status == "valid"  # a scanner's whitespace


def test_m5_t04_forgeries_fail_the_signature() -> None:
    oem = MemoryOem()
    code = oem.add_unit("KSO-T-0001")
    prefix, kid, payload, sig = code.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["serial"] = "KSO-T-0002"  # the payload changed, the signature kept
    changed = b64(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    assert seal_code.verify(f"{prefix}.{kid}.{changed}.{sig}", oem).status == "bad_signature"
    assert seal_code.verify(oem.forged("KSO-T-0009"), oem).status == "bad_signature"
    other = Ed25519PrivateKey.generate()
    assert seal_code.verify(encode(canonical_payload("kestrel-sample", "KSO-T-1", "KSO-B", date(2026, 1, 1),
                                                     "0" * 16), other, kid_of(other)), oem).status == "unknown_key"


def test_m5_t04_signed_but_not_canonical_or_bad_fields_is_bad_payload() -> None:
    oem = MemoryOem()
    loose = json.dumps({"v": 1, "oem": "kestrel-sample", "serial": "KSO-T-1", "sku": "KSO-B", "sealed_at": "2026-09-28",
                        "nonce": "0" * 16}).encode()  # keys unsorted, with spaces
    assert seal_code.verify(encode(loose, oem.key, oem.kid), oem).status == "bad_payload"
    bad_date = canonical_payload("kestrel-sample", "KSO-T-1", "KSO-B", date(2026, 1, 1), "0" * 16).replace(
        b"2026-01-01", b"2026-13-01")
    assert seal_code.verify(encode(bad_date, oem.key, oem.kid), oem).status == "bad_payload"
    extra = json.dumps({"nonce": "0" * 16, "oem": "kestrel-sample", "serial": "KSO-T-1", "sealed_at": "2026-01-01",
                        "sku": "KSO-B", "v": 1, "x": 1}, sort_keys=True, separators=(",", ":")).encode()
    assert seal_code.verify(encode(extra, oem.key, oem.kid), oem).status == "bad_payload"


def test_m5_t04_not_a_seal_code_and_unknown_maker() -> None:
    oem = MemoryOem()
    code = oem.add_unit("KSO-T-0001")
    prefix, kid, payload, sig = code.split(".")
    for junk in ("", "hello", "SEAL2." + code[6:], f"{prefix}.{kid}.{payload}", f"{prefix}.XYZ.{payload}.{sig}",
                 f"{prefix}.{kid}.{payload}.{sig[:-4]}", f"{prefix}.{kid}.%%%.{sig}", "x" * 2000,
                 f"{prefix}.{kid}.{b64(b'[1,2]')}.{sig}"):
        assert seal_code.verify(junk, oem).status == "not_a_seal_code", junk[:40]
    elsewhere = canonical_payload("other-maker", "KSO-T-1", "KSO-B", date(2026, 1, 1), "0" * 16)
    r = seal_code.verify(encode(elsewhere, oem.key, oem.kid), oem)
    assert r.status == "unknown_oem" and r.oem == "other-maker"


@dataclass
class RotatingPort:
    """Answers the old key set first and the new one only on refresh (a key rotation the cache has not seen)."""

    old: OemKeySet
    new: OemKeySet
    refreshes: list[bool] = field(default_factory=list)

    def knows(self, oem: str) -> bool:
        return oem == "kestrel-sample"

    def keys(self, oem: str, *, refresh: bool = False) -> OemKeySet:
        self.refreshes.append(refresh)
        return self.new if refresh else self.old

    def check_unit(self, oem: str, serial: str, checker: str, area: str | None) -> UnitCheck:
        raise AssertionError("not used")


def test_m5_t04_an_unknown_kid_refetches_once_for_key_rotation() -> None:
    old, new = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    def ks(*keys: Ed25519PrivateKey) -> OemKeySet:
        return OemKeySet("kestrel-sample", "K", tuple(OemKey(kid_of(k), raw_public(k)) for k in keys))

    port = RotatingPort(ks(old), ks(old, new))
    code = encode(canonical_payload("kestrel-sample", "KSO-T-1", "KSO-B", date(2026, 1, 1), "0" * 16), new,
                  kid_of(new))
    assert seal_code.verify(code, port).status == "valid"
    assert port.refreshes == [False, True]


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pos=st.integers(min_value=0, max_value=10_000), ch=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh0123_-."))
def test_m5_t07_property_any_one_character_change_of_a_code_never_verifies(pos: int, ch: str) -> None:
    """M5-T07: a forgery by editing one character of a genuine code is never ``valid``."""
    oem = MemoryOem()
    code = oem.add_unit("KSO-T-0001")
    i = pos % len(code)
    forged = code[:i] + ch + code[i + 1:]
    status = seal_code.verify(forged, oem).status
    if forged == code:
        assert status == "valid"
    else:
        # base64url's last character can carry unused bits: such an edit decodes to the same bytes
        same = seal_code.parse(forged) == seal_code.parse(code) and seal_code.parse(code) is not None
        assert status == "valid" if same else status != "valid"
