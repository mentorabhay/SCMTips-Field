"""The evidence page (M5 contract section 3): one self-contained HTML document of an evidence pack.

No external asset of any kind (no script, font, stylesheet or image URL): the CSS is inline, the photo is embedded
as a ``data:image/jpeg`` URI and the outlines are an inline SVG over it, in the image's own pixel coordinates
(``viewBox = 0 0 width height``), numbered, green for good and red for flagged (with the words "good" / "flagged"
in the list beside it, so colour is never the only signal). Sections: SAMPLE banner, document and movements, photo,
deterministic check, model calls, confirm, claim, hashes. Every value is HTML-escaped; the page holds no token,
key or link back to the API. Contrast: text #1a1a1a on #ffffff (17:1), the banner #1a1a1a on #ffd54f (12:1), the
outline colours #1b7a3a and #b3261e on white (5.4:1 and 6.5:1).
"""

from __future__ import annotations

import base64
from html import escape
from typing import Any

GOOD, FLAGGED = "#1b7a3a", "#b3261e"

CSS = """
:root { color-scheme: light; }
body { font: 16px/1.5 system-ui, sans-serif; color: #1a1a1a; background: #fff;
       margin: 0; }
main { max-width: 960px; margin: 0 auto; padding: 0 16px 48px; }
.sample { background: #ffd54f; color: #1a1a1a; font-weight: 700; padding: 12px 16px; border-bottom: 3px solid #1a1a1a; }
h1 { font-size: 1.6rem; margin: 24px 0 8px; }
h2 { font-size: 1.25rem; margin: 28px 0 8px; border-bottom: 1px solid #767676; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
caption { text-align: left; font-weight: 600; padding: 4px 0; }
th, td { border: 1px solid #767676; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f0f0f0; }
figure { margin: 8px 0; }
.photo { position: relative; display: inline-block; max-width: 100%; }
.photo img, .photo svg { display: block; width: 100%; height: auto; }
.photo svg { position: absolute; inset: 0; height: 100%; }
code, .hash { font-family: ui-monospace, Menlo, Consolas, monospace; word-break: break-all; }
.good { color: #1b7a3a; font-weight: 600; }
.flagged { color: #b3261e; font-weight: 600; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; }
dt { font-weight: 600; }
dd { margin: 0; }
"""


def _e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _table(caption: str, head: list[str], rows: list[list[Any]], empty: str) -> str:
    if not rows:
        return f"<p>{_e(empty)}</p>"
    th = "".join(f'<th scope="col">{_e(h)}</th>' for h in head)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><caption>{_e(caption)}</caption><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _dl(pairs: list[tuple[str, Any]]) -> str:
    return "<dl>" + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in pairs) + "</dl>"


def _flagged_ns(pack: dict[str, Any]) -> set[int]:
    check = pack.get("check") or {}
    out: set[int] = set()
    for f in check.get("flagged") or []:
        n = _num(f.get("n")) if isinstance(f, dict) else None
        if n is not None:
            out.add(int(n))
    return out


def outlines_svg(look: dict[str, Any], flagged: set[int]) -> str:
    """The numbered outlines as an SVG in the image's pixel space (empty string when the size is unknown)."""
    image = look.get("image") or {}
    w, h = _num(image.get("width")), _num(image.get("height"))
    if not w or not h or w <= 0 or h <= 0:
        return ""
    shapes: list[str] = []
    stroke = max(2.0, round(min(w, h) / 300, 1))
    font = max(14.0, round(min(w, h) / 30, 1))
    for inst in look.get("instances") or []:
        if not isinstance(inst, dict):
            continue
        n = _num(inst.get("n"))
        box = inst.get("box")
        if n is None or not isinstance(box, list) or len(box) != 4:
            continue
        coords = [_num(c) for c in box]
        if any(c is None for c in coords):
            continue
        x0, y0, x1, y1 = (float(c) for c in coords if c is not None)
        colour = FLAGGED if int(n) in flagged else GOOD
        poly = inst.get("polygon")
        pts = []
        if isinstance(poly, list):
            for p in poly:
                if isinstance(p, list) and len(p) == 2 and _num(p[0]) is not None and _num(p[1]) is not None:
                    pts.append(f"{_num(p[0]):g},{_num(p[1]):g}")
        if len(pts) >= 3:
            shapes.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="{colour}" '
                          f'stroke-width="{stroke:g}"/>')
        else:
            shapes.append(f'<rect x="{x0:g}" y="{y0:g}" width="{max(0.0, x1 - x0):g}" height="{max(0.0, y1 - y0):g}" '
                          f'fill="none" stroke="{colour}" stroke-width="{stroke:g}"/>')
        shapes.append(f'<rect x="{x0:g}" y="{y0:g}" width="{font * 1.6:g}" height="{font * 1.3:g}" fill="{colour}"/>'
                      f'<text x="{x0 + font * 0.3:g}" y="{y0 + font:g}" font-size="{font:g}" fill="#ffffff" '
                      f'font-family="sans-serif" font-weight="700">{int(n)}</text>')
    return (f'<svg viewBox="0 0 {w:g} {h:g}" preserveAspectRatio="none" aria-hidden="true" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(shapes)}</svg>')


