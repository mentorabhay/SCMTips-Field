# M3 glasses-first: binding contract (owner amendment A-03, 31 Oct 2026)

Three tracks build M3 in parallel. This file is what they agree on; a track that needs to change it
says so in its report and does not change another track's side. The plan the owner approved:
"SCMTips Field: glasses-first plan (M3)" (Claude Docs); its essentials are restated here.

## 0. Goal in one paragraph

The glasses are the operator's interface; the phone is a pocket computer and fallback. An assistant
speaks through the glasses, knows the open work from the ERP, says what to look at next and what
"done" means, and scans by looking (barcodes read from the glasses video). A sandbox site mode lets
any real box at home become a material, a receipt line and a count line, with real documents in
erp-sim. The job engine (field-api tasks + server checks + posting queue + ErpPort) stays the single
source of truth: the assistant talks and routes; it never posts and never sees book quantities.

## 1. Tracks, branches, ownership

| Track | Branch / worktree | Owns |
|---|---|---|
| S sandbox + barcodes (WP1) | `feat/m3-sandbox` in `/home/claude/wt-m3-sandbox` | `services/erp-sim/**`, `connectors/**`, `field_api/codes/**`, `field_api/sandbox/**`, `field_api/jobs/confirmations.py` + task-list line fields, site `mode`, worker material/barcode sync, `tools/dev_stack/**`, migrations `field_0060_m3_sandbox`, `erpsim_0003_m3_barcodes` |
| A assistant + records (WP3, WP4, WP5 backend) | `feat/m3-assistant` in `/home/claude/wt-m3-assistant` | `field_api/assistant/**`, `field_api/ai/**`, `config/ai_pricing.yaml`, `tools/spikes/**`, worker retention job for assistant data, migration `field_0061_m3_assistant` |
| P phone + console (WP2, WP5 console) | `feat/m3-android` in `/home/claude/wt-m3-android` | `apps/field-android/**`, `apps/field-console/**` |

- All start from `slice/m3-glasses-first` (commit with this file). Commit messages: `type(scope): summary (IDs)`;
  scope without spaces; IDs `M3-S01`…, `M3-A01`…, `M3-P01`… (and spec task IDs where one applies).
- Migrations: `field_0060_m3_sandbox` has `down_revision = "field_0059"`. `field_0061_m3_assistant` ALSO uses
  `down_revision = "field_0059"` on its own branch; the integrator re-points it to `field_0060` at merge.
  erp-sim: `erpsim_0003_m3_barcodes` after `erpsim_0002`.
- Ledger: each track appends its entries to `docs/STATUS/m3.yaml` (same fields as phase ledgers:
  id, title, status, evidence, tests, frs, verified_at, note). Every M3 entry is at most `partial` until
  proven on the owner's phone and glasses. The integrator makes trace.py check this file.
- Binding rules (CLAUDE.md) apply in full: real gates, no orphans, no mocks/fakes/sims imported by production,
  mypy --strict, never weaken or skip a test, secrets by env-var name only (A-02).

## 2. Barcodes and site mode (track S provides; A and P consume)

- erp-sim: `erpsim.material_barcode(client, material_no, barcode, uom, is_main)`, PK `(client, barcode)`,
  modelled on SAP MEAN. Every existing SAMPLE material gets `barcode = material_no` so current labels work.
  The product read API exposes barcodes the way S/4 does (`to_ProductUnitsOfMeasureEAN`-like); the
  field side reads them through the connector, never straight from erp-sim tables.
- field: `field.material_barcode(tenant_id, material_id, barcode, uom)` synced from the ERP read;
  `field.site.mode text NOT NULL DEFAULT 'production' CHECK (mode IN ('production','sandbox'))`,
  changed only with `field.site.edit` by `field.admin`, audited. `GET /v1/sites` items carry `mode`.
- `GET /v1/codes/{code}?site_id=` (any field role with `field.task.read`) →
  `{"code", "kind": "material"|"bin"|"serial"|"unknown", "material": {"material","description","uom"}|null,
    "bin": str|null, "site_mode": "production"|"sandbox"}`.
- Task list lines (`GET /v1/tasks`) gain `"barcodes": [str]` = every barcode of the line's material
  (always includes nothing secret; may be empty). Confirmations `kind=product` accept the material
  number OR any of its barcodes; the line matches on either.

## 3. Sandbox actions (track S; refused on production sites with 403 `FIELD-SBX-403-PRODUCTION`)

- `POST /v1/sandbox/receipts {site_id}` → 201 `{task_id, ref_doc_no}`: an open inbound delivery in erp-sim
  with no items yet and the matching receive task in field, created at once (no worker wait).
- `POST /v1/sandbox/tasks/{task_id}/items {code, description, qty?}` (Idempotency-Key) → 201
  `{line_id, material, created_material: bool}`. Unknown code → new material `HOME-nnnn` in erp-sim with
  that barcode, then the line. Works on sandbox receive tasks (adds a delivery item; soft pegging: at post
  the delivery quantity is set to the counted quantity, then GR 101) and on sandbox count tasks (adds a
  count line for the bin).
- Opening stock: on a sandbox count, a counted material with no book stock posts movement 561 (initial
  entry) for the counted quantity instead of a PI difference. Production never posts 561 from the field.
- `stack home [--simulate-differences]`: creates site "Home (sandbox)" in mode sandbox with bins HOME-A,
  HOME-B, one empty home receipt and one count task for HOME-A, and prints how to pair to it
  (`stack pair --home`). `--simulate-differences` is opt-in and marks the documents it causes as simulated.
