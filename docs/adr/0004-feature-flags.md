# ADR-0004: Multi-Tenant & Per-Site Feature Flag Resolution

## Context
Features such as HUD Display, Glove Mode, and specific Industry Packs must be enabled progressively across tenants and sites without redeploying code.

## Decision
Adopt a deterministic 4-tier fallback hierarchy evaluated in `field_api/flags.py`:
1. **User / Device Override:** Specific test device or operator.
2. **Site Override:** Specific physical site (e.g., warehouse pilot site `SAMPLE-WH-01`).
3. **Tenant Default:** Per-tenant configuration stored in `field.tenant_config`.
4. **Environment Fallback:** Compiled default flags (`FIELD_FEATURE_*`).

Flags are cached for 60 seconds (`FIELD_FLAG_CACHE_SECONDS`) and invalidated upon modification.

## Consequences
### Positive
- Enables safe canary rollout waves (Phase 8) using stable hash buckets.
- Allows disabling unstable features instantaneously via API without deployment.
