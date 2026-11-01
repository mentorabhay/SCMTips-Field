# M5 case C3 contract: "Is this unit really new?" (authenticity check)

Binding for the C3 stream (`feat/m5-c3-authenticity`, ledger rows `M5-T01`...`M5-T07` in `docs/STATUS/m5.yaml`) and
for the app builder who codes the phone flow against section 7. Built on `slice/m5-look` under owner amendment A-06;
every M5 rule applies (M5_CONTRACT.md): status at most `partial` until proven on the owner's phone and glasses, model
calls only through the field-api budget guard, no brand or company names stored, nothing done until proven.

**Everything in C3 is SAMPLE.** The only OEM is the fictional **Kestrel Optics (SAMPLE)** (`oem: "kestrel-sample"`)
served by the OEM simulator. No real brand, seller, marketplace or logo appears in code, data, labels or pages.

## 1. The case

A customer (or a returns-dock operator) holds a delivered, boxed product. The OEM signed a QR code printed on the
box's seal. The person looks at the box with the glasses (or the phone) and says "check this box". Field answers
with a verdict decided by deterministic rules, says it aloud (number- and fact-checked), keeps an evidence page, and
lets the person make a claim when the unit is not what it should be.

Example (returned unit resold as new, seal taped over):
"Code is genuine. But this unit was activated on 12 October and returned on 20 October. It is not a new unit. The
seal shows tape over the original."

## 2. Signals

| # | Signal | Source | Decides the verdict? |
|---|---|---|---|
| S1 | **Signed seal code**: Ed25519 signature over the canonical payload, verified **in field-api** against the OEM's public key (fetched from the OEM, cached) | QR text | yes |
| S2 | **Unit history** from the OEM registry: `manufactured`, `shipped_to_seller`, `delivered`, `activated`, `returned`, `refurbished` (each with a date; area optional, city level) | OEM registry | yes |
| S3 | **First-check claim**: the first verification of a serial is recorded by the OEM registry, atomically (time, coarse area if given, a pseudonymous checker id). Later checks by a *different* checker learn "first checked on <date>" | OEM registry | yes |
| S4 | **Visual seal check** (optional, needs a look photo): SAM 3.1 outlines the seal (text prompt `seal`, then `sticker` if nothing found); Muse Spark 1.3 reads tamper signs on the seal crop | Meta Model API via the budget guard | **no**: sets `tamper` and adds reasons and a sentence, never changes the verdict |

### 2.1 Seal code format (QR text)

```
SEAL1.<kid>.<payload_b64url>.<signature_b64url>
```

- `kid`: 16 lowercase hex characters, the first 16 hex of sha256 over the raw 32-byte Ed25519 public key.
- `payload_b64url`: base64url without padding of the **canonical payload bytes**: UTF-8 JSON of exactly
  `{"nonce", "oem", "serial", "sealed_at", "sku", "v"}` with sorted keys, no whitespace, ASCII only
  (`json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`).
  - `v`: integer `1`
  - `oem`: `^[a-z0-9-]{3,40}$` (the sample OEM is `kestrel-sample`)
  - `serial`: `^[A-Z0-9-]{4,40}$`
  - `sku`: `^[A-Z0-9-]{2,40}$`
  - `sealed_at`: `YYYY-MM-DD` (the sealing day, UTC)
  - `nonce`: `^[0-9a-f]{16}$` (random per unit, so two units never share a payload)
- `signature_b64url`: base64url without padding of the 64-byte Ed25519 signature over
  `b"scmtips-field/oem-seal/v1\n" + payload_bytes` (domain-separated: the key signs nothing else in this format).
- Verification order in field-api: structure (4 dot-separated parts, prefix `SEAL1`, base64url alphabets, sizes,
  total length at most 1024) -> payload JSON parses -> payload's `oem` known to the configured OEM port -> key with
  `kid` among the OEM's keys (one forced refetch when unknown, for key rotation) -> signature valid over the exact
  bytes -> payload bytes are the canonical encoding of the parsed fields and every field matches its pattern.
  A payload that changed by one byte fails the signature; a non-canonical payload with a valid signature is
  `code:bad_payload` (an OEM fault, CANNOT_VERIFY).

### 2.2 OEM public keys (JWKS-like)

