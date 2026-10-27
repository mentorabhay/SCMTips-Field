# F1 Capture Engine: STRIDE Threat Model & Security Review (Task T2.072 / FR2.053, FR2.059)

## 1. Overview & Threat Modeling Methodology
This security review covers the Phase 2 F1 Capture Engine surfaces across the Android edge client, wearables link, `field-api`, and `field-worker` components, evaluated under the STRIDE methodology.

---

## 2. STRIDE Assessment Matrix

| Threat Category | Surface / Vector | Mitigating Control & Architectural Enforcement | Verification |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Rogue device spoofing capture upload | Hardware Keystore-backed AES-256-GCM tokens; short-lived memory-only JWT; W3C `traceparent` and RFC 9562 UUIDv7 keys. | TC2.104, TC2.135 |
| **Tampering** | Local file tampering on lost/rooted phone | Database encrypted via SQLCipher 4.x with 256-bit passphrase; crop files encrypted with AES-256-GCM (12-byte IV + 16-byte tag). Tampered ciphertext fails authentication (`InvalidTag`). | TC2.135, TC2.136 |
| **Repudiation** | Operator denying counted quantity or scan | Confirmed voice turn strictly enforced: `POST /v1/tasks/{id}/post-requests` requires an accepted `confirm` turn within 10s of `post`; CloudEvents envelope published to append-only outbox. | PR2.11, TC2.133, TC2.146 |
| **Information Disclosure** | Bystander faces or location leaks in evidence | `FaceBlurStage` detects bystander faces ($\ge 0.30$) and applies 16px block blur with 10% margins; EXIF GPS tags stripped; full camera frames rejected from disk; RAM audio buffer zeroed immediately after ASR. | PR2.13, TC2.123, TC2.131, TC2.161 |
| **Denial of Service** | Flash flood offline burst overflowing storage | Bounded outbox capacity governor: warns at 90% (`MSG2.12`), strictly refuses admission at 2,000 items or 200 MB (`MSG2.13`) without evicting queued items; exponential retry backoff `[2, 4, 8, 16, 32]s`. | PR2.18, TC2.137 |
| **Elevation of Privilege** | Cross-tenant or cross-site data access | PostgreSQL Row-Level Security (RLS) forced on all 11 Phase 2 tables; restrictive `tenant_isolation` policy; out-of-scope reads return 404; device revoke restricted to `field.admin`. | FR2.053, TC2.160 |

---

## 3. Data Sovereignty & Contributor Model Ban (FR2.059)
- Configured model names ending in `-contributor` (e.g. models trained on enterprise customer inputs) are strictly rejected at worker startup (`FieldContributorModelConfig`).
- Verified via automated static analysis and dynamic test `TC2.148`.

---

## 4. Trivy & Dependency Scan Findings
- All pinned Gradle libraries (Room, WorkManager, CameraX, ML Kit, MediaPipe, SQLCipher) and Python packages: **0 High, 0 Critical findings open**.
