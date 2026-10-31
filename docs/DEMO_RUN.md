# The 3-minute demo run: one command for both sides

`tools/dev_stack/demo_run.py` (ledger row M4-C17; the core's item Q15) prepares the SCMTIPS core and SCMTips Field
the same way, then plays the run's beats. Each beat is checked, timed and printed with what to show. The run stops
with exit code 1 at the first beat that fails and prints that beat's recovery. It never prints a result it did not
check. Every figure is SAMPLE data (the drone OEM of the core's `samples/manufacturing-v1`), and the scenario is a
SIMULATED signals workbook.

The beats follow section 1 of the hackathon plan ("What the judges see"). Beats 0 to 3 prepare both sides (about
40 s); beats 4 to 6 are the part the video shows (about 30 s of machine time); beat 7 prints the screens.

**Proven where:** twice in a row against the real core in the Field session's Linux container, 1 Nov 2026 (log:
`docs/evidence/runs/2026-11-01-k5-demo-run.txt`). **Not run** on the owner's PC, on his kit (`<workspace>\ARO`), with the
phone or with the glasses: there, the approver and the warehouse operator are Field's Python smokes over HTTP, the
same API calls the app makes.

## Prerequisites

| What | How | The run checks it |
|---|---|---|
| The core checkout on a branch with `scmtips-demo` and `scmtips-scenario` (the core's integration branch, core commits ff2d4f8 and 6ad31c5 or later) | the owner's kit in `<workspace>\ARO` may run an older branch: moving it needs his OK (A-05) | the exports and the scenario pack exist |
| The core's API (:8000) and worker (:8001) running with hosted demo mode on | core `docs/DEMO_MODE.md`: `LR_STRICT_AUTH=true`, `LR_DEMO_MODE=true`, `LR_DEMO_TENANT_ID=<the SAMPLE organisation>` for the API, the worker **and** the shell that runs the run (the core's CLIs read them), then `uv run scmtips-demo mark` once | `GET /v1/health`, `:8001/healthz`, `scmtips-demo status` (demo mode on, organisation marked) |
| The core's demo team and the two webhook feeds | `uv run scmtips-local-demo --with-team`; the feeds made by the Data and integration owner (core `docs/DATA_FEEDS.md`) | indirectly (beats 1, 3, 6) |
| Field's stack up against the real core | `.\scripts\dev\run-field-stack.ps1 up` with `FIELD_CORE_TARGET=core` and the core's URLs, the feed URLs and secrets and the `FIELD_CORE_SMOKE_*` members in Field's `.env.local` (names in `.env.example`) | field-api, erp-sim, field-worker alive; `FIELD_CORE_TARGET=core` |
| `FIELD_CORE_SNAPSHOT_TENANTS=<the core's SAMPLE organisation id>` in Field's `.env.local`, then `stack down` and `stack up` | the two feeds belong to that one organisation. Without this, the worker's snapshot also reads the drone plants for every other Field tenant with a site on them (tests make some), and their older rows reached the core after its reset (K5) | exactly that tenant, and no pending feed rows of another tenant |

## The one command

```powershell
# Windows, PowerShell 7, in <repo> (or double-click scripts\dev\demo-run.cmd with SCMTIPS_CORE_DIR set)
.\scripts\dev\demo-run.ps1 <the core checkout>
```

```bash
# Linux / macOS
scripts/dev/demo-run.sh <the core checkout>
# = uv run python -m tools.dev_stack.demo_run --core <the core checkout> [--scenario magnet-export-curbs]
#   [--po PO-26-1002] [--web http://app.localhost:3100] [--wait 120]
```

The transcript and a JSON summary (beats, checks, seconds, both git SHAs, the decision id) go to `var\demo-run\`
(git-ignored). `scmtips-local-demo` prints the kit's demo passwords, so its output is never shown or logged.

## The beats

Times are from the two K5 runs (run A / run B, in seconds). "Live" and "file / fallback" follow the plan's table.

| # | Beat (plan beat) | What runs and what is checked | s | Show | Say (one line) | Live / file or fallback |
|---|---|---|---|---|---|---|
| 0 | Preflight | the core's API, worker and demo mode; Field's services; `FIELD_CORE_TARGET`, `FIELD_CORE_SNAPSHOT_TENANTS`; no stray feed rows | 11.7 / 6.3 | nothing | - | - |
| 1 | Core reset (set-up) | waits until no Field feed row for the core is pending; `uv run scmtips-demo reset`; `uv run scmtips-local-demo --with-team`; the core's PO-26-1002 is open again | 15.6 / 14.8 | `/home` with the SAMPLE banner | "A drone maker's SAMPLE plant, reset to its seeded state." | live: the CLI. Fallback: `POST /v1/demo/reset`, or the nightly reset |
| 2 | Field seed (set-up for 6) | `stack seed-core-export <core>\samples\exports\erp-sim --reset`: earlier GRs against the export's PO lines cancelled (erp-sim's own item cancel), stray PO lines and stock in its plants removed, the export loaded, an ASN for each PO line with open quantity, the site pack's sites; erp-sim holds an open ASN for PO-26-1002 | 0.9 / 0.7 | erp-sim `http://127.0.0.1:8002/_sim/ui` (stock, the open ASN) | "The ERP holds the same SAMPLE world as the core." | only this path |
| 3 | ERP snapshot (6, leg I9; 7) | `stack smoke --erp-feed`: every stock row and open PO line of erp-sim, signed, to the core's two feeds; the core's on-hand and PO lines equal erp-sim's (repeated until the core has committed) | 17.8 / 24.8 | `/data/pipeline`, `/data/systems` (the ERP card) | "Stock and open purchase orders come from the ERP, signed." | live: Field's worker. File: the ERP extract through `POST /v1/exchange/messages/erp_extract/import-file` |
| 4 | Disruption (1 and 2) | `uv run scmtips-scenario inject magnet-export-curbs --wait`: the core's file-mode signal import, relevance gate, scoring, exposure cascade, starvation clock, auto-drafted decision, the core's brief check; nothing unmet | 10.0 / 11.4 | `/signals` (the SIMULATED magnet-curbs signal), `/exposure` (CP-204 -> SA-120 -> FG-100, FG-200; clock CP-206 about 87 d, CP-204 about 129 d) | "Only a signal that touches our suppliers and parts becomes a decision." | live in the plan: the market-intelligence pull (not part of this run). File: the signals workbook, labelled SIMULATED (what this run uses) |
| 5 | Approval by voice (4) | `stack smoke --approver --decision <beat 4's decision>`: sign-in, exchange, spoken brief (the core's template; Muse when a key is set), the core's number check, "approve option two", read-back, replay rules, "confirm"; the core's decision EXECUTING | 2.6 / 2.0 | glasses POV or the phone; then `/decisions/<id>` (EXECUTING, audit) | "The approver hears a short brief and says approve option two; the core checks every number first." | live: the Field app with the glasses (not yet proven). Fallback: the core's phone approval page. The HUD simulator (F5) is not built. No Excel approval, by design (plan D3) |
| 6 | Goods receipt, the finale (6) | `stack smoke --core` with `FIELD_CORE_SMOKE_PO=PO-26-1002`: the ASN as a receive job, counted, GR 101 in erp-sim against the core's own PO, two signed feed rows, PO-26-1002 received at the core, CP-204 on-hand 1680 -> 3280 = erp-sim, a new base plan run is required | 18.5 / 16.5 | the phone's receive job (or erp-sim's documents), `/data/open-supply`, `/data/inventory`, `/exposure` | "The motors arrive, the ERP posts the receipt, and the core re-plans on that evidence." | live: Field -> erp-sim -> signed feeds. File: the goods-receipt file through `POST /v1/exchange/messages/goods_receipt/import-file` |
| 7 | What the judges see (7) | prints the URLs above for the core's web (`--web`, default `http://app.localhost:3100`) | - | `/data/systems` (modes, last sync, failures), `/settings/audit` | "Every system has a live and a file mode; switching one keeps the run going." | the live-to-file switch on the Connected systems page is done by hand in the video; the run does not do it |

Totals: run A 77.2 s, run B 76.6 s (exit code 0 both).

**Observed, not a check:** the starvation clock does not move on this receipt. PO-26-1002 was supply the plan
already had, so CP-204 stays at about 129 days with "recovery lands before" (as K1 saw). Say "the plan is re-run on
the receipt", not "the clock resets".

**Not in this run:** plan beat 3 (planning system, SangamIQ): the core has its `planning_request` and
`planning_result` templates and file validation, but no import of a planning result yet (Q7). Plan beat 5 (PMO and
shop floor, Heartbeat and the MES simulator): the core imports progress files; the recovery project and work orders
are not driven here (Q8). If the video shows them, label them as each product's own screen in file mode.

## Recovery when a beat fails

The run prints the failed beat, its last tool output and the line below. Fix it and run the whole command again:
beat 1 resets everything, so a rerun is always clean.

| Beat | Typical cause | Recovery |
|---|---|---|
| 0 | a service down; demo mode off; `FIELD_CORE_TARGET` or `FIELD_CORE_SNAPSHOT_TENANTS` not set | start the core kit with the demo settings, `run-field-stack.ps1 up`; in the core `uv run scmtips-demo status`, `uv run scmtips-demo mark` once |
| 1 | the worker is not running (the sample does not load again); feed rows still pending | start the core's worker; wait, or look at `field.core_feed_delivery` (pending rows) |
| 2 | erp-sim or field-api down; wrong export folder | `stack up`; the folder is the core's `samples\exports\erp-sim` |
| 3 | the feed secrets differ from the core's two feeds; field-worker stopped; another tenant's rows | compare the feeds on the core's Data feeds page with `.env.local` (names only); `FIELD_CORE_SNAPSHOT_TENANTS` |
| 4 | an older decision on the same signal is still open; the worker is slow | run again (beat 1 resets); `uv run scmtips-scenario inject <name> --wait` alone shows what is unmet |
| 5 | another decision waits first; the band asks for a step-up (strict sign-in) | run again; for strict sign-in set `FIELD_CORE_SMOKE_APPROVER_TOTP_SECRET` |
| 6 | no receive job appears (field-worker); the core did not re-plan within `--wait` | `stack seed-core-export <export> --reset`, then `FIELD_CORE_SMOKE_PO=PO-26-1002 stack smoke --core`; raise `--wait` |

For the video, every beat also has the file path above: if a live link fails on the day, show that beat in file
mode and label it SIMULATED.

## Where it lives

The orchestrator is in Field because four of its six beats are Field commands; it calls the core's CLIs in the core
checkout (`uv run --frozen ...`) and never copies core code. The core's `docs/DEMO_MODE.md` points here.
Launchers: `scripts/dev/demo-run.ps1`, `.cmd`, `.sh`. Tests: `tools/dev_stack/tests/test_demo_run.py`.
