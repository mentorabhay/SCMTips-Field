# M4 hackathon integration: binding contract (owner amendment A-04, 31 Oct 2026)

M4 connects SCMTips Field to the SCMTIPS core for the hackathon (submit 4 Nov 22:00 IST). It is built on
top of M3 (amendment A-03), which stays: theme, sandbox, warehouse and tower jobs, glasses-first session,
Field Assistant. Source of truth for every core shape: the core's handover files, copied for the build at
`/home/claude/m4-inputs/01_FIELD_MOBILE_AGENT_HANDOVER.md`, `01a_FIELD_ADDENDUM_CORE_PATHS.md` (paths and
the feed-based receipt; it overrides 01 where they differ) and `01b_FIELD_EXCHANGE_CONTRACT.md`; the
exchange contract is in `docs/integration/exchange-contract-v1/`. The core is NOT deployed yet: everything
is built and tested against a stand-in core (section 3), and switching to the real core is settings only.

## 1. Streams, branches, ownership

| Stream | Branch / worktree | Owns | DB port |
|---|---|---|---|
| C core link (F7, F4, core stand-in) | `feat/m4-core-link`, `/home/claude/wt-m4-core` | `tools/fake-core/**`, `field_api/auth/**`, `field_api/routes/auth.py`, field-worker outbox + new `field_worker/core_feeds/**`, `tools/dev_stack/**`, `.env.example` | 5451 |
| B approver app (F2, F1) + M3 phone fixes | `feat/m4-approver`, `/home/claude/wt-m4-android` | `apps/field-android/**` | none |
| M Meta router (F3) + M3 assistant fixes | `feat/m4-router`, `/home/claude/wt-m4-router` | `field_api/assistant/**`, `field_api/ai/**`, new `field_api/briefs/**`, `config/ai_pricing.yaml`, `docs/META_FIELD.md` rows 19-20 and new rows | 5452 |

- All start from `slice/m4-core-integration`. Commits `type(scope): summary (M4-Cnn | M4-Bnn | M4-Mnn)`.
- Ledger: append to `docs/STATUS/m4.yaml` (fields as phase ledgers); everything at most `partial` until proven
  on the owner's phone and glasses AND against the real core. Every core-dependent row in META_FIELD style
  stays UNVERIFIED until a call to the real core is recorded.
- Migrations if needed: C uses `field_0062_m4_core`, M uses `field_0063_m4_router`, both with
  `down_revision = "field_0061"`; the integrator chains them.
- Rules of CLAUDE.md apply in full (real gates, no orphans, no mocks/fakes/sims imported by production code,
  mypy --strict, never weaken/skip a test, secrets by env-var name only, A-02).

## 2. Settings (names only; values in `.env.local`)

`FIELD_CORE_BASE_URL` (default the stand-in), `FIELD_CORE_JWKS_URL` (default `{CORE}/v1/core/jwks.json`
on the stand-in), `FIELD_CORE_DEVICE_STATUS_URL` (template with `{device_id}` and `{tenant_id}`),
`FIELD_CORE_INVENTORY_FEED_URL`, `FIELD_CORE_INVENTORY_FEED_SECRET`, `FIELD_CORE_SUPPLY_FEED_URL`,
`FIELD_CORE_SUPPLY_FEED_SECRET`, `ASSISTANT_MODEL` (default `muse-spark-1.3`), `MODEL_API_KEY`.
The owner's PC already uses ports 3100, 5450, 5451, 8000, 8001, 8790, 8791 (the real core API is on 8000):
the dev stack keeps choosing free ports and records them.

## 3. The stand-in core (stream C, in `tools/fake-core`, a dev double, never presented as the core)

Serves the handover's paths and shapes exactly, on top of what fake-core already serves:
- `POST /v1/auth/app/token` (header `X-Requested-With: lr`): e-mail + password, or `pairing_code`; demo users
  from a seed (an approver with `voice.approve`, an operator; password from env `FAKE_CORE_DEMO_PASSWORD`,
  default printed by `stack up` as a dev value); answers 200 with access_token (EdDSA, kid prefix
  `scmtips-core-ed25519-`, claims incl. `permissions`, `email`), `wearable {session_id, token, expires_at,
  device_id}`, `user`, `capabilities`; 401 invalid_credentials, 403 pairing_required, 429.
