"""The OEM simulator's pages: GET /_oem/ui (units and their history, read only) and GET /_oem/labels (the printable
label sheet, oem_sim.labels). Both are SAMPLE data of a fictional maker and change nothing."""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from oem_sim import keys, labels
from oem_sim.routes import all_forgeries, all_units

router = APIRouter(prefix="/_oem", tags=["OEM simulator (M5 C3)"])
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"}


def _e(v: Any) -> str:
    return "-" if v is None else html.escape(str(v), quote=True)


def ui_page(units: list[dict[str, Any]], forgeries: list[dict[str, Any]], kid: str | None) -> str:
    rows = []
    for u in units:
        hist = "<br>".join(f"{_e(ev['at'])} {_e(ev['type'])}{' (' + _e(ev['area']) + ')' if ev['area'] else ''}"
                           for ev in u["events"]) or "-"
        fc = u.get("first_check")
        first = f"{_e(fc['at'])}{' (' + _e(fc['area']) + ')' if fc and fc['area'] else ''}" if fc else "not yet"
        rows.append(f"<tr><td>{_e(u['scenario'])}</td><td><code>{_e(u['serial'])}</code></td><td>{_e(u['sku'])}</td>"
                    f"<td>{_e(u['sealed_at'])}</td><td>{hist}</td><td>{first}</td><td>{_e(u['title'])}</td></tr>")
    forged = "".join(f"<tr><td>{_e(f['scenario'])}</td><td><code>{_e(f['serial'])}</code></td><td>{_e(f['sku'])}</td>"
                     f"<td>{_e(f['title'])}</td></tr>" for f in forgeries)
    key = f"key id <code>{_e(kid)}</code>" if kid else f"<b>no signing key</b> (set {keys.SEED_ENV})"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>OEM simulator (SAMPLE)</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#0b0f19;color:#e2e8f0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #23314f;padding:8px;
text-align:left;vertical-align:top}}th{{color:#94a3b8;font-size:11px;text-transform:uppercase}}
.banner{{background:#b42318;color:#fff;padding:6px 10px;font-weight:700;margin-bottom:16px}}a{{color:#38bdf8}}</style>
</head><body><div class="banner">SAMPLE - {_e(keys.OEM_NAME)} is a fictional maker (OEM simulator, M5 case C3)</div>
<h1>OEM registry</h1><p>{key} &middot; public keys: <a href="/_oem/.well-known/oem-keys">/_oem/.well-known/oem-keys</a>
&middot; printable labels: <a href="/_oem/labels">/_oem/labels</a></p>
<h2>Units ({len(units)})</h2><table><tr><th>Scenario</th><th>Serial</th><th>SKU</th><th>Sealed</th><th>History</th>
<th>First check</th><th>Title</th></tr>{''.join(rows) or '<tr><td colspan="7">No units: run stack c3.</td></tr>'}</table>
<h2>Counterfeit labels (not in the registry) ({len(forgeries)})</h2><table><tr><th>Scenario</th><th>Serial</th>
<th>SKU</th><th>Title</th></tr>{forged or '<tr><td colspan="4">None.</td></tr>'}</table></body></html>"""


@router.get("/ui", response_class=HTMLResponse)
def get_ui() -> HTMLResponse:
    try:
        kid: str | None = keys.kid_of(keys.public_raw(keys.signing_key()))
    except keys.NoSigningKey:
        kid = None
    return HTMLResponse(ui_page(all_units(), all_forgeries(), kid), headers=HEADERS)


@router.get("/labels", response_class=HTMLResponse)
def get_labels() -> HTMLResponse:
    try:
        page = labels.sheet(all_units(), all_forgeries())
    except keys.NoSigningKey:
        return HTMLResponse(f"<!DOCTYPE html><p>The OEM simulator has no signing key: set {keys.SEED_ENV}.</p>",
                            status_code=503, headers=HEADERS)
    return HTMLResponse(page, headers=HEADERS)