`GET /_oem/.well-known/oem-keys` (public) ->
```json
{"oem": "kestrel-sample", "name": "Kestrel Optics (SAMPLE)", "sample": true,
 "keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": "3f1c...", "x": "<b64url 32 bytes>"}]}
```
field-api caches the key set per adapter for `FIELD_OEM_KEYS_TTL_S` (default 300 s; a cache, not a store: a
restart or an unknown `kid` refetches).

## 3. Verdicts and the exact rule table

Inputs (all computed, never a model's opinion):
`code` in {`valid`, `not_a_seal_code`, `bad_payload`, `unknown_oem`, `unknown_key`, `bad_signature`,
`oem_unavailable`, `oem_not_configured`}; `registry` in {`found`, `unknown_unit`, `sku_mismatch`, `unavailable`,
`not_asked`} plus the event types present; `first_check` in {`first`, `same_checker`, `other_checker`,
`not_recorded`}.

Rules, first match wins:

| Rule | Condition | Verdict | Reason codes added |
|---|---|---|---|
| R1 | code = `not_a_seal_code` | `CANNOT_VERIFY` | `code:not_a_seal_code` |
| R2 | code = `unknown_oem` | `CANNOT_VERIFY` | `code:unknown_oem` |
| R3 | code = `oem_not_configured` | `CANNOT_VERIFY` | `oem:not_configured` |
| R4 | code = `oem_unavailable` | `CANNOT_VERIFY` | `oem:unavailable` |
| R5 | code = `unknown_key` | `LIKELY_COUNTERFEIT` | `code:unknown_key` |
| R6 | code = `bad_signature` | `LIKELY_COUNTERFEIT` | `code:bad_signature` |
| R7 | code = `bad_payload` | `CANNOT_VERIFY` | `code:bad_payload` |
| R8 | registry = `unavailable` | `CANNOT_VERIFY` | `registry:unavailable` |
| R9 | registry = `unknown_unit` | `CANNOT_VERIFY` | `registry:unknown_unit` |
| R10 | registry = `sku_mismatch` | `CANNOT_VERIFY` | `registry:sku_mismatch` |
| R11 | history has `returned` or `refurbished` | `RETURNED_REFURBISHED` | `history:returned` and/or `history:refurbished` |
| R12 | history has `activated` | `GENUINE_PREVIOUSLY_ACTIVATED` | `history:activated` |
| R13 | first_check = `other_checker` | `CANNOT_VERIFY` | `first_check:other_checker` |
| R14 | otherwise (valid code, unit found, no activation / return / refurbish, first check is this checker's) | `GENUINE_NEW` | none |

Always added (whatever rule matched), for the record: `history:activated` / `history:returned` /
`history:refurbished` for each such event; `first_check:other_checker` when another checker was first;
`history:not_shipped` when the unit has no `shipped_to_seller` event (informational only).

Why R13 is CANNOT_VERIFY and not LIKELY_COUNTERFEIT: a printed code can be copied, and the box checked second may be
the genuine one (the first checker may hold the copy). Field says exactly that and lets the person claim.

`tamper` (from S4 only): `true` when the visual check finished and Muse reported at least one tamper sign;
`false` when it finished, a seal was seen and no sign was reported; `null` when there was no photo, the check is
still running, failed, or no seal was seen and `seal_missing` was not reported. Signs, a closed set (anything else
in the model's answer is dropped): `tape_over_seal`, `seal_torn`, `reglued`, `sticker_over_seal`, `seal_missing`.
Each sign adds `visual:<sign>`; visual failures add `visual:no_model`, `visual:image_unavailable`,
`visual:<model>:<error code>`, `visual:not_finished`; SAM finding nothing adds `visual:seal_not_outlined` (Muse
then reads the whole photo, scaled to 768 px).

### 3.1 What is spoken (`say`)

Built from the facts only (template, no model): every number and date in `say` comes from the signals (property
test: the numbers of `say` are a subset of the numbers of the facts, `briefs.numbers`). Dates are spoken as
"12 October" (the year added when it differs from the check's year).

| Verdict | Sentence(s) |
|---|---|
| GENUINE_NEW | "Code is genuine. This unit is new: it was never activated or returned." (+ "You first checked it on <date>." when same_checker on an earlier day) |
| GENUINE_PREVIOUSLY_ACTIVATED | "Code is genuine. But this unit was activated on <date>. It is not a new unit." |
| RETURNED_REFURBISHED | "Code is genuine. But this unit was [activated on <date> and ]returned on <date>[ and refurbished on <date>]. It is not a new unit." |
| CANNOT_VERIFY (R13) | "Code is genuine, but it was first checked on <date> by someone else. A printed code can be copied, so I cannot verify this unit." |
| CANNOT_VERIFY (others) | "I cannot verify this code." + one reason sentence ("It is not a seal code." / "The maker is not known." / "The maker's records cannot be reached." / "The maker has no record of this unit." / "The maker's records do not match this code.") |
| LIKELY_COUNTERFEIT | "This code is not signed by the maker. This is likely a counterfeit." |

Visual sentence (appended when `tamper` is true): "The seal shows " + signs joined ("tape over the original", "a
torn seal", "signs of re-gluing", "a sticker over the seal", "no seal") + "." When the visual check is running:
" Checking the seal." is appended to the first answer.

## 4. Field API

All under the existing auth (bearer), RLS (tenant + site scope) and the Idempotency-Key middleware on every POST.
Permission **`field.authenticity.check`**: `field.operator`, `field.supervisor`, `field.viewer` (and `field.admin`).

### 4.1 `POST /v1/authenticity/checks`

Request:
```json
{"code": "SEAL1.3f1c....", "capture_id": "uuid | null", "site_id": "uuid | null", "area": "Pune | null"}
```
- `code`: the QR text, 1..1024 characters (longer -> 422 validation).
- `capture_id`: optional look photo of the seal from the captures API (same photo rules as an M5 look: at most
  1600 px, faces pixelated on the phone, `blur_applied` required, kept 30 days). The capture must be in scope.
- `site_id`: optional; default: the capture's site, else the principal's only site; else 422
  `FIELD-AUT-422-SITE`. Must be in the principal's site scope (403 otherwise).
- `area`: optional, coarse, city level at most: `^[A-Za-z][A-Za-z .'-]{0,59}$` (no digits, so no coordinates,
  postcodes or addresses). Sent to the OEM with the first check. The app sends none unless the owner decides.

Response **200** (also the Idempotency-Key replay, which returns the stored first answer):
```json
{
  "check_id": "uuid",
  "final": true,
  "verdict": "GENUINE_NEW | GENUINE_PREVIOUSLY_ACTIVATED | RETURNED_REFURBISHED | CANNOT_VERIFY | LIKELY_COUNTERFEIT",
  "tamper": true,
  "reasons": ["history:activated", "history:returned", "visual:tape_over_seal"],
  "signals": {
    "code": {"status": "valid", "oem": "kestrel-sample", "oem_name": "Kestrel Optics (SAMPLE)", "kid": "3f1c...",
             "serial": "KSO-24-000102", "sku": "KSO-BINO-842", "sealed_at": "2026-09-30"},
    "registry": {"status": "found", "sku": "KSO-BINO-842",
                 "events": [{"type": "manufactured", "at": "2026-09-30", "area": null}, ...],
                 "activated_at": "2026-10-12", "returned_at": "2026-10-20", "refurbished_at": null},
    "first_check": {"status": "first", "first_checked_at": "2026-11-01T10:12:03Z", "area": null},
    "visual": {"status": "done", "capture_id": "uuid", "seal_found": true, "box": [x0, y0, x1, y1],
               "score": 0.9, "signs": ["tape_over_seal"], "image": {"width": 1600, "height": 1200}}
  },
  "say": "Code is genuine. But this unit was activated on 12 October and returned on 20 October. It is not a new unit. The seal shows tape over the original.",
  "say_next": "The seal shows tape over the original.",
  "models": [{"model": "sam-3.1", "purpose": "seal", "latency_ms": 640, "cost_usd": 0.004, "outcome": "ok"},
             {"model": "muse-spark-1.3", "purpose": "seal_tamper", "latency_ms": 1900, "cost_usd": 0.001, "outcome": "ok"}],
  "evidence_url": "/v1/authenticity/checks/<id>/evidence",
  "claim_id": null,
  "site_id": "uuid", "capture_id": "uuid | null", "created_at": "iso", "checked_by": "principal id"
}
```
Field values: `signals.code` keeps `oem`/`serial`/`sku`/`sealed_at` null unless the payload parsed;
`signals.registry.status` = `not_asked` when the code did not verify (R1-R7); `signals.first_check.status` =
`not_recorded` then too (a first check is recorded only for a verified code of a known unit);
`signals.visual.status` = `none` (no photo) | `pending` | `done` | `failed`.

**Two steps (like M5-S01).** The verdict comes from S1-S3 only, so it is final at once. With a photo and a
configured vision model, POST answers `final: false`, `signals.visual.status: "pending"`, `tamper: null`, `say` =
the verdict sentences + " Checking the seal.", `say_next: null`; the visual check runs in the request's background
task; `GET` then answers `final: true` with `tamper`, the visual reasons, `say` = verdict sentences (+ the visual
sentence) and `say_next` = what to speak next (the visual sentence; "The seal looks intact." when `tamper` is
false; "I couldn't check the seal." when it failed). A visual check unfinished at `visual_due_at` (instances +
labels deadlines of M5 + 15 s; e.g. after a restart) is ended by the next read with `visual:not_finished`. Without a
photo (or without a model) the check is final in one step (`say_next` null; `visual:no_model` when a photo was given
but no model is configured). The app polls `GET` every 1 s, up to 45 s.

### 4.2 `GET /v1/authenticity/checks/{check_id}` (`field.authenticity.check`)

The same body as it is now. 404 `FIELD-AUT-404-CHECK` when not visible (tenant / site scope) or not a uuid.

### 4.3 Evidence

- `GET /v1/authenticity/checks/{id}/evidence` (`field.authenticity.check`) -> the JSON evidence pack: the check
  body (signals, verdict, reasons, say, models), the rule that matched (`rule: "R11"`), the claim if any, the code
  text, and `hashes` (`photo_sha256` from the crop store with `photo_sha256_verified`, `pack_sha256` = sha256 over
  the canonical JSON of the pack without itself, as M5 packs). ETag = the pack's sha256.
- `POST /v1/authenticity/checks/{id}/link` -> `{url, path, expires_at}`: a signed link
  (HMAC-SHA256 with `FIELD_EVIDENCE_SECRET`, its own domain string `scmtips-field/m5-c3-evidence/v1`, tenant + check id
  + expiry, `FIELD_EVIDENCE_LINK_TTL_S`), host `FIELD_PUBLIC_BASE_URL` when set.
- `GET /evidence/check/{token}` (public, the token is the credential; 401 `FIELD-EVD-401-INVALID-TOKEN`) -> a
  self-contained HTML page: SAMPLE banner, verdict, the rule, signals, the history timeline, the photo with the seal
  outline drawn as SVG over it, hashes. Same headers and CSP as the M5 evidence page.

### 4.4 Claim from a check

`POST /v1/claims {"check_id": "uuid"}` (`field.claim.create`, as for looks; exactly one of `look_id` / `check_id`)
-> a claim with `kind: "authenticity"`, `check_id` set and `look_id: null`; one claim per check (a second create
returns the first, 200). Lines (deterministic, one unit each, `pieces: 0`):
`not_new` (GENUINE_PREVIOUSLY_ACTIVATED or RETURNED_REFURBISHED), `counterfeit` (LIKELY_COUNTERFEIT),
`copied_code` (R13), `cannot_verify` (other CANNOT_VERIFY), `tampered_seal` (tamper true, with any verdict).
GENUINE_NEW without tamper -> 422 `FIELD-CLM-422-NOTHING-TO-CLAIM`; a check whose visual is pending -> 409
`FIELD-CLM-409-CHECK-PENDING`. The text is the template (or Muse through the same number check as M5 claims).
Decision, confirm within 10 s, the SIMULATED send and listing are unchanged (`GET /v1/claims` lists both kinds;
items carry `kind` and `check_id`; `look_id` is null for `kind: "authenticity"`). The claim's `evidence_url` is
the check's evidence path.

### 4.5 Error codes

| HTTP | Code | When |
|---|---|---|
| 422 | `FIELD-HTTP-422-VALIDATION` | body invalid (code too long, bad area, bad uuid) |
| 422 | `FIELD-AUT-422-SITE` | no `site_id`, no capture and more than one site in scope |
| 403 | `FIELD-AUTH-403-FORBIDDEN` | no `field.authenticity.check`, or the site is out of scope |
| 404 | `FIELD-AUT-404-CAPTURE` | `capture_id` not found or out of scope |
| 404 | `FIELD-AUT-404-CHECK` | GET / evidence / link of an unknown check |
| 409 | `FIELD-CLM-409-CHECK-PENDING` | claim on a check whose visual check is still running |
| 422 | `FIELD-CLM-422-NOTHING-TO-CLAIM` | claim on GENUINE_NEW without tamper |
| 401 | `FIELD-EVD-401-INVALID-TOKEN` | tampered, malformed or expired evidence link |

An unreachable or unconfigured OEM is **not** an HTTP error: the check answers 200 `CANNOT_VERIFY` with
`oem:unavailable` / `oem:not_configured`. A model failure is never an error either (`visual.status: failed`).

## 5. OEM port and the OEM simulator

- **`OemPort`** (connector package `connectors/oem`, module `field_oem`): `keys(oem) -> OemKeySet`,
  `check_unit(oem, serial, checker, area) -> UnitCheck` (history + the atomic first-check claim in one call),
  errors `OemUnavailable`, `OemNotConfigured`, `UnknownOem`. Chosen by config `FIELD_OEM_ADAPTER`:
  - `sim` (default): HTTP to the OEM simulator at `FIELD_OEM_SIM_URL` (default `FIELD_ERP_SIM_URL` + `/_oem`), the
    unit call with `X-Sim-Admin-Token` (`ERPSIM_ADMIN_TOKEN`), 5 s timeout.
  - `oem`: the "real OEM" adapter. **No real OEM has signed seals or opened a registry for this build**, so it
    refuses every call with `OemNotConfigured` (-> CANNOT_VERIFY `oem:not_configured`). Honest per rule 2.4.
- `checker` sent to the OEM is pseudonymous: the first 32 hex of HMAC-SHA256(`FIELD_EVIDENCE_SECRET`,
  `"scmtips-field/oem-checker/v1\n" + tenant_id + "\n" + principal_id`). The OEM never gets a name, e-mail, device
  id or location finer than the optional `area`. (Rotating `FIELD_EVIDENCE_SECRET` makes earlier checkers look like
  other checkers.)
- **OEM simulator** (`services/oem-sim`, module `oem_sim`): its own schema `oemsim` and Alembic history
  (`oemsim.alembic_version`) in the simulator database (`OEMSIM_DATABASE_URL`, default `ERPSIM_DATABASE_URL`);
  mounted by erp-sim under `/_oem` when `ERPSIM_OEM_ENABLED` is true (default true), so no new container or hostname.
  Tables `oemsim.unit` (serial, oem, sku, sealed_at, nonce, scenario, created_at), `oemsim.unit_event` (serial,
  type, at, area), `oemsim.first_check` (serial primary key: the first insert wins, `ON CONFLICT DO NOTHING`).
  Signing key: Ed25519 private key = sha256(`"scmtips-field/oem-sim-key/v1\n"` + `OEMSIM_SIGNING_SEED`) as the
  32-byte seed; the seed is a secret env var (at least 32 characters), generated into `.env.local` by `stack up`,
  never committed; without it the key and label routes answer 503 `OEMSIM-503-NO-KEY` and field-api answers
  CANNOT_VERIFY `oem:unavailable`.
  Routes: `GET /_oem/.well-known/oem-keys` (public); `POST /_oem/v1/units/{serial}/checks {checker, area?}`
  (admin token) -> `{unit: {serial, sku, oem, events}, first_check: {first, at, area, same_checker}}`, 404
  `OEMSIM-404-UNIT`; `GET /_oem/v1/units/{serial}` (admin token); admin (admin token): `POST /_oem/admin/units`
  (upsert a unit with its events, returns its signed `code`), `POST /_oem/admin/reset`; `GET /_oem/ui` (units and
  their history, read only) and `GET /_oem/labels` (the printable label sheet, section 6).

## 6. Labels and the five scenarios

`stack c3` seeds the scenarios through the admin API (`field-api` tool `seed_c3`) and writes `var/c3_labels.html`
(the same sheet as `GET /_oem/labels`). Print on paper, cut out, tape onto any box at home.

| Label | Scenario | Registry | Expected verdict |
|---|---|---|---|
| L1 | Genuine new | manufactured, shipped_to_seller, delivered | GENUINE_NEW |
| L2 | Returned, resold as new | + activated, returned | RETURNED_REFURBISHED |
| L3 | Counterfeit | none: the code is signed with a forger's key (made in the label sheet only) | LIKELY_COUNTERFEIT |
| L4a / L4b | Cloned code | one unit; the same code printed twice | first check GENUINE_NEW, a check of the other copy by a different checker CANNOT_VERIFY (`first_check:other_checker`) |
| L5 | Tampered seal | genuine new unit; the label is drawn with a strip of tape over a torn seal, and the sheet says to put real tape over it | GENUINE_NEW with `tamper: true` when a photo is sent |

Seal artwork is drawn in SVG with "KESTREL OPTICS (SAMPLE)" and "SAMPLE SEAL - NOT A REAL PRODUCT"; no real logos.

## 7. Phone flow (for the app builder)

- **Start**: voice "check this box" (also "is this new", "check the seal") while a work session is open; a "Check a
  box" button on Today. No task is needed. Speak: "Show me the seal code."
- **Scan**: the existing barcode scan reads the QR (glasses camera through DAT, phone camera when the glasses camera
  is unavailable; the UI says which camera was used). A QR not starting with `SEAL1.` is still sent (the server
  answers CANNOT_VERIFY "It is not a seal code.").
- **Photo** (optional, recommended): the same frame or one more photo of the seal, through the M5 photo pipeline
  (at most 1600 px, faces pixelated on the phone, `POST /v1/captures` with `site_id`, `task_id: null`,
  `code_type: "seal_photo"`, `code_value: "authenticity"`, `blur_applied: true`) -> `capture_id`. Without camera or
  capture permission (e.g. a `field.viewer`), check by code only.
- **Check**: `POST /v1/authenticity/checks` (new Idempotency-Key per check, the same key on a retry); speak `say`;
  show a verdict card (GENUINE_NEW green, GENUINE_PREVIOUSLY_ACTIVATED and RETURNED_REFURBISHED amber,
  CANNOT_VERIFY grey, LIKELY_COUNTERFEIT red, a "seal tampered" chip when `tamper` is true), the history timeline,
  the photo with the seal box. When `final` is false, poll `GET` every 1 s up to 45 s, then speak `say_next`.
- **Voice after the answer**: "check again" (a new check with a new key), "make a claim" (`POST /v1/claims
  {check_id}`, read the claim `text`; 422 nothing-to-claim -> "There is nothing to claim: the unit is new and the
  seal looks intact."), "show evidence" (`POST /v1/authenticity/checks/{id}/link`, open `url`), "done".
- **Supervisor**: authenticity claims arrive in the existing "claims" / "next claim" flow (approve / reject ->
  read-back -> "confirm" within 10 s); the card shows `kind`.
- **Errors**: 403 -> "You are not allowed to check boxes here."; 422 SITE -> ask to pick a site in Me -> Site;
  network failure -> "I couldn't reach Field. Try again." (retry with the same Idempotency-Key).

## 8. Privacy

- Photos: the captures API's rules (faces pixelated on the phone before upload, `blur_applied` required, kept 30
  days like M5 look photos). Muse is asked only for tamper signs from a closed list; its free text is not stored.
  No face, person, brand or company name is asked for or stored.
- Area: optional, city level at most, never coordinates (validated: no digits). Omitted by default.
- The OEM receives the serial, a pseudonymous checker id and the optional area; nothing else.
- The check record (code text, signals, verdict, say) is kept as evidence, under tenant RLS and site scope.

## 9. What C3 does NOT prove

- It needs the OEM to sign its seals and to open its registry. No real OEM does that for this build: the OEM is a
  simulator, and the real-OEM adapter refuses (`oem:not_configured`).
- A printed QR code can be photocopied. A valid signature proves the code was made by the OEM's key, not that this
  box is the one it was printed for. The first-check claim only detects a copy when both copies are checked; the
  first checker may hold the copy. An NFC seal with a per-tap counter or challenge-response (e.g. a secure element)
  would be much stronger and is out of scope.
- A leaked OEM signing key defeats S1 entirely.
- The visual check only supports: a model can miss tape or see tamper that is not there. It never changes the
  verdict, only `tamper` and the reasons.
- Unit history is only as good as the OEM's records (a return not reported to the OEM is invisible).
- The Meta model request and answer shapes are UNVERIFIED until Gate 0 (META_FIELD rows 20, 23), as in M5. Nothing
  in C3 is proven on the owner's phone and glasses yet.
