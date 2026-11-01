"""The printable seal-label sheet (docs/design/M5_C3_CONTRACT.md section 6): GET /_oem/labels, and `stack c3`
writes the same page to var/c3_labels.html.

Each label is an SVG: the signed QR code and a clearly SAMPLE seal drawn here (a geometric bird mark, "KESTREL
OPTICS (SAMPLE)", "SAMPLE SEAL - NOT A REAL PRODUCT"); no real logo, brand, seller or marketplace. The scenario
caption and the expected verdict are printed *outside* the cut line, so a model looking at a taped-on label never
reads them. A unit with ``copies`` 2 (scenario L4, the cloned code) is printed twice with the same code. The
tampered label (scenario L5) is drawn with a torn seal band and a strip of tape over it, and the sheet asks for
real tape over the printed one.
"""

from __future__ import annotations

import html
from datetime import date
from types import MappingProxyType
from typing import Any

import qrcode
import qrcode.constants

from oem_sim import keys

TAMPERED = frozenset({"L5"})


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def qr_path(text: str, size: float, x0: float, y0: float) -> str:
    """The QR code of ``text`` as one SVG path of dark modules, ``size`` wide, at (x0, y0)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    cell = size / len(matrix)
    parts = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                parts.append(f"M{x0 + x * cell:.3f} {y0 + y * cell:.3f}h{cell:.3f}v{cell:.3f}h-{cell:.3f}z")
    return (f'<rect x="{x0}" y="{y0}" width="{size}" height="{size}" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="#000"/>')


BIRD = ('<g transform="translate(206 20)">'
        '<polygon points="0,22 18,4 30,14 46,0 38,20 24,26 14,36" fill="#1f3a5f"/>'
        '<polygon points="14,36 24,26 22,40" fill="#3f6e9e"/></g>')


def label_svg(code: str, serial: str, sku: str, *, tampered: bool = False) -> str:
    tamper = ""
    if tampered:
        tamper = ('<polyline points="200,160 214,168 226,158 240,170 252,159 266,169 280,158 294,168 308,160 322,170'
                  ' 336,159 348,166" fill="none" stroke="#7a1c1c" stroke-width="2"/>'
                  '<rect x="186" y="150" width="176" height="26" fill="#e9dfb4" fill-opacity="0.65"'
                  ' stroke="#b9a970" stroke-width="1" transform="rotate(-6 274 163)"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 200" width="95mm" height="53mm" role="img"'
        f' aria-label="SAMPLE seal label {_e(serial)}">'
        '<rect x="1" y="1" width="358" height="198" rx="10" fill="#fdfcf7" stroke="#1f3a5f" stroke-width="2"/>'
        + qr_path(code, 176, 12, 12) + BIRD +
        '<text x="258" y="30" font-family="Helvetica, Arial, sans-serif" font-size="13" font-weight="700"'
        ' fill="#1f3a5f">KESTREL</text>'
        '<text x="258" y="46" font-family="Helvetica, Arial, sans-serif" font-size="13" font-weight="700"'
        ' fill="#1f3a5f">OPTICS</text>'
        '<text x="206" y="70" font-family="Helvetica, Arial, sans-serif" font-size="12" font-weight="700"'
        ' fill="#b42318">(SAMPLE)</text>'
        '<text x="206" y="88" font-family="Helvetica, Arial, sans-serif" font-size="8" fill="#b42318">SAMPLE SEAL -'
        ' NOT A REAL PRODUCT</text>'
        f'<text x="206" y="108" font-family="Courier New, monospace" font-size="10" fill="#111">S/N {_e(serial)}</text>'
        f'<text x="206" y="124" font-family="Courier New, monospace" font-size="10" fill="#111">SKU {_e(sku)}</text>'
        '<rect x="196" y="140" width="156" height="44" rx="4" fill="#1f3a5f"/>'
        '<text x="274" y="160" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9"'
        ' font-weight="700" fill="#fff">TAMPER-EVIDENT SEAL</text>'
        '<text x="274" y="175" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="8"'
        ' fill="#cfe0f5">SAMPLE - do not accept if broken</text>'
        + tamper + '</svg>'
    )


EXPECT = MappingProxyType({
    "L1": "GENUINE_NEW",
    "L2": "RETURNED_REFURBISHED",
    "L3": "LIKELY_COUNTERFEIT",
    "L4": "first check GENUINE_NEW; the other copy, checked by someone else: CANNOT_VERIFY (first checked before)",
    "L5": "GENUINE_NEW with the seal flagged as tampered (send a photo)",
})


def _card(code: str, serial: str, sku: str, caption: str, expect: str, *, tampered: bool) -> str:
    return (f'<figure class="label"><div class="cut">{label_svg(code, serial, sku, tampered=tampered)}</div>'
            f'<figcaption><b>{_e(caption)}</b><br>Expected: {_e(expect)}</figcaption></figure>')


def sheet(units: list[dict[str, Any]], forgeries: list[dict[str, Any]]) -> str:
    """The whole printable page: genuine units (copies as asked), then the counterfeits, by scenario."""
    cards: list[tuple[str, str]] = []
    for u in units:
        sc = u.get("scenario")
        code = keys.seal_code(u["serial"], u["sku"], date.fromisoformat(u["sealed_at"]), u["nonce"])
        copies = int(u.get("copies") or 1)
        for i in range(copies):
            suffix = f" (copy {chr(ord('a') + i)} of {copies})" if copies > 1 else ""
            caption = f"{sc or '-'} {u.get('title') or 'Registered unit'}{suffix}"
            cards.append((str(sc or "~"), _card(code, u["serial"], u["sku"], caption,
                                                EXPECT.get(str(sc), "see /_oem/ui"), tampered=sc in TAMPERED)))
    for f in forgeries:
        sc = f.get("scenario")
        code = keys.forged_code(f["serial"], f["sku"], date.fromisoformat(f["sealed_at"]))
        caption = f"{sc or '-'} {f.get('title') or 'Counterfeit (not in the registry)'}"
        cards.append((str(sc or "~"), _card(code, f["serial"], f["sku"], caption,
                                            EXPECT.get(str(sc), "LIKELY_COUNTERFEIT"), tampered=False)))
    cards.sort(key=lambda c: c[0])
    body = "".join(c for _, c in cards) or "<p>No labels yet: run <code>stack c3</code> (or seed_c3).</p>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>C3 seal labels (SAMPLE)</title>
<style>
 body {{ font-family: Helvetica, Arial, sans-serif; margin: 12mm; color: #111; }}
 .banner {{ background: #b42318; color: #fff; padding: 6px 10px; font-weight: 700; }}
 .grid {{ display: flex; flex-wrap: wrap; gap: 8mm; margin-top: 6mm; }}
 .label {{ margin: 0; width: 97mm; break-inside: avoid; }}
 .cut {{ border: 1px dashed #888; padding: 1mm; }}
 figcaption {{ font-size: 10px; margin-top: 2mm; }}
 ol {{ font-size: 12px; }}
 @media print {{ .noprint {{ display: none; }} body {{ margin: 8mm; }} }}
</style></head><body>
<div class="banner">SAMPLE - Kestrel Optics (SAMPLE) is a fictional maker. These seals protect nothing real.</div>
<h1>C3 "Is this unit really new?" - printable seal labels</h1>
<ol class="noprint">
 <li>Print this page on plain paper at 100 % scale. Cut each label along its dashed line (leave the caption off).</li>
 <li>Tape each label onto any box at home. Use one box per label; L4 a and L4 b go on two different boxes.</li>
 <li>L5 (tampered seal): stick a strip of clear or brown tape across the dark seal band, as drawn.</li>
 <li>In the Field app say "check this box", show the QR to the glasses or the phone, then look at the seal.</li>
 <li>L4: check copy a first; then let a different person (another sign-in) check copy b.</li>
</ol>
<div class="grid">{body}</div>
</body></html>"""