- `GET /v1/core/jwks.json`; `GET /v1/core/devices/{device_id}/status?tenant_id=` (unknown -> revoked).
- With `Authorization: Bearer <wearable token>` + `X-Device-Id`: `GET /v1/wearable/next`,
  `GET /v1/briefs/decision/{id}`, `POST /v1/briefs/decision/{id}/check` (accepted only if every number in the
  text appears in the template; answers `{accepted, reasons[], template_text}`), `POST /v1/voice/challenges`,
  `POST /v1/voice/commands` (single-use challenge, grammar intent, mandatory confirm turn), `GET|POST
  /v1/auth/step-up`, `POST /v1/evidence/photos`, `GET /v1/wearable/sessions`, `DELETE
  /v1/wearable/sessions/{id}`. Shapes follow the handover and the ported ARO client (`api/Models.kt` in
  `/home/claude/m4-inputs/aro-wearable-src/main/java/com/scmtips/wearable/api/`); where they differ, the
  ARO client wins (it talks to the real core today) and the difference is reported.
- Two SAMPLE decisions (rare-earth magnet export curbs: expedite air freight vs. qualify alternate supplier),
  card <= 240 chars, ~20 s spoken brief, options, an approval band that needs step-up.
- Feed receivers `POST /v1/inbound/feeds/{feed_id}` verifying `X-SCMTIPS-Timestamp` (<= 5 min) and
  `X-SCMTIPS-Signature: sha256=<hex HMAC-SHA256(secret, timestamp + "." + raw_body)>`, recording rows.

## 4. Field changes

- C, F7: `/exchange` accepts core tokens with the extra claims; JWKS re-read on unknown kid; device status
  via the URL template. F4: after a GR 101 posts, the outbox delivers the two upsert rows of 01a
  (inventory on-hand after the receipt, read from the ERP through ErpPort; open-supply PO line status
  received) to the two feeds, signed; idempotent on event id, retried, dead-letter after N tries; only when
  both feed URLs are set. A drone-world seed loader for erp-sim that reads the core's export folder when it
  exists (`stack seed-core-export <dir>`), with a clear message when it does not.
- M, F3: `POST /v1/briefs/spoken {decision_id, template_text}` with headers `X-Core-Token` (the app's
  wearable token, forwarded, never stored or logged) and `X-Device-Id`: Muse rewrites the template into a
  ~20 s spoken brief; field-api sends it to the core's check; answers `{text, source: "model"|"template",
  reasons[]}` — the template whenever the check refuses, the model is off, or anything fails. Transcribe
  (`muse-voice-transcribe-1.0`) and SAM 3.1 outline endpoints may be added behind the guard; unpriced models
  stay refused (feature off), recorded UNVERIFIED. Muse Image is never called (a test asserts no model id
  containing "image" can be configured).
- M, M3 fixes found in the owner's test (31 Oct): the assistant answered Start Work 6-7 s late because every
  turn went to Muse first and timed out. Rules first: greeting, work list, start, what's next, how many left,
  summary are answered by rules at once; only what rules cannot parse goes to the model, with a 3.5 s
  deadline. New sandbox intents: "new home receipt", "count shelf <bin>" create the task (section-3 sandbox
  service of M3) and open it.
- B, F2: sign-in screen (e-mail + password, or pairing code; the M3 QR pairing stays as an option), tokens in
  EncryptedSharedPreferences, never logged; home by `capabilities`: Decisions / Warehouse / Tower.
- B, F1: `feature-decisions` Gradle module ported from the ARO wearable app's flow, API client and card
  formatter (sources in `/home/claude/m4-inputs/aro-wearable-src/`, read-only, rewritten on Field's
  core-wearables and core-voice, no second glasses wrapper, nothing else copied): next decision, spoken
  brief (via `POST /v1/briefs/spoken`, template fallback), "approve option two" / "reject" / "repeat",
  confirm turn, phone step-up, committed by audio. The work session (M3) announces "1 decision waiting"
  and routes "decisions" to this flow.
- B, M3 fixes: Start Work speaks a local greeting at once and never waits silently on the server; Today
  offers "New home receipt" / "Count a shelf" on sandbox sites; optional attention word "Field" (setting,
  off by default) so only sentences starting with it are taken as commands. "Hey Meta" stays Meta's: it is
  handled by the glasses before any app hears it.

## 5. Done for M4 today (integration)

All gates green; `smoke --all` and `smoke --home` still pass; a new `smoke --approver` passes against the
stand-in (sign in, next decision, spoken brief with check, approve option two, confirm, step-up, committed)
and a GR 101 produces two signed feed rows the stand-in verifies; CI green including emulator launch.
