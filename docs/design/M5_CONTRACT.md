# M5 contract: look-and-act (owner amendment A-06)

Binding for every M5 stream. Source: `<workspace>\SCMTIPS Field M5 Blueprint.html` (revised 1 Nov 2026), owner message
of 1 Nov: build first; video and submission material only once the app is ready to test; at least two test cases that
work at home or at a nearby pharmacy or grocery store, with the glasses.

Base: `slice/m5-look` from `slice/m4-core-integration` at ba7b597. M4 files, branches and ledger rows are not edited by
M5 (shared modules may be extended, never changed in behaviour for M4 callers; every M4 test keeps passing). Ledger:
`docs/STATUS/m5.yaml`, ids `M5-<letter><2 digits>`, status at most `partial` until proven on the owner's phone and
glasses. Commits `type(scope): summary (M5-Xnn)`.

## 1. The two real-world test cases

Both run on a **sandbox site** (M3 sandbox mode: any real barcode becomes a SAMPLE material on first sight, soft
pegging, `YY1_FieldSandbox`), so real products from a home, a grocery store or a pharmacy can be used without any ERP
master data prepared in advance. Nothing a model reads is stored as a brand or company name: materials are named by
what the operator says or by a generic description ("biscuit pack", "tablet box"), see §6.

| Case | Where | What the operator does | What Field checks (deterministic) | Postings |
|---|---|---|---|---|
| **C1 Grocery delivery** | home table or a grocery shop's back room | Lays out 8–20 identical packs (one layer, seen from above or as a shelf front); one look | count of visible packs vs the delivery line; damaged packs (crushed, torn, open); **pack size** read from each label (e.g. "pack of 6", "12 x 50 g") vs the expected pieces per pack → pieces short or over | 101 good units to 101A (unrestricted), 101 flagged units to 101Q (quality); a supplier claim for short/damaged/pack-size differences |
| **C2 Pharmacy receipt** | home medicine cabinet or a nearby pharmacy | Lays out 5–15 medicine boxes of one product; one look (plus a close look at a label if needed) | count; damaged boxes; **batch and expiry** read from each box → expired or expiring within the site's window (default 90 days) are flagged; mixed batches reported | 101 good to 101A, flagged (expired / near expiry / damaged) to 101Q; claim for flagged boxes |

