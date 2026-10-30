# SCMTIPS Field Latency Baseline & Budget Report (Task T1.068 / FR1.059 / FR1.060)

**Revised:** 2026-10-30 (C0 correction, see the internal review of 30 Oct 2026 §3.14)

> **Retraction.** The 2026-10-27 version reported "measured" p50/p95 values for glasses→phone BLE transfer, on-device ML Kit, HUD ack and k6 probe throughput. None could have been measured: no glasses were used, the Android app had never been built, and no raw measurement files were committed. All figures are withdrawn and the old text remains in git history (`dfea392`).

**Rule for this file:** a "Measured" cell may be filled only when the raw data file (k6 JSON summary, device trace, logcat export) is committed under `docs/perf/raw/` and the row links to it.

| Segment | BRIEF target p95 | Measured p50 | Measured p95 | Raw data | Status |
|---|---|---|---|---|---|
| Glasses → phone still transfer (DAT) | — (part of 800 ms shutter-to-ack) | — | — | — | NOT MEASURED |
| On-device barcode/text (ML Kit) | — | — | — | — | NOT MEASURED |
| Phone → field-api upload (`/v1/captures`) | API ingest ≤ 120 ms | — | — | — | NOT MEASURED |
| field-api processing | — | — | — | — | NOT MEASURED |
| field-api → phone response | — | — | — | — | NOT MEASURED |
| Phone → glasses spoken prompt start | — (Gen 2 has no display; audio replaces lens draw ≤ 40 ms) | — | — | — | NOT MEASURED |
| **Shutter-to-ack total** | **≤ 800 ms** | — | — | — | NOT MEASURED |
| `POST /v1/diagnostics/probe` at 10 / 50 / 100 rps | ≤ 50 / 100 / 150 ms | — | — | — | NOT MEASURED (`tools/latency/k6/probe.js` exists, never run with committed output) |

Phase 1 exit criterion ("measured p50/p95 for at least 6 budget segments") is **not met**.
