# ADR-0004: Per-Tenant Feature Flags Architecture (Task T1.077 / FR1.068)

**Status**: Accepted  
**Date**: 2026-10-27  
**Context**: SCMTIPS Field needs granular, per-tenant capability toggling across edge devices, console features, and live ERP posting.

---

## 1. Flag Keys Inventory

| Flag Key | Description | Default |
| :--- | :--- | :--- |
| `field.addon.enabled` | Master tenant enablement for SCMTIPS Field add-on module | `false` |
| `field.glasses.enabled` | Enables wearable smart glasses pairing and HUD interaction | `false` |
| `field.erp.live_posting` | Direct live posting to S/4HANA vs posting to queue / simulation | `false` |
| `field.console.enabled` | Access to field web management console | `false` |

---

## 2. Resolution Hierarchy (Highest to Lowest Precedence)

```
[1. Core P13a Dynamic Flags (CS-03 Seam)]
       ↓ (if unavailable or unset)
[2. Process Environment Overrides (FIELD_FLAG_OVERRIDES)]
       ↓ (if unset)
[3. Tenant Allowlist (FIELD_TENANT_ALLOWLIST)]
       ↓ (if not matched)
[4. Default: false (Fail-Closed Off)]
```

---

## 3. Enforcement Semantics

When an API route or console screen requires a feature flag that is disabled for the authenticated tenant:
- The server responds with **HTTP 403 Forbidden**.
- Response body adheres to RFC 9457 Problem Details:
  - `type`: `urn:scmtips-field:problem:FIELD-FLAG-403-DISABLED`
  - `title`: `Feature Flag Disabled`
  - `detail`: `Feature flag '{flag_key}' is disabled for tenant '{tenant_id}'.`