`stack m5-cases` (stream V) creates both on the sandbox site: an expected delivery per case with its line
(expected units, expected pieces per unit for C1, expiry window for C2), printable QR labels for the deliveries, and
resets them on re-run. The operator can also start either case by voice ("new grocery delivery", "new pharmacy
delivery") or from Today (sandbox starters, as M4's "New home receipt").

## 2. Vision look API (stream V owns it)

`POST /v1/vision/looks` — permission `field.task.execute` (operator and up); `Idempotency-Key` required.

Request: `{"task_id": str, "line_id": str|null, "capture_id": str, "object": str|null, "case": "grocery"|"pharmacy"|"generic"}`
— `capture_id` from the existing captures API (photo upload, crop store, on-device blur and consent gates unchanged);
`object` is the noun to count ("pack", "box", "carton"; default from the case).

Response 200 (always; failures degrade, they don't error):
```json
{
  "look_id": "uuid",
  "source": "model" | "partial" | "rules",
  "image": {"capture_id": "...", "width": 1920, "height": 1440},
  "instances": [
    {"n": 1, "box": [x0, y0, x1, y1], "polygon": [[x, y], ...] | null, "score": 0.93,
     "damaged": false, "damage_note": null,
     "label": {"read": true, "pieces_per_unit": 6, "batch": "B2411" | null, "expiry": "2027-03" | null, "raw": "..."}}
  ],
  "counts": {"expected": 20, "seen": 20, "damaged": 2, "good": 18},
  "pack": {"expected_pieces_per_unit": 12, "mismatches": [{"n": 7, "pieces_per_unit": 10}], "pieces_difference": -4} | null,
  "expiry": {"window_days": 90, "flagged": [{"n": 3, "expiry": "2026-12", "reason": "near"}], "batches": ["B2411"]} | null,
  "proposal": {"receive": 18, "flag": 2, "reasons": ["2 damaged", "2 packs hold 10, not 12: 4 pieces short"]},
  "say": "Twenty of twenty. Two damaged. Two packs hold 10, not 12: 4 pieces short.",
  "models": [{"model": "sam-3.1", "purpose": "instances", "latency_ms": 840, "cost_usd": 0.004, "outcome": "ok"}],
  "reasons": []
}
```
Rules: box/polygon coordinates are in image pixels of the original capture; `n` is 1-based and stable for the look;
every number in `say` passes the local number check against `counts`/`pack`/`expiry`/`proposal` (M4 pattern);
`source: "rules"` when no model answered (no key, budget refused, timeout, error): instances empty, counts.seen null,
`say` asks for a spoken count. Pack-size and expiry decisions are computed, never taken from a model's opinion; an
unread label is `read: false`, never guessed. The look never stages or posts anything.

`GET /v1/vision/looks/{look_id}` returns the same body. `GET /v1/captures/{id}` / `/crop` serve the image as today.

**Two-step look (M5-S01).** The body gains `"final": bool` and `"say_next": str | null` (additive; a body without
`final` is final). With instances and a label reader, `POST` answers as soon as SAM's instances are counted:
`final: false`, `source: "partial"`, instances with outlines and `label.read: false`, `counts.expected`/`seen` set
and `counts.damaged`/`good` **null** (damage comes from the label read), `pack`/`expiry` null, `proposal`
`{receive: null, flag: null, reasons: []}`, and `say` = the count only, number-checked, then "Reading the labels."
(e.g. "8 of 20 packs. Reading the labels."). The label read continues in field-api (the request's background task,
after the answer is sent). Then `GET` answers `final: true` with labels, pack/expiry checks, proposal, the full
`say` (as a one-step look) and `say_next` = what the app speaks next (the final `say` without the count sentence
already heard). If no label batch is answered (failure, time-out) or anything fails, the look ends `final: true`,
`source: "partial"`, a reason, the label-free check (every label unread) and `say` = `say_next` = "I couldn't read
the labels. Say your numbers.". A read unfinished at its due time (labels + fallback deadlines + 15 s, e.g. field-api
restarted) is ended the same way by the next read of the look (reason `labels:not_finished`). Looks without
instances or without a reader are final in one step (`say_next` null). The `Idempotency-Key` replay of the POST
returns the stored first answer; the app polls `GET` (every 1 s, up to 40 s) until `final`. Every spoken number is
still checked against the deterministic result, and nothing posts without the operator's numbers and "confirm".
`POST /v1/claims` on a look that is not final is refused **409 `FIELD-CLM-409-LOOK-PENDING`**: a claim is always made
from the final state. Posting a receipt with a look that is not final is allowed (the operator's numbers post); the
evidence page shows the look as it is when the page is opened.

Posting: the existing receive flow (counts, then "post" → "confirm" within 10 s, or touch confirm) gains an optional
`look_id` and a `flag_qty` per line (stream V): good quantity → 101 to 101A, flagged quantity → 101 to 101Q, one
material document, linked to the look. The operator's spoken numbers ("receive 18, flag 2") are what posts; the
proposal only pre-fills them. M4 receive behaviour without `look_id` is unchanged.

Models (all through `field_api.ai` budget guard, provider `meta`, from field-api only): SAM 3.1 for instances with a
text prompt; Muse Spark 1.3 (image input) for labels (pieces per unit, batch, expiry) and damage, per instance crop
where the full image is too small; Llama 3.2 Vision on Baseten as the existing fallback. Endpoints and request shapes
are UNVERIFIED until Gate 0 (META_FIELD rows 20, 23): build behind ports with test doubles in test code, and a probe
script for the owner (`tools/probes/m5_gate0.py`, reads `MODEL_API_KEY` from `.env.local`, never prints it).

## 3. Claims and evidence (stream X owns them)

`POST /v1/claims` `{"look_id"}` (operator and up) → `{"claim_id", "status": "draft", "lines": [{"reason": "damaged"|"short"|"pack_size"|"expired"|"near_expiry", "units": 2, "pieces": 4}], "text": str, "source": "model"|"template", "reasons": [], "evidence_url": str}` — Muse drafts `text` from the lines; every number in it must match the lines (local check) or the template is used.
`POST /v1/claims/{id}/decision` `{"decision": "approve"|"reject", "reason"?}` (supervisor) → `{"status": "pending_confirm", "say": "<read-back>", "confirm_by": iso}`; `POST /v1/claims/{id}/confirm` within 10 s → `{"status": "approved"|"rejected", "say": str}`. Sending to the supplier is SIMULATED (an outbox record, no e-mail). Listing: `GET /v1/claims?status=draft|pending|approved`.

`GET /v1/evidence/documents/{doc_number}?year=` (any field role of the tenant) → JSON: the ERP document (number,
year, movements), the look (photo capture id, instances, counts, pack, expiry), every model call (model, purpose,
latency, cost, outcome), the deterministic check, the spoken or touch confirm (who, when, the words), the claim if any,
and `hashes` (photo sha256 from the crop store; the pack's own sha256 over its canonical JSON).
`GET /evidence/{signed-token}` → a self-contained HTML page of the same pack (photo with outlines drawn as SVG over it,
SAMPLE banner), the link signed like `jobs/audit_report.py` (HMAC, tenant, expiry). `POST /v1/evidence/documents/{doc}/link` returns that signed URL. The phone opens it after "confirm".

## 4. The app (stream B owns it)

- **Look:** in a receive task (and from the two case starters), "look" / "take a look" / a button captures a photo
  from the glasses camera (DAT) or the phone camera, uploads it through the captures API, calls `/v1/vision/looks`,
  shows the photo with the outlines (Compose `Canvas`: numbered, green good, red damaged) and speaks `say`.
- **Voice:** "receive 18, flag 2" pre-fills the lines; "post" then "confirm" (existing 10 s rule); then the app opens
  the evidence link. "Count again" repeats the look. "Make a claim" calls `/v1/claims` and reads the draft.
- **Supervisor:** "claims" / "next claim" reads a draft, "approve" / "reject" → read-back → "confirm" (same pattern as
  M4's approval flow, but against `/v1/claims`, no core).
- **Glasses camera test** in Me ("Test glasses camera"): takes one DAT photo and shows size and delay — this is the
  owner's Gate 0 probe G0-5.
- Everything works with the phone camera when the glasses camera is unavailable; the UI says which camera was used.

## 5. Ownership and parallel streams

| Stream | Worktree / branch | Owns | DB port | Migration |
|---|---|---|---|---|
| V vision + posting + cases | `wt-m5-vision` / `feat/m5-vision` | `field_api/vision/**`, receive posting extension, erp-sim 101Q receipt support if missing, `stack m5-cases`, `tools/probes/m5_gate0.py`, META_FIELD rows 20/23 notes | 5461 | `field_0064_m5_vision` (down_revision field_0062) |
| X claims + evidence | `wt-m5-claims` / `feat/m5-claims` | `field_api/claims/**`, `field_api/evidence/**`, the evidence HTML | 5462 | `field_0065_m5_claims` (down_revision **field_0064_m5_vision**; until V lands, X writes its migration against field_0062 and the integrator rebases the chain) |
| B app | `wt-m5-app` / `feat/m5-app` | `apps/field-android/**` | - | - |

X reads looks only through the response shape in §2 (`GET /v1/vision/looks/{id}`), via a small port with a test
double, so it does not wait for V. B codes against §2–§3 with a scripted HTTP fake in tests. The integrator (lead
session) merges V → X → B into `slice/m5-look`, fixes the migration chain, runs every gate and the smokes.

## 6. Privacy and naming

Real products appear on camera. Field stores no brand or company names: the label read asks only for pieces per
unit, batch, expiry and damage; `raw` text is kept 30 days like assistant turns and is excluded from logs; material
names in the sandbox come from the operator's words or a generic description. On-device blur and consent gates for
photos are unchanged. The video is the owner's decision (§ Blueprint), not part of this build.

Look photo size (M5-P01, owner-approved 1 Nov 2026; was 640 px): a look photo from the glasses or the phone camera is
at most **1600 px** on its long side (aspect kept, never scaled up), JPEG quality about 85 (lower only to stay within
the captures API's 1 MB limit, which is unchanged). Faces are found and pixelated on the phone **on that full-size
photo, before it is uploaded**, and the captures API refuses a photo without `blur_applied`, so no model call ever
sees an unblurred face. SAM 3.1 gets the photo as stored; each label crop sent to Muse (or the fallback) is cut from
the full-size photo and is at most **768 px** on its long side. The evidence page shows the photo as stored. Scan
crops (barcode captures, FR2.066) keep their own 640 px rule.

## 7. Done for M5 build (before the owner's device test)

All gates green (ruff, mypy --strict, tools/checks, openapi drift, alembic round trip, pytest, compile_check --all,
kotlin_jvm, CI green on the build mirror); `smoke --m5` on the stand-in stack runs both cases end to end with model
test doubles (look → proposal → post with flag → 101A + 101Q in erp-sim → claim → approve → evidence page); an APK in
CI. Proof on the real Meta API and on the glasses is the owner's device session.
