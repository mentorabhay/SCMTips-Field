# SCMTIPS exchange contract (scmtips.exchange/v1)

Generated from the SCMTIPS core on 2026-10-31T09:32:41Z. Do not edit by hand.

Every message SCMTIPS trades with your other systems has **one format and two transports**:

- **Live:** a JSON message (the `schemas/*.schema.json`, JSON Schema draft 2020-12) pushed
  over HTTPS or pulled by SCMTIPS.
- **File:** the XLSX template (`templates/*.xlsx`) with the same columns, uploaded in
  SCMTIPS. A file is read into the same message as a live push and checked by the same
  rules. Its rows are labelled SIMULATED wherever they appear.

## The envelope

| Field | Required | Meaning |
|---|---|---|
| `contract` | yes | Always `scmtips.exchange/v1`. |
| `message` | yes | The message key, e.g. `planning_result`. |
| `message_id` | yes (live) | Your unique id, the idempotency key: a repeat changes nothing. |
| `correlation_id` | no | The SCMTIPS decision id the message answers (audit trail). |
| `source_system` | no | Your system, a short lower-case name. |
| `sent_at` | no | ISO 8601 with a time zone. |
| `simulated` | no | `true` for test data. |
| `rows` / `parts` | yes | The rows; the ERP extract has `parts` with one array per table. |

A file without a `message_id` uses the hash of its bytes, so the same file twice counts once.
Rows whose `decision_id` differs from the `correlation_id` are rejected.

In the XLSX template the envelope is the `Message` sheet, and the rows go on the sheet named
after the table. The `Columns` sheet explains every column; the `Example` sheet shows a row.

## Signing live pushes

Every push to SCMTIPS carries:

- `X-SCMTIPS-Timestamp`: Unix seconds, within 5 minutes of SCMTIPS's clock;
- `X-SCMTIPS-Signature`: `sha256=` + hex HMAC-SHA256 of `timestamp + "." + raw body`, with the
  secret SCMTIPS showed once when the connection was made.

SCMTIPS signs what it sends you the same way.

## Values

- Codes (items, sites, suppliers) are the SCMTIPS codes, upper case.
- Dates are `YYYY-MM-DD`; date-times are ISO 8601 with a time zone; months are `YYYY-MM`.
- Numbers use a dot as the decimal separator. Lists in a file are separated by semicolons.
- Columns SCMTIPS doesn't know are ignored and reported as warnings.

## Messages

| Message | Direction | Leg | Tables | File import |
|---|---|---|---|---|
| `signal` (Signal) | to SCMTIPS | I1 | `signal` | yes |
| `planning_request` (Planning request) | from SCMTIPS | I2 | `planning_request` | yes |
| `planning_result` (Planning result) | to SCMTIPS | I3 | `planning_result` | yes |
| `decision_outcome` (Decision outcome) | from SCMTIPS | I4 | `decision_outcome` | no |
| `work_order` (Work order) | from SCMTIPS | I6, I8 | `work_order` | yes |
| `progress` (Progress) | to SCMTIPS | I7, I8 | `progress` | yes |
| `erp_extract` (ERP extract) | to SCMTIPS | I9 | `inventory`, `open_supply`, `bom` | yes |
| `goods_receipt` (Goods receipt) | to SCMTIPS | I10 | `goods_receipt` | yes |

What SCMTIPS does with each message today (this list changes as each leg is built):

- `signal`: Being built (A3). Today news reaches signals through the source registry.
- `planning_request`: Being built.
- `planning_result`: Being built (A4).
- `decision_outcome`: Being built: the export for the record.
- `work_order`: Published by the release to execution (dataset execution_orders), these columns.
- `progress`: Live: applied by POST /v1/execution/inbound/{target_id}, one row per signed call. File mode: being built (A5).
- `erp_extract`: Applied by the data import (POST /v1/imports) and the data feeds (POST /v1/inbound/feeds/{id}), one table per call. Message upload: being built (A8).
- `goods_receipt`: Live: the ERP pushes the two rows it becomes to the inventory and open-supply feeds. File mode: being built (A7).

**The decision outcome is never imported.** An approval read from a spreadsheet would skip the
step-up and the audit chain. Approvals happen in SCMTIPS (web, phone or glasses); the outcome
is exported for the record.

## Checking a message

`POST /v1/exchange/messages/{key}/validate` (JSON) and `/validate-file` (XLSX or CSV) answer
how SCMTIPS reads your message (envelope, rows, errors with row and column) and store nothing.
