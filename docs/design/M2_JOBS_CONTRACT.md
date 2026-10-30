# M2 jobs contract — phone app, console and backend (Warehouse + Tower)

**Status:** binding for the M2 build pass. *As built* notes (backend, 31 Oct 2026) record where the backend differs
from or details the original text (owner choice 31 Oct 2026: "Warehouse + Tower"). The design
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
  "id": "uuid", "type": "receive|putaway|pick|count|audit|swap",
  "status": "open|in_progress|awaiting_posting|awaiting_approval|done|failed|cancelled",
  "title": "Delivery 1800000022", "subtitle": "From SAMPLE-VENDOR-01 · 2 items · 36 pieces",
  "ref_doc_no": "1800000022", "erp_ref": "1800000022", "reason": null, "due": null, "site_id": "uuid", "version": 3,
  "updated_at": "2026-10-31T10:00:00+00:00", "completed_at": null,
  "lines": [{
    "id": "uuid", "line_no": 10, "material": "SAMPLE-MAT-0001", "description": "Industrial Component Grade 1",
    "uom": "EA", "bin": "03-05-02", "expected_qty": 12, "counted_qty": 0,
    "position": null, "expected_serial": null, "status": "open|counted|confirmed|flagged|done", "version": 1
  }]
}], "next_cursor": null}
```

- `count` tasks never include `expected_qty` / `counted_qty` (blind count, FR3.029). `reason` is set for a
  recount ("Requested by an exception case: count differed from the books").
- *As built:* `status` and `type` accept comma lists; status accepts the contract words above (and the stored
  words pending/posting/completed for older clients); an unknown word is 422. A recount supersedes its count, which
  shows `cancelled` (not in the original list). `erp_ref` = `ref_doc_no` (pre-M2 name, kept). Every non-count line
  carries `counted_qty` (for pick: the picked quantity; putaway/audit/swap: 0). Subtitles: receive "From <supplier> ·
  n items · m pieces", putaway "Goods receipt <doc> · …", pick "For <ship-to> · n stops · m pieces", count "PI <doc> ·
  n items · blind count", audit "<tower> · n units", swap "<tower> · remove <serial>". `material` for audit/swap lines
  is the installed equipment's material, `description` its class (e.g. RRU). Pick lines are listed in walking order
  (bin code order); `line_no` stays the delivery item number. Putaway `ref_doc_no` is the GR material document.
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

*As built (§3):*
- count-records: 201 `{id, line_id, counted_qty, source, version}`, plus `picked_qty` on pick lines. On a count line
  a recount by an earlier counter is 409 `FIELD-PI-409-RECOUNT-SAME-OPERATOR`; round 3 needs an inventory controller.
- confirmations body `{kind: bin|product|hu|serial, code, source: scan|voice|manual (default scan), role?: old|new,
  reason?}`; 200 `{ok: true, line_status, match?}` (+ `bin`/`divergent` for putaway, `bin`/`product` for pick). Codes
  are compared trimmed and upper-cased. Every 409 is `FIELD-TASK-409-WRONG-CODE` with a title the phone shows as is:
  putaway "That is bin X. Go to Y." / "X is not a bin here. Go to Y." (another real bin is accepted with
  `reason: bin_full|rack_damaged|other`); pick "Scan bin Y first.", "That is bin X. Go to Y.", "That is X. Pick M.";
  swap "That is unit X. The unit to remove is Y.", "Scan the unit you remove first (Y).", "That is the unit you are
  removing. Scan the new unit.", "Unit X is already installed at <slot>.". A bin under an open posting-blocked count
  is 423 `FIELD-PI-423-POSTING-BLOCKED`. Swap `role` defaults to old, then new.
- flags `{flag: missing|damaged|short|under, reason?}` (`reason_code` still accepted). missing: reasons not_found
  (default) / removed_by_other / inaccessible, line becomes `flagged`. short on pick: an FR3.020 code or free text
  ("picked 2 of 4"); short/under on receive: the under-delivery reasons. damaged (receive) still needs capture evidence
  and qty.

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

*As built:* `staged_hash = sha256("|".join(sorted(f"{line_id}:{qty:.3f}")))` over the request's lines, where qty is
the server's counted_qty for receive and count, picked_qty for pick (= the `counted_qty` the list shows and the
`picked_qty` the count-record answer returns), and counted_qty (0) for putaway, audit and swap: the phone hashes the
`counted_qty` the task list reported, 0 if absent. Voice may send the turn ids inside `confirm` and/or at the top
level (the phone sends both). The 202 body is `{task_id, type, confirm_method, posting_request_id, status, ...}`;
`posting_request_id` is null for `completed` and `awaiting_approval`; `awaiting_approval` adds
`approval_request_id`; audit adds `reconciliation {matched, serial_mismatch, tower_only, erp_only, misplaced,
completeness}`; putaway adds `stored [{line_id, bin, qty}]`. Finishing an already finished / posting / awaiting task
is 409 `FIELD-TASK-409-STATE`. Count: all lines of the task must be in the request; "tolerance" = FR3.031 (2 % or
value 25 000) or the document value above FIELD_PI_APPROVAL_VALUE (FR3.034). Pick: lines with a picked quantity need
bin and product scans first (409). Putaway: every listed line needs its bin scan. Audit: every line scanned or flagged
missing; missing lines stay `flagged`. Swap: old and new serial scanned.

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

*As built:* each event is `{id, kind, payload, created_at}`; payloads also carry `erp_document_id`, erp.posted adds
`doc_type` and `fiscal_year`, erp.failed adds `error_class` (posting queue). task.assigned (after a GR) carries the
new put-away task's id; it goes to the device that posted the receive. A swap's erp.posted carries the SAP change
document as `doc_number`. Events go to the device of the token that finished the job; a count approved later by the
console, and a recount, produce no device event (the phone sees them in the task list). Polling
`?once=true&last_event_id=` works as before.

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

*As built:*
- `GET /v1/approval-requests?status=pending[,approved,rejected,cancelled]&site_id=` (field.discrepancy.approve;
  operators get 403): `{items: [{id, task_id, title, bin, material, description, uom, book_qty, counted_qty,
  difference_qty, value_abs, currency, band, recount_count, requested_by, excluded_principals, sod_note, can_decide,
  created_at, type, status, task_type, site_id, task_status, reason, lines: [{line_id, bin, material, description,
  book_qty, counted_qty, difference, uom}]}], next_cursor}`. material/description/uom are null when the document has
  several items; book/counted/difference are then sums.
- `POST /v1/tasks/{task_id}/recount` `{reason?}` (field.recount.assign) → 201 `{task_id, recount_of, count_round,
  reason, status: "open", requested_at}`. Only for a count that is awaiting_approval or in progress; the old task and
  its PI document are cancelled and their pending approval request becomes `cancelled`. Round > 3 is 409.
- `GET /v1/posting-queues/{key}/jobs` items add `last_error`. `GET /v1/mismatches` items add `captured_by`.
  `POST /v1/safety/visits/{id}/ack` needs `field.visit.ack` (now held by field.supervisor).
- `GET /v1/audits/{id}/progress` adds `percent` (null for an empty scope) and `expected_count`; `site` stays 1.0 with
  `empty_scope: true` for an empty scope, because FR4.024 defines it so.
- CORS: explicit origins from FIELD_CONSOLE_ORIGINS (default http://localhost:3000,http://127.0.0.1:3000); "*" is
  refused at start-up.
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

*As built:* bins 02-01-01, 02-01-02, 02-02-01, 02-02-02, 02-03-04, 02-03-05, 03-05-01, 03-05-02, 03-05-03, 03-06-01,
03-06-02, 03-07-01 (created through POST /v1/locations). Once per site an opening balance puts today's SAP stock of
SAMPLE-MAT-0001..0004 into 02-01-01, 02-03-04, 03-05-01, 03-05-02 (field.bin_stock; SAP IM has no bins). `count`
creates the count through POST /v1/pi-documents without book quantities (the server snapshots field.bin_stock).
`tower` writes SAMPLE-TWR-0001 (sectors A, B; slots S1-S3, S1) with an RRU per slot and one spare into erp-sim,
creates the field tower site, mirrors FLs and equipment through the SAP readers, and creates a sector A audit and a
swap of slot A-S3. `smoke --all` drives receive (voice) → putaway → pick (short) → count within tolerance → count
beyond tolerance → recount by a second operator → approval → tower visit (check-in, climb events, heartbeat) → audit →
check-out → swap, with the phone's exact request shapes, and checks erp-sim documents, stock and equipment.
The smoke uses erp-sim stock as its reference for the blind counts, so it needs field bin stock and erp-sim stock in step
(a fresh stack; an erp-sim `/_sim/reset` alone breaks that).
