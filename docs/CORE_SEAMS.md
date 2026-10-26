# SCMTIPS Core Integration Seams (CS-01 to CS-09)

This document formalizes the architectural isolation boundary between the **SCMTIPS Field Add-on** repository (`SCMTips-Field`) and the **SCMTIPS Core Platform** (`ARO`).

During **Phases 1 through 4**, the Field Add-on operates on the **P13 Baseline**, relying exclusively on typed contracts in `packages/core-contract/` and interim test doubles (`tools/fake-core`). In **Phase 5**, all 9 seams are merged into core via a single consolidated pull request once P14 lands.

---

## Seam Inventory & Delivery Plan

### Seam CS-01: Core Auth & Device Token Exchange
- **Gap**: Wearable devices (smart glasses, handhelds) hold P10 device tokens that must be exchanged for short-lived, site-scoped field access tokens without owning user passwords.
- **Interim Bridge (P13 / Phases 1-4)**: `POST /v1/auth/exchange` validates core tokens using cached JWKS (`field_api/auth/jwks.py`) against `tools/fake-core` or core JWKS, checks hardware fingerprint, and issues a 600-second EdDSA field JWT.
- **Phase 5 Target**: Native core auth exchange handler (`core-auth/src/services/tokens.ts`).

### Seam CS-02: User Role & Site Scope Grants
- **Gap**: Field persona roles (`field.operator`, `field.supervisor`, etc.) and site data scoping (`site_ids = ['*']` or specific sites) are not yet natively modeled in core's RBAC tables.
- **Interim Bridge (P13 / Phases 1-4)**: Dedicated database table `field.role_grant` with forced RLS and CLI bootstrap `field-api grant --tenant ... --user ... --role field.admin` audited to `field.outbox`.
- **Phase 5 Target**: WP-14b role mapping into core platform tenant user roles.

### Seam CS-03: Per-Tenant Platform Feature Flags
- **Gap**: Core P13a feature flag service is staff-only and not yet queryable via public API by external add-ons.
- **Interim Bridge (P13 / Phases 1-4)**: `field_api/flags.py` implementing resolution hierarchy: `FIELD_FLAG_OVERRIDES` > `FIELD_TENANT_ALLOWLIST` > default off (ADR-0004). Returns 403 `FIELD-FLAG-403-DISABLED` if add-on is disabled.
- **Phase 5 Target**: Direct read from core P13a feature flag provider via internal gRPC / RPC endpoint.

### Seam CS-04: Wearable Device Revocation Notification
- **Gap**: No inbound push webhook exists in core to notify field services when a mobile/wearable device is reported stolen or revoked.
- **Interim Bridge (P13 / Phases 1-4)**: Background polling of `GET /api/v1/devices/{id}/status` every `FIELD_DEVICE_POLL_S` (default 60s) + local revocation endpoint `POST /v1/devices/{id}/revoke` which writes to `field.outbox` and jti denial list.
- **Phase 5 Target**: P13f outbound signed webhook publisher subscribing to `device.revoked` topic.

### Seam CS-05: AI Model Gateway & Vision Spike
- **Gap**: Meta Model API access in India region for Ray-Ban camera captures; P13b model gateway pending.
- **Interim Bridge (P13 / Phases 1-4)**: Local prompt template files; benchmark quantized Llama fallback on CPU/GPU host for label extraction.
- **Phase 5 Target**: Centralized SCMTIPS AI router (P13b) with quota tracking.

### Seam CS-06: Discrepancy & Variance Approvals
- **Gap**: High-variance goods receipts and cycle count write-offs require supervisor sign-off; core approval engine is P13d.
- **Interim Bridge (P13 / Phases 1-4)**: Local approval state machine in `field.task` with audit outbox records.
- **Phase 5 Target**: Core approval workflow router delegating to `core:/m/approve/{id}`.

### Seam CS-07: Inbound Supply Ledger Synchronization
- **Gap**: ERP receipts must update core supply planning consensus models without direct DB coupling.
- **Interim Bridge (P13 / Phases 1-4)**: Console exports CSV receipt ledger compatible with core guided load.
- **Phase 5 Target**: Inbound WP-14e webhook pushing real-time receipt lines directly into core planning store.

### Seam CS-08: Outbound Integration Event Publisher
- **Gap**: Field events (`goods_receipt.posted`, `inventory_count.completed`) need durable broadcast.
- **Interim Bridge (P13 / Phases 1-4)**: Transactional PostgreSQL outbox table `field.outbox` polled with `FOR UPDATE SKIP LOCKED`.
- **Phase 5 Target**: Core Kafka / NATS JetStream publisher.

### Seam CS-09: AI Quota & Budget Enforcement
- **Gap**: AI vision inference cost tracking per tenant.
- **Interim Bridge (P13 / Phases 1-4)**: In-process token counter and rate limiter.
- **Phase 5 Target**: Core P13b billing and AI budget engine.