def _photo_section(pack: dict[str, Any], photo: bytes | None) -> str:
    look = pack.get("look")
    if not isinstance(look, dict):
        return "<p>No look is linked to this document.</p>"
    flagged = _flagged_ns(pack)
    instances = [i for i in look.get("instances") or [] if isinstance(i, dict)]
    rows = []
    for inst in instances:
        n = inst.get("n")
        state = "flagged" if _num(n) is not None and int(_num(n) or 0) in flagged else "good"
        label = inst.get("label") or {}
        rows.append(f'<li><span class="{state}">{_e(n)}: {state}</span>'
                    + (f" (damage: {_e(inst.get('damage_note'))})" if inst.get("damage_note") else "")
                    + (f", pieces {_e(label.get('pieces_per_unit'))}" if label.get("pieces_per_unit") else "")
                    + (f", batch {_e(label.get('batch'))}" if label.get("batch") else "")
                    + (f", expiry {_e(label.get('expiry'))}" if label.get("expiry") else "") + "</li>")
    n_good = sum(1 for r in rows if 'class="good"' in r)
    alt = f"Photo of the look: {len(instances)} outlined items, {n_good} good, {len(instances) - n_good} flagged."
    if photo is None:
        status = (pack.get("hashes") or {}).get("photo")
        img = f"<p>The photo is not available here ({_e(status)}).</p>"
    else:
        data = base64.b64encode(photo).decode("ascii")
        img = (f'<div class="photo"><img src="data:image/jpeg;base64,{data}" alt="{_e(alt)}">'
               f"{outlines_svg(look, flagged)}</div>")
    legend = ('<p>Outlines: <span class="good">green = good</span>, <span class="flagged">red = flagged</span>; '
              "numbers match the list.</p>")
    items = f"<ol aria-label=\"Items in the look\" style=\"list-style:none;padding:0\">{''.join(rows)}</ol>"
    return (f"<figure>{img}<figcaption>{_e(alt)} Source: {_e(look.get('source'))}.</figcaption></figure>"
            f"{legend}{items}")


