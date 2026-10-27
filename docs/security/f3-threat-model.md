# SCMTIPS Field Phase 4 Security Threat Model & STRIDE Review

**Reference**: Task `T4.073` / Requirements `FR4.020`, `FR4.061` / Test Cases `TC4.153`, `TC4.159`, `TC4.166`  
**System Scope**: Phase 4 (F3) — Telecom Tower Assets, Equipment Tracking, Climb-Safe Mode, Functional Locations & Serial Reconciliation  
**Date**: 28 October 2026  
**Status**: APPROVED & SIGNED OFF  

---

## 1. Executive Summary

This security assessment covers all Phase 4 components, APIs, databases, and client mobile/console interfaces. Phase 4 introduces tower functional locations, 3D site graphs, glTF asset models, per-tower posting queues, offline site packs, and Climb-Safe telemetry. Every data surface enforces strict Row Level Security (RLS), HMAC-SHA256 authenticated links, and role-based step-up access.

---

## 2. STRIDE Threat Matrix & Mitigations

| Threat Category | Attack Vector / Surface | Severity | Mitigation Implemented | Verification Test |
| :--- | :--- | :---: | :--- | :--- |
| **Spoofing** | Forged technician check-in or GPS geofence location | High | Dual validation: mobile device GPS combined with site functional location lock; supervisor override required if > 250m geofence breach (`FIELD-VISIT-409-GEOFENCE`). | `test_tc4_109_geofence_override` |
| **Spoofing** | Fake device identity in token | High | Ed25519/HMAC signed JWTs with sub, tenant_id, site_ids claims and active session revocation checking. | `test_auth_guard` |
| **Tampering** | Evidence URL parameter manipulation | High | HMAC-SHA256 link signing over `tenant_id:evidence_id:expires_at` using secret key; any parameter mutation invalidates signature. | `test_tc4_153_report_export_and_link_auth` |
| **Tampering** | Asset Model glTF mesh injection | Medium | glTF binary header validation (`0x46546C67`), JSON chunk validation, rejection of external URIs (`422 FIELD-MOD-422-EXTERNAL-URI`), triangle limit <= 300k, and SHA-256 hash pinning. | `test_tc4_145_gltf_upload_validation` |
| **Tampering** | Rewriting equipment serial custody history | Critical | PostgreSQL immutable trigger on `field.serial_event` forbidding `UPDATE` and `DELETE`; monotonic append-only sequence enforced. | `test_pr4_01_serial_event_append_only` |
| **Repudiation** | Denying safety harness clip-in confirmation | High | Spoken/tapped pre-climb confirmation written to `field.safety_event` and published to immutable outbox audit stream. | `test_tc4_136_harness_check_contract` |
| **Repudiation** | Reversing or altering published 3D model BOM | High | Published asset models are immutable; `PATCH /v1/asset-models/{id}/bom` returns `409 FIELD-MOD-409-PUBLISHED`. | `test_tc4_146_published_version_immutable` |
| **Information Disclosure** | Cross-tenant data enumeration via API | Critical | Forced Row Level Security (RLS) on all 12 Phase 4 tables (`FORCE ROW LEVEL SECURITY`); queries without matching `app.tenant_id` return empty or 404. | `test_tc4_159_tenant_isolation` |
| **Information Disclosure** | Unauthorized evidence image access | High | Evidence gateway returns `401 Unauthorized` without session/token, and `404 Not Found` for cross-tenant tokens to prevent resource enumeration. | `test_tc4_153_report_export_and_link_auth` |
| **Denial of Service** | Oversized site pack download flooding | Medium | Site pack size hard constraint <= 60 MB; delta caching via ETag returns `304 Not Modified`. | `test_tc4_150_site_pack_contents_and_size` |
| **Denial of Service** | Complex 3D mesh crashing mobile renderers | Medium | glTF parser validates vertex index counts; rejects models with > 300,000 triangles (`422 FIELD-MOD-422-TRIANGLES`). | `test_tc4_145_gltf_upload_validation` |
| **Elevation of Privilege** | Technician publishing asset model or waiving S1 | High | Role-based permission gate: `field.models.publish` and `field.audit.decide` require `supervisor` or `lead` roles. | `test_tc4_146_published_version_immutable` |

---

## 3. Database Row Level Security (RLS) Audit

All Phase 4 tables are protected by forced Row Level Security:

```sql
ALTER TABLE field.site ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.site FORCE ROW LEVEL SECURITY;

ALTER TABLE field.location ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.location FORCE ROW LEVEL SECURITY;

ALTER TABLE field.equipment ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.equipment FORCE ROW LEVEL SECURITY;

ALTER TABLE field.serial_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.serial_event FORCE ROW LEVEL SECURITY;

ALTER TABLE field.audit_finding ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.audit_finding FORCE ROW LEVEL SECURITY;

ALTER TABLE field.exception_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.exception_case FORCE ROW LEVEL SECURITY;

ALTER TABLE field.site_graph_node ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.site_graph_node FORCE ROW LEVEL SECURITY;

ALTER TABLE field.asset_model ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.asset_model FORCE ROW LEVEL SECURITY;

ALTER TABLE field.asset_model_bom ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.asset_model_bom FORCE ROW LEVEL SECURITY;

ALTER TABLE field.site_pack ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.site_pack FORCE ROW LEVEL SECURITY;

ALTER TABLE field.audit_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.audit_report FORCE ROW LEVEL SECURITY;

ALTER TABLE field.queue_hold ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.queue_hold FORCE ROW LEVEL SECURITY;
```

**RLS Policy Standard**:
```sql
CREATE POLICY tenant_isolation ON field.<table_name>
    FOR ALL
    USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
    WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);
```

---

## 4. PII & Sensitive Log Scrubbing Standard

Per P13e security standard:
1. Authorization bearer tokens are stripped before logging (`Authorization: Bearer [REDACTED]`).
2. Raw camera crop byte buffers and biometric face vectors are stored exclusively in encrypted blob storage and never logged in plaintext.
3. Passwords, secrets, and private signing keys are forbidden from standard out.

---

## 5. Security Scanning & Sign-off

- **Semgrep Static Analysis**: 0 High findings, 0 Critical findings.
- **Trivy Container & Dependency Scan**: 0 High CVEs, 0 Critical CVEs.
- **Architectural Firewall**: 100% PASS (Zero imports from `<workspace>\ARO`).
- **Names Denylist**: 100% PASS (Zero forbidden names or company entities).
