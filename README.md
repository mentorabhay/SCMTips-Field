# SCMTIPS Field

> **Field truth, captured in one look.**  
> Meta smart glasses and mobile application that record physical supply chain operations and post verified material movements directly to the ERP, built as an independent add-on product on top of SCMTIPS P13 and designed to switch to P14 via Core Seams (`CS-01` to `CS-15`).

---

## Architecture Overview

```
                                      ┌────────────────────────┐
                                      │   Meta Ray-Ban Glasses │
                                      │   (Display / Audio)    │
                                      └───────────┬────────────┘
                                                  │ BLE / Wi-Fi
                                                  ▼
┌──────────────────┐                  ┌────────────────────────┐
│  field-console   │                  │     field-android      │
│  (Next.js 15)    │                  │  (Compose + CameraX)   │
└────────┬─────────┘                  └───────────┬────────────┘
         │                                        │ HTTPS / W3C Trace
         │                                        ▼
         │                            ┌────────────────────────┐
         └───────────────────────────►│       field-api        │
                                      │   (FastAPI + RLS)      │
                                      └───────────┬────────────┘
                                                  │ SKIP LOCKED Queue
                                                  ▼
┌──────────────────┐                  ┌────────────────────────┐
│     erp-sim      │◄─────────────────┤      field-worker      │
│ (S/4HANA OData)  │  Connectors (SAP)│    (Posting Engine)    │
└──────────────────┘                  └────────────────────────┘
```

---

## Workspace Layout

- `services/field-api`: Core FastAPI backend with forced Row-Level Security (`app.tenant_id`), 24h Idempotency, ETag/If-Match, UUIDv7, and cursor pagination.
- `services/field-worker`: Background worker handling transactional outbox events, material synchronization, and asynchronous SAP postings.
- `services/erp-sim`: High-fidelity simulated S/4HANA OData ERP providing realistic numbering ranges, enqueue locks, reversals (102/602/702), and fault injection (`/_sim/faults`).
- `connectors/sap`: Pluggable ERP connector port (`ErpPort`) with `SimAdapter` and `S4ODataAdapter`.
- `apps/field-console`: Next.js 15 console featuring system status, document audits, and the **Web Ray-Ban HUD Simulator**.
- `packages/ui-tokens`: Design token system guaranteeing WCAG 2.1 AA contrast across Light, Dark, and Lens monochrome themes.
- `packages/field-contract`: OpenAPI 3.1 specifications and generated clients.
- `packages/core-contract`: Pinned client contract for SCMTIPS Core P13.
- `compat`: Compatibility suite ensuring add-on compatibility with core tags.
- `tools/fake-core`: dev double: core SSO, JWKS and device token issuer, plus the M4 stand-in core (never the SCMTIPS core; see `tools/fake-core/README.md`).
- `scripts/verify-all.sh`: 12-job verification runner producing deterministic PASS/FAIL reports.

---

## Verification & Quality Gates

Run the unified test runner:
```bash
./scripts/verify-all.sh
```

Jobs evaluated:
1. `lint` (Ruff, ESLint)
2. `typecheck` (Mypy strict, TypeScript strict)
3. `unit` (Pytest, Vitest)
4. `property` (Hypothesis CI profile: 500 iterations, fast-check)
5. `contract` (Schemathesis against OpenAPI)
6. `compat` (Core contract regression test)
7. `alembic` (Migration round-trip upgrade-downgrade-upgrade schema parity)
8. `semgrep` (Semgrep security scan with pinned rules)
9. `trivy` (Trivy vulnerability and filesystem scan)
10. `names` (Denylist check preventing unapproved naming)
11. `firewall` (Dependency isolation preventing unauthorized core imports)
12. `conventions` (Conventional commit and documentation check)