def render(pack: dict[str, Any], photo: bytes | None) -> str:
    doc = pack.get("document") or {}
    title = f"Evidence for document {doc.get('number')} / {doc.get('year')}"
    posted = _table("Posted lines", ["Line", "Material", "Description", "Expected", "Counted", "Damaged", "Unit"],
                    [[ln.get("line_no"), ln.get("material"), ln.get("description"), ln.get("expected_qty"),
                      ln.get("counted_qty"), ln.get("damaged_qty"), ln.get("uom")]
                     for ln in doc.get("posted_lines") or []], "No task lines are recorded for this document.")
    moves = _table("Posting steps sent to the ERP", ["Step", "Family", "Status", "Items"],
                   [[m.get("seq"), m.get("family"), m.get("status"), "; ".join(
                       ", ".join(f"{k}={v}" for k, v in sorted(i.items())) if isinstance(i, dict) else str(i)
                       for i in m.get("items") or [])] for m in doc.get("movements") or []],
                   "No posting steps are recorded.")
    events = _table("ERP events", ["Event", "At", "Document", "Movement types"],
                    [[e.get("type"), e.get("at"), f"{e.get('doc_no') or ''} {e.get('doc_year') or ''}".strip(),
                      ", ".join(str(x) for x in e.get("movement_types") or [])] for e in doc.get("events") or []],
                    "No ERP events are recorded.")
    models = _table("Model calls", ["Model", "Purpose", "Latency (ms)", "Cost (USD)", "Outcome"],
                    [[m.get("model"), m.get("purpose"), m.get("latency_ms"), m.get("cost_usd"), m.get("outcome")]
                     for m in pack.get("models") or []], "No model was called: rules only.")
    check = pack.get("check") or {}
    counts = check.get("counts") or {}
    proposal = check.get("proposal") or {}
    check_html = (_dl([("Expected", counts.get("expected")), ("Seen", counts.get("seen")),
                       ("Damaged", counts.get("damaged")), ("Good", counts.get("good")),
                       ("Proposal: receive", proposal.get("receive")), ("Proposal: flag", proposal.get("flag")),
                       ("Reasons", "; ".join(str(r) for r in proposal.get("reasons") or []))])
                  + _table("Claim lines computed from the look", ["Reason", "Units", "Pieces"],
                           [[c.get("reason"), c.get("units"), c.get("pieces")] for c in check.get("claim_lines") or []],
                           "Nothing to claim.")) if check else "<p>No deterministic check: no look.</p>"
    conf = pack.get("confirm") or {}
    confirm_html = _dl([("Method", conf.get("method")), ("By", conf.get("by")), ("At", conf.get("at")),
                        ("Words", " / ".join(str(w) for w in conf.get("words") or []) or "-")])
    claim = pack.get("claim")
    if isinstance(claim, dict):
        claim_html = (_dl([("Status", claim.get("status")), ("Text source", claim.get("source")),
                           ("Decision", claim.get("decision")), ("Decided by", claim.get("decided_by")),
                           ("Confirmed by", claim.get("confirmed_by")), ("Confirmed at", claim.get("confirmed_at")),
                           ("Sent", "yes (SIMULATED: an outbox record, no e-mail)" if claim.get("sent") else "no")])
                      + f"<blockquote>{_e(claim.get('text'))}</blockquote>"
                      + _table("Claim lines", ["Reason", "Units", "Pieces"],
                               [[c.get("reason"), c.get("units"), c.get("pieces")] for c in claim.get("lines") or []],
                               "No lines."))
    else:
        claim_html = "<p>No supplier claim for this document.</p>"
    hashes = pack.get("hashes") or {}
    hash_html = _dl([("Photo sha256", hashes.get("photo_sha256") or "-"),
                     ("Photo still matches", "yes" if hashes.get("photo_sha256_verified") else "no"),
                     ("Pack sha256", hashes.get("pack_sha256"))])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{_e(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="sample" role="note">SAMPLE: test data on a {_e(pack.get('site_mode'))} site. The ERP is a simulator
({_e(pack.get('erp'))}) and sending a claim to the supplier is simulated.</div>
<main>
<header><h1>{_e(title)}</h1>
{_dl([("Type", doc.get("type")), ("Movement type", doc.get("movement_type")), ("Status", doc.get("status")),
      ("Delivery", doc.get("delivery"))])}</header>
<section aria-labelledby="h-photo"><h2 id="h-photo">The look</h2>{_photo_section(pack, photo)}</section>
<section aria-labelledby="h-check"><h2 id="h-check">The check (rules, not a model)</h2>{check_html}</section>
<section aria-labelledby="h-models"><h2 id="h-models">Model calls</h2>{models}</section>
<section aria-labelledby="h-confirm"><h2 id="h-confirm">The confirm</h2>{confirm_html}</section>
<section aria-labelledby="h-doc"><h2 id="h-doc">The ERP document</h2>{posted}{moves}{events}</section>
<section aria-labelledby="h-claim"><h2 id="h-claim">The supplier claim</h2>{claim_html}</section>
<section aria-labelledby="h-hashes"><h2 id="h-hashes">Hashes</h2>{hash_html}
<p>The pack hash is sha256 over the evidence pack's canonical JSON (sorted keys) without the pack hash itself.</p>
</section>
</main>
</body>
</html>
"""
