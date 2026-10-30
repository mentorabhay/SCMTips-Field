# M2 jobs contract — phone app, console and backend (Warehouse + Tower)

**Status:** binding for the M2 build pass (owner choice 31 Oct 2026: "Warehouse + Tower"). The design
is the canvas "SCMTips Field — whole application prototype"
(https://claude.ai/artifact/WKYK77q2vwWe9erbsT3YvA): one job runner (go → scan → confirm → done) for every job.
The spec (`Plan/scmtips-field-spec.html`, extracts in `docs/SPEC/phase*/`) stays the reference for rules,
error codes and copy; where this file narrows or changes the spec it says so.

Everything here runs end to end on the owner's PC: phone ↔ field-api ↔ worker ↔ erp-sim (S/4-shaped
simulator). Nothing is "simulated" inside the app or field-api: erp-sim is reached only through ErpPort.

## 1. Rules for every client call

- Auth as today: pairing QR → core (fake-core) token → `POST /v1/auth/exchange` → field token; device
  registered with `POST /v1/devices`. Every route needs a token (tools/checks/route_auth.py).
- Every write carries `Idempotency-Key` (UUIDv7). Retrying the same key returns the first result.
- Posting to SAP is asynchronous: the request returns 202, the result arrives as a live event (§5).
- Errors are problem+json with `code` (FIELD-…) and a plain-English `title` the phone may show as is.

## 2. Task list

`GET /v1/tasks?site_id=&status=open,in_progress&type=` (status and type accept comma lists).
Operators see tasks for their sites; supervisors see all.

```json
{"items": [{
  "id": "uuid", "type": "receive|putaway|pick|count|audit|swap", "status": "open|in_progress|awaiting_posting|awaiting_approval|done|failed",
  "title": "Delivery 1800000022", "subtitle": "From SAMPLE-VENDOR-01 · 2 items · 36 pieces",
  "ref_doc_no": "1800000022", "reason": null, "due": null, "site_id": "uuid", "version": 3,
  "lines": [{
    "id": "uuid", "line_no": 10, "material": "SAMPLE-MAT-0001", "description": "Industrial Component Grade 1",
    "uom": "EA", "bin": "03-05-02", "expected_qty": 12, "counted_qty": 0,
    "position": null, "expected_serial": null, "status": "open|counted|confirmed|flagged|done", "version": 1
  }]
}], "next_cursor": null}
```

- `count` tasks never include `expected_qty` / `counted_qty` (blind count, FR3.029). `reason` is set for a
  recount ("Requested by an exception case: count differed from the books").
- `putaway` lines: one per material received, `bin` = the suggested bin, `expected_qty` = quantity to store.
- `pick` lines: one per stop in walking order, `bin` + `material` + `expected_qty`.
- `audit` (tower sector audit) lines: one per expected unit, `position` ("Sector A · slot 2"),
  `material`/`description` (equipment class) and `expected_serial`.
- `swap` lines: exactly one, `position` + `expected_serial` (the unit to remove) + `material`.

## 3. Line progress

| Call | Used by | Notes |
|---|---|---|
| `POST /v1/count-records` `{task_line_id, value, unit, source: manual\|scan\|voice, voice_event_id?}` | receive, pick, count | exists |
| `POST /v1/tasks/{task_id}/lines/{line_id}/confirmations` `{kind: bin\|product\|hu\|serial, code, source}` | putaway (bin), pick (bin, product), audit (serial), swap (old/new serial) | **new**. 200 `{ok: true, line_status}`; a wrong bin/product is 409 `FIELD-TASK-409-WRONG-CODE` with a title like "That is bin 03-05-01. Go to 03-05-02." For audit, any captured serial is accepted: 200 `{ok: true, match: true\|false}`; mismatches feed the console. For swap, `kind: serial` with `{role: old\|new}` in an optional `role` field. |
| `POST /v1/tasks/{task_id}/lines/{line_id}/flags` `{flag: missing\|damaged\|short, reason?}` | all | exists; `short` for pick |

## 4. Finish a job

`POST /v1/tasks/{task_id}/post-requests` — two-step confirmation, touch or voice:

