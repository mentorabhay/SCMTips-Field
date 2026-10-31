# fake-core: dev identity provider and the stand-in core

`fake-core` is a **dev double**. Nothing in it is the SCMTIPS core, and it must never be presented as the core.

It serves two things:

1. **Legacy dev identity** (Phase 1, T1.035): `POST /api/v1/auth/token`, `GET /.well-known/jwks.json`,
   `GET /api/v1/devices/{id}/status`, `POST /api/v1/devices/{id}/revoke`. The dev stack's QR pairing and the
   smoke tests mint tokens here.
2. **The stand-in core** (M4 contract section 3, package `fake_core.standin`): the core's `/v1` paths and shapes
   from the core's handover files (01, 01a, 01b), the ported ARO wearable client (`api/Models.kt`) and the core's
   reply `TO_FIELD.md` of 31 Oct (which states the real core's behaviour and wins where it speaks), so Field can be
   built and tested while the real core is not deployed. Switching Field to the real core is settings only
   (`FIELD_CORE_*`, see `.env.example`).

## The stand-in core

| Path | What it does |
|---|---|
| `POST /v1/auth/app/token` | e-mail + password, or `pairing_code`; 200 with `access_token` (EdDSA, kid `scmtips-core-ed25519-standin-…`, claims incl. `roles` (core role keys), `permissions`, `email`, `device_id`), `wearable`, `user`, `capabilities`; 401 `invalid_credentials`, 403 `pairing_required` (strict mode), 429 `too_many_attempts`; `device_model` is a label `^[A-Z0-9_]+$`, at most 40 |
| `GET /v1/core/jwks.json` | the stand-in key and the legacy dev key |
| `GET /v1/core/devices/{device_id}/status?tenant_id=` | `{device_id, status, fingerprint, last_seen_at}`; unknown device or other tenant: `revoked` |
| `POST /v1/wearable/sessions` | ARO pairing: one-time code -> device token |
| `GET /v1/wearable/next` | the decision waiting longest (`item: null` when none, or for a user without `voice.approve`) |
| `GET /v1/briefs/{kind}/{subject_id}?format=spoken\|card` (kind `decision`, `signal`; needs `decision.read`) | the core's brief document `{kind, subject_id, format, text, template_text, source, facts{}, check{}, characters, words, seconds, simulated}` (templates only: `source` is `template`) |
| `POST /v1/briefs/decision/{id}/check` `{text}` (needs `decision.read`) | `{accepted, reasons[], template_text}`: accepted only if every number in the text (digits and number words) is in the template |
| `POST /v1/voice/challenges`, `POST /v1/voice/commands` | single-use nonce, grammar intents (approve option X, reject [because …], confirm, cancel, repeat, details), mandatory confirm turn, `Idempotency-Key` replay; as the real core answered Field's smoke (31 Oct): `pending` is `{intent, option_id, letter, reason, review_at, readback}`, decision statuses `PENDING_APPROVAL` / `APPROVED` / `REJECTED`, every turn but the executed one issues the next, 404 `voice_challenge_unknown` / 409 `voice_nonce_replayed` / 410 `voice_challenge_expired`, and 409 `voice_not_actionable` for a decided decision |
| `GET\|POST /v1/auth/step-up` | phone step-up bound to the device session, fresh for 5 minutes |
| `POST /v1/evidence/photos` (multipart) | metadata and a digest only; the image bytes are not kept |
| `GET /v1/wearable/sessions`, `DELETE /v1/wearable/sessions/{id}` | the user's device sessions: an array of `{id, device_id, device_model, display_capable, current, created_at, expires_at, last_seen_at\|null, revoked_at\|null}` (revoked ones stay listed) |
| `POST /v1/inbound/feeds/{feed_id}` | signed feeds: body `{"rows": [...]}`, `X-SCMTIPS-Timestamp` within 5 minutes, `X-SCMTIPS-Signature: sha256=<hex HMAC-SHA256(secret, timestamp + "." + raw body)>`; rows checked against the exchange contract's `inventory` / `open_supply` columns and recorded (upsert view; an open-supply line is `(kind, ref, item_code)`); the same body within 10 minutes answers **409 `duplicate`** (by body hash; `Idempotency-Key` is ignored, as the core does) |

Every call after sign-in carries `Authorization: Bearer <wearable token>` and `X-Device-Id`; the token works only
with the device id it was issued for. Every state-changing route (each POST and DELETE above, the feeds and the brief
check included) answers **403 `missing_requested_with`** without `X-Requested-With: lr`, as the real core does; the
GET routes do not need it. Errors are RFC 7807 problem documents with a `code`.

Dev-only helpers (no core equivalent): `POST /_standin/pairing-codes {email}`, `POST /_standin/devices/{id}/revoke`,
`POST /_standin/decisions/reset`, `GET /_standin/feeds/pushes`, `GET /_standin/feeds/state`, `GET /_standin/info`.

**Demo users** (tenant `FAKE_CORE_TENANT_ID`; the dev stack passes its demo tenant):

| E-mail | Roles | Permissions | Capabilities |
|---|---|---|---|
| `approver@demo.scmtips.test` | `approver` | `voice.approve`, `decision.read`, `evidence.upload` | approve_decisions |
| `operator@demo.scmtips.test` | `procurement` | `field.operate`, `evidence.upload` | field_operator |

Roles are **core role keys**, as the real core issues them (it has no "warehouse operator" role; its demo operator
is a `procurement` member). field-api maps them to Field roles with `FIELD_CORE_ROLE_MAP` (default: `approver` ->
`field.supervisor`, `procurement` -> `field.operator`; see `services/field-api/src/field_api/auth/core_roles.py`).

The password is `FAKE_CORE_DEMO_PASSWORD` (a dev value; `stack up` prints the default), the step-up code
`FAKE_CORE_STEP_UP_CODE`. Feeds: `FAKE_CORE_INVENTORY_FEED_ID` / `FAKE_CORE_SUPPLY_FEED_ID` (default
`standin-inventory`, `standin-open-supply`) with the secrets `FIELD_CORE_INVENTORY_FEED_SECRET` /
`FIELD_CORE_SUPPLY_FEED_SECRET` from `.env.local`.

**SAMPLE decisions:** rare-earth magnet export curbs. (1) expedite air freight (A) vs. qualify an alternate supplier
(B), approval band over USD 15,000 with the phone step-up; (2) raise the magnet buffer (A) or keep it (B), no step-up.

State lives in process memory: a restart forgets sessions and pushes and makes a new signing key (as the core does
locally without `LR_CORE_SIGNING_KEY`).

### Where the stand-in assumes a shape

Neither the handover nor the core's reply gives these; the stand-in chose them and Field must not depend on more
than those documents say: what `facts{}` and `check{}` of a brief hold inside (the core gave only the keys), the
`seconds` estimate (words / 2.5), the exact `say` texts, the step-up and backup codes, and the 200 feed answer
(`{accepted, rows, duplicate}`).
