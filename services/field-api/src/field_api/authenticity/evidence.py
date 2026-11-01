"""The evidence pack and page of a C3 check (docs/design/M5_C3_CONTRACT.md section 4.3).

Pack: the check as GET answers it (signals, verdict, the rule that matched, reasons, say, models), the code text, the
claim made from it (if any) and ``hashes``: ``photo_sha256`` as the crop store recorded it, with
``photo_sha256_verified`` (the stored bytes still hash to it), and ``pack_sha256`` over the canonical JSON of the
pack without itself (evidence.pack.pack_sha256, as for M5 document packs). Page: one self-contained HTML document
(SAMPLE banner, verdict, rule, signals, the history timeline, the photo with the seal box drawn as SVG over it,
hashes), same headers and CSP as the M5 evidence page; every value HTML-escaped; no token, key or link back.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any

from field_api.auth.jwt import Principal
from field_api.authenticity import service
from field_api.claims.service import COLS as CLAIM_COLS
from field_api.claims.service import view as claim_view
from field_api.crops import CropStoreError, crop_store
from field_api.db import principal_tx
from field_api.evidence.pack import pack_sha256, plain
from field_api.evidence.page import CSS, FLAGGED, GOOD, outlines_svg

_CLAIM_NAMES = tuple(c.strip() for c in CLAIM_COLS.split(","))
RULES_NOTE = ("authenticity.rules R1-R14 (deterministic: signature, the maker's registry and the first check; the "
              "visual seal check only sets tamper)")


@dataclass(frozen=True)
class CheckPack:
    body: dict[str, Any]
    photo: bytes | None


def _photo(cur: Any, capture_id: str | None) -> tuple[dict[str, Any], bytes | None]:
    none = {"photo_sha256": None, "photo_sha256_verified": False, "photo": "none"}
    if not capture_id:
        return none, None
    cur.execute("SELECT crop_s3_uri, sha256_hash, retention_until, is_legal_hold FROM field.capture_evidence"
                " WHERE capture_id = %s::uuid ORDER BY created_at DESC LIMIT 1", (capture_id,))
    r = cur.fetchone()
    if r is None:
        return none, None
    uri, sha, until, hold = r
    if datetime.now(UTC) > until and not hold:
        return {"photo_sha256": sha, "photo_sha256_verified": False, "photo": "deleted_by_retention"}, None
    try:
        data = crop_store().get(uri)
    except (CropStoreError, OSError):
        return {"photo_sha256": sha, "photo_sha256_verified": False, "photo": "missing"}, None
    ok = hashlib.sha256(data).hexdigest() == str(sha).lower()
    return {"photo_sha256": sha, "photo_sha256_verified": ok, "photo": "stored"}, data if ok else None


def build_check_pack(principal: Principal, check_id: str) -> CheckPack:
    check = service.get_check(principal, check_id)
    with principal_tx(principal) as cur:
        cur.execute("SELECT code FROM field.authenticity_check WHERE id = %s::uuid", (check["check_id"],))
        code_row = cur.fetchone()
        cur.execute(f"SELECT {CLAIM_COLS} FROM field.supplier_claim WHERE check_id = %s::uuid", (check["check_id"],))
        cr = cur.fetchone()
        claim = claim_view(dict(zip(_CLAIM_NAMES, cr, strict=True)), None) if cr else None
        hashes, photo = _photo(cur, check.get("capture_id"))
    check_body = {k: v for k, v in check.items() if k != "evidence_url"}
    body: dict[str, Any] = plain({
        "kind": "scmtips-field.authenticity-evidence", "version": 1, "sample": True,
        "note": "SAMPLE: the maker is a simulator (Kestrel Optics (SAMPLE)); see M5_C3_CONTRACT.md section 9.",
        "check": check_body, "rule": check.get("rule"), "rules": RULES_NOTE,
        "code": code_row[0] if code_row else None, "claim": claim, "hashes": hashes,
    })
    body["hashes"]["pack_sha256"] = pack_sha256(body)
    return CheckPack(body, photo)


def _e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


def _rows(pairs: list[tuple[str, Any]]) -> str:
    return "<dl>" + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in pairs) + "</dl>"


def render_check(pack: dict[str, Any], photo: bytes | None) -> str:
    check = pack.get("check") or {}
    sig = check.get("signals") or {}
    code, reg, first, vis = (sig.get("code") or {}, sig.get("registry") or {}, sig.get("first_check") or {},
                             sig.get("visual") or {})
    tamper = check.get("tamper")
    events = "".join(f"<tr><td>{_e(ev.get('at'))}</td><td>{_e(ev.get('type'))}</td><td>{_e(ev.get('area'))}</td></tr>"
                     for ev in reg.get("events") or [] if isinstance(ev, dict))
    timeline = (f"<table><caption>Unit history (the maker's registry)</caption><thead><tr><th scope=\"col\">Day</th>"
                f"<th scope=\"col\">Event</th><th scope=\"col\">Area</th></tr></thead><tbody>{events}</tbody></table>"
                if events else "<p>No history from the maker.</p>")
    photo_html = "<p>No photo was sent with this check.</p>"
    if photo is not None:
        image = vis.get("image") or {}
        box = vis.get("box")
        look = {"image": image, "instances": [{"n": 1, "box": box}] if isinstance(box, list) else []}
        alt = ("Photo of the seal" + (", outlined" if box else "") + (", flagged as tampered" if tamper else "") + ".")
        data = base64.b64encode(photo).decode("ascii")
        photo_html = (f'<figure><div class="photo"><img src="data:image/jpeg;base64,{data}" alt="{_e(alt)}">'
                      f"{outlines_svg(look, {1} if tamper else set())}</div><figcaption>{_e(alt)} Outline: "
                      f'<span class="{"flagged" if tamper else "good"}">'
                      f'{"red = seal flagged" if tamper else "green = seal"}</span>.</figcaption></figure>')
    elif (pack.get("hashes") or {}).get("photo") not in (None, "none"):
        photo_html = f"<p>The photo is not available here ({_e((pack.get('hashes') or {}).get('photo'))}).</p>"
    models = "".join(f"<tr><td>{_e(m.get('model'))}</td><td>{_e(m.get('purpose'))}</td><td>{_e(m.get('latency_ms'))}"
                     f"</td><td>{_e(m.get('cost_usd'))}</td><td>{_e(m.get('outcome'))}</td></tr>"
                     for m in check.get("models") or [] if isinstance(m, dict))
    claim = pack.get("claim")
    claim_html = (_rows([("Claim", claim.get("claim_id")), ("Status", claim.get("status")), ("Text", claim.get("text")),
                         ("Lines", "; ".join(f"{ln.get('units')} {ln.get('reason')}" for ln in claim.get("lines") or []))])
                  if isinstance(claim, dict) else "<p>No claim was made from this check.</p>")
    hashes = pack.get("hashes") or {}
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authenticity check {_e(check.get('check_id'))}</title><style>{CSS}
.verdict {{ font-size: 1.4rem; font-weight: 700; }}</style></head><body>
<div class="sample">SAMPLE - case C3. The maker Kestrel Optics (SAMPLE) is a simulator; this page proves nothing about a
real product.</div><main>
<h1>Authenticity check</h1>
<p class="verdict">{_e(check.get('verdict'))}{' - seal flagged as tampered' if tamper else ''}</p>
<p>{_e(check.get('say'))}</p>
{_rows([("Rule", f"{pack.get('rule')} ({pack.get('rules')})"), ("Reasons", ", ".join(check.get("reasons") or []) or "-"),
        ("Checked", check.get("created_at")), ("Final", check.get("final"))])}
<h2>Seal code (signal 1)</h2>
{_rows([("Status", code.get("status")), ("Maker", code.get("oem_name") or code.get("oem")), ("Key id", code.get("kid")),
        ("Serial", code.get("serial")), ("SKU", code.get("sku")), ("Sealed", code.get("sealed_at"))])}
<h2>Unit history (signal 2)</h2>
<p>Registry: {_e(reg.get('status'))}</p>{timeline}
<h2>First check (signal 3)</h2>
{_rows([("Status", first.get("status")), ("First checked", first.get("first_checked_at")), ("Area", first.get("area"))])}
<h2>Seal photo (signal 4, supporting only)</h2>
<p>Visual check: {_e(vis.get('status'))}; signs: {_e(', '.join(vis.get('signs') or []) or 'none')};
tamper: <span style="color:{FLAGGED if tamper else GOOD}">{_e(tamper)}</span></p>
{photo_html}
<h2>Model calls</h2>
{f'<table><thead><tr><th scope="col">Model</th><th scope="col">Purpose</th><th scope="col">Latency ms</th><th scope="col">Cost USD</th><th scope="col">Outcome</th></tr></thead><tbody>{models}</tbody></table>' if models else '<p>No model was called.</p>'}
<h2>Claim</h2>{claim_html}
<h2>Hashes</h2>
{_rows([("Photo sha256", hashes.get("photo_sha256")), ("Photo verified", hashes.get("photo_sha256_verified")),
        ("Pack sha256", hashes.get("pack_sha256"))])}
</main></body></html>"""