```json
{"operation": "post", "lines": ["line-uuid", "..."], "staged_hash": "<sha256 as today>",
 "confirm": {"method": "touch"}}
```
or `"confirm": {"method": "voice", "post_voice_event_id": "...", "confirm_voice_event_id": "..."}`.
The old top-level `post_voice_event_id` / `confirm_voice_event_id` stay accepted (backward compatible).
"touch" means the operator saw the review screen and pressed "Yes, post it"; `staged_hash` proves it was
exactly these lines and quantities.

| type | What happens | 202 body `status` | Live event |
|---|---|---|---|
| receive | goods receipt 101 to erp-sim (as today); then the worker creates a **putaway** task for what was received | `queued` | `erp.posted` then `task.assigned` (putaway) |
| putaway | lines marked stored in their bins (SAP IM has no bins: field-side stock by bin, no SAP posting) | `completed` | `task.completed` |
| pick | goods issue 601 for the outbound delivery in erp-sim | `queued` | `erp.posted` |
| count | within tolerance: difference posted through the PI document (701/702) in erp-sim; beyond tolerance: an approval request for the console, no posting | `queued` or `awaiting_approval` | `erp.posted` or `count.awaiting_approval` |
| audit | findings reconciled; mismatches/missing go to the console Decisions queue; nothing posts to SAP | `completed` | `task.completed` |
| swap | dismantle old + install new serial through the tower equipment queue in erp-sim | `queued` | `erp.posted` |

## 5. Live events (`GET /v1/devices/{device_id}/events`, SSE as today)

`erp.posted {task_id, doc_number, doc_year}` · `erp.failed {task_id, message}` · `task.completed {task_id}` ·
`count.awaiting_approval {task_id}` · `task.assigned {task_id, type, title}`.

## 6. Tower visit and safety (existing endpoints)

- Check in: `POST /v1/sites/{site_id}/visits` (permit_ref, permit_valid_until, lat, lon, accuracy_m, …);
  check out: `PATCH /v1/visits/{visit_id}` `{unsynced_count}`.
- Climb-safe: `POST /v1/climb-sessions/{visit_id}/events` `{events: [{device_seq, type, occurred_at, payload}]}`
  with types `harness_confirmed`, `climb_safe_activated`, `checkpoint_reached` (payload `{level}`), `climb_safe_released`.
- Safety heartbeat: `POST /v1/safety/visits/{visit_id}/check-in`.

## 7. Console (supervisor) endpoints

`GET /v1/tasks` (all sites) · `GET /v1/posting-queues` · `POST /v1/posting-jobs/{id}/retry` ·
`GET /v1/devices` · `POST /v1/devices/{id}/revoke` · `GET /v1/system/status` · `GET /v1/safety/active-visits` ·
`POST /v1/safety/visits/{id}/ack` · `GET /v1/mismatches` · `POST /v1/mismatches/{id}/decision` ·
**new** `GET /v1/approval-requests?status=pending` (count differences awaiting a decision) ·
`POST /v1/approval-requests/{id}/decide` (exists) · **new** `POST /v1/tasks/{task_id}/recount` (creates a
recount `count` task with `reason`) · `GET /v1/audits/{task_id}/progress`.
Dev sign-in for the console: fake-core issues a supervisor token (dev stack only), exchanged as above.

## 8. Test data on the PC (tools/dev_stack/stack.py)

| Command | Creates |
|---|---|
| `delivery` | inbound delivery in erp-sim → worker imports a **receive** task (exists) |
| `outbound` | outbound delivery in erp-sim → worker imports a **pick** task |
| `count [BIN]` | a **count** task for a bin of the SAMPLE site |
| `tower` | tower site SAMPLE-TWR-0001 with installed equipment in erp-sim, a sector **audit** task and a **swap** task |
| `smoke --all` | drives every job type through the real HTTP API as the phone would, and checks the SAP documents |

The SAMPLE warehouse gets a small bin tree (zones 02 and 03, e.g. 02-01-01, 02-03-04, 03-05-01, 03-05-02)
so put-away and pick have real bins.