- erp-sim documents from sandbox sites carry `header_data.sandbox = true`; the simulator pages show it.

## 4. Field Assistant (track A provides; P consumes)

`POST /v1/assistant/turns` (permission `field.assistant.use`, granted to operator, technician, supervisor;
Idempotency-Key exempt like auth exchange is NOT allowed: send one)

Request:
```json
{"session_id": "uuid or null (null = start a session)", "site_id": "uuid",
 "event": "session_start|utterance|scan|unknown_code|photo|step_done|pause|resume|session_end",
 "text": "words heard, or null", "code": "scanned code or null",
 "photo_jpeg_b64": "≤ 1 MB JPEG or null",
 "client_state": {"task_id": "or null", "line_id": "or null", "step": "phone step name or null"}}
```
Response 200:
```json
{"session_id": "uuid", "say": "words to speak (≤ 2 sentences)", "card": {"title": "...", "body": "..."} ,
 "actions": [ {"type": "open_task", "task_id": "..."},
              {"type": "command", "command": "next|repeat|post|cancel|all_here|count", "value": 4},
              {"type": "refresh_task", "task_id": "...", "focus_code": "..."},
              {"type": "listen", "mode": "command|free"} ],
 "ai": "model|rules", "cost_usd": 0.0021}
```
- The phone executes `actions` through its own job runner; the server never changes a task's lines on
  the model's say-so, except sandbox `add item` (a tool that calls section 3 after the operator said yes).
- The server strips any action that would confirm a post: there is no `confirm` command. Posting still
  needs the operator's own "confirm" within 10 s, handled by the phone grammar and checked by the server.
- Model tools (server side): `list_work`, `task_detail` (count tasks: never book or expected quantities),
  `lookup_code`, `add_sandbox_item` (only after an explicit yes, only on sandbox sites), `session_summary`.
- `ai: "rules"`: when AI is off (`AI_CLOUD_ENABLED` not true, no key, budget refused, model error or
  timeout > 6 s) the same endpoint answers by fixed rules for: greeting + work list, "start <type or
  number>", "what's next", "how many left", "what is this" (code lookup only), unknown code in sandbox
  ("What is it?" then the next utterance is the name, then "How many?"), "summary". Work never stops
  because of the AI.
- Model: Meta Model API, `https://api.meta.ai/v1`, OpenAI-compatible chat completions, model
  `muse-spark-1.2` (Standard tier; `-contributor` ids are refused). Key from env `MODEL_API_KEY` only.
  Fallback provider Baseten (`BASETEN_API_KEY`, model id from config). Every call goes through the budget
  guard: new provider `meta`, cap `AI_BUDGET_META_USD`, prices in `config/ai_pricing.yaml`
  (muse-spark-1.2: input 1.25, cached input 0.15, output 4.25 USD per million tokens). A test double of
  the model (recorded responses) serves CI; it lives in test code only.
- Records: `field.assistant_session(id, tenant_id, site_id, principal_id, device_id, mode, started_at,
  ended_at)` and `field.assistant_turn(id, session_id, at, event, heard, said, actions jsonb, tool_calls jsonb,
  code, photo_ref, ai, cost_usd, latency_ms)`, RLS forced like every field table. Heard/said/photos are
  purged after 30 days by the worker. Supervisor reads:
  `GET /v1/assistant/sessions?site_id=&limit=` → items `{id, site_id, principal_id, mode, started_at,
  ended_at, turns, documents: [doc numbers], cost_usd}`; `GET /v1/assistant/sessions/{id}` → session +
  `turns[]`; `GET /v1/assistant/sessions/{id}/export.csv`.
- `stack assistant-check` (track A adds it to the dev stack command list via a small hook file it owns:
  `tools/dev_stack/assistant_check.py`, registered by track S's stack.py with one line) makes ONE real
  model call through the budget guard and prints `assistant-check: OK model=… latency_ms=… cost_usd=…` or
  `BLOCKED <reason>` (never the key).

## 5. Phone and console (track P)

- Work session: a foreground service started from Today ("Start work" — the one big button) and
  automatically when glasses connect; the microphone listens continuously during the session through the
  glasses (Bluetooth SCO/HFP), paused when the DAT session pauses (glasses tap / taken off) and resumed after.
- Utterance routing: the existing JobGrammar first while a job is open; anything it does not parse, and
  everything outside a job, goes to `POST /v1/assistant/turns`; the reply's `say` is spoken and its
  `actions` executed. The session greeting is the `session_start` turn.
- Scan by looking: the DAT video stream (low fps) is decoded with ML Kit on the phone; a scan = the same
  code in 2 consecutive frames; the same code is not re-reported within 3 s. The capture button and
  "what is this" take a full photo.
- Line matching uses material OR `barcodes`. An unknown code on a sandbox site → `unknown_code` turn with a
  photo; on a production site → refused as today.
- Audio first when glasses are connected (prompts spoken, the screen mirrors).
- Console: Sessions page (list, detail with turns, photos, documents, CSV link), sandbox badges on sites
  and warehouse pages.

## 6. Done for M3 (integration)

All gates green, `smoke --all` passes, a new `smoke --home` passes (sandbox receipt with a never-seen barcode
→ GR 101 with a HOME material; production site refuses the same code; sandbox count with 561), assistant
endpoint answers in rules mode with AI off and through the recorded model double in CI, CI green including
the emulator launch. Then the owner tests on glasses; only then may entries move toward done.
