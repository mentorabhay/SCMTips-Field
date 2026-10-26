# Core Platform Compatibility Matrix (Task T1.034 / FR1.009)

Tracks compatibility between the SCMTIPS Field Add-on and SCMTIPS Core Platform revisions.

| Endpoint / Capability | core-p13 (P13 Reference) | core-p14 (Target PR) | Seam ID | Notes |
|:----------------------|:-------------------------|:---------------------|:--------|:------|
| `GET /.well-known/jwks.json` | **COMPATIBLE** (Ed25519/RS256) | *SKIPPED-PENDING* | - | Core public keys |
| `POST /api/v1/auth/token` | **COMPATIBLE** | *SKIPPED-PENDING* | - | User session JWT |
| `GET /api/v1/devices/{id}/status` | **INTERIM BRIDGED** | *SKIPPED-PENDING* | CS-01 | Polled via fake-core / P10 |
| `POST /api/v1/devices/{id}/revoke` | **INTERIM BRIDGED** | *SKIPPED-PENDING* | CS-04 | JTI revocation list |
| `GET /api/v1/tenants/{id}/features` | **INTERIM BRIDGED** | *SKIPPED-PENDING* | CS-03 | Local env allowlist |
| `POST /api/v1/approvals` | **INTERIM BRIDGED** | *SKIPPED-PENDING* | CS-06 | Field-local approval |
| `POST /api/v1/supply/sync` | **INTERIM BRIDGED** | *SKIPPED-PENDING* | CS-07 | Guided CSV export |

> **Gate Status**: P13 Baseline **LOCKED**. P14 switch scheduled for Phase 5 (CS-01..CS-09 consolidated PR).
