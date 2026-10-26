# ADR-0003: Interim Auth Bridge (`POST /v1/auth/exchange`)

## Context
SCMTIPS Core issues JWTs via its SSO session and P10 device tokens. During development of SCMTIPS Field prior to P14, core does not carry `field.*` roles or the device exchange endpoint natively. Core Seam `CS-01` captures this delta.

## Decision
Implement `POST /v1/auth/exchange` in `field-api`:
1. Validates core-signed device token against core JWKS.
2. Looks up interim field permissions from `field.role_grant` (CS-02 interim).
3. Issues a scoped `field_access_token` containing principal, tenant, site scopes, and `field.*` permissions.
4. Seamlessly replaces with native core tokens in Phase 5 when Seam `CS-01` merges.

## Consequences
### Positive
- Fully decoupled development; no edits required in `<workspace>\ARO`.
- Enforces zero-trust fail-closed authentication from Day 1.

### Negative / Trade-offs
- Requires maintaining an interim token exchange service until Phase 5.
