# SCMTIPS Field - Data Classification Matrix (Task T1.070 / FR1.061)

**Document Reference**: `docs/security/DATA_CLASSIFICATION.md`  
**Classification Tiers**:
1. **Public**: Non-sensitive data that can be shared externally without business impact.
2. **Internal**: Standard operational operational metadata, non-sensitive IDs and timestamps.
3. **Confidential**: Business-critical inventory counts, ERP documents, material descriptions, coordinates.
4. **Restricted-Personal**: Personal Identifiable Information (PII) including operator IDs, device fingerprints, biometric/camera frames.

---

## Complete Table & Column Classification (V1 Data Model)

| Table | Column Name | Data Type | Classification Tier | Justification & Safeguards |
| :--- | :--- | :--- | :--- | :--- |
| **field.site** | `id` | uuid | **Internal** | Synthetic UUIDv7 identifier |
| | `tenant_id` | uuid | **Confidential** | Tenant isolation key |
| | `code` | text | **Internal** | Warehouse code (e.g. WH1) |
| | `name` | text | **Internal** | Facility name |
| | `kind` | text | **Internal** | Site classification enum |
| | `erp_plant` | text | **Confidential** | ERP plant mapping code |
| | `erp_storage_locations` | text[] | **Confidential** | ERP storage locations list |
| | `timezone` | text | **Internal** | Standard IANA timezone |
| | `lat` / `lon` | numeric(9,6) | **Confidential** | Physical facility GPS coordinates |
| | `status` | text | **Internal** | Site status flag |
| | `version` / `created_at` / `updated_at` | integer / timestamptz | **Internal** | Concurrency and audit timestamps |
| **field.location** | `id` / `tenant_id` / `site_id` | uuid | **Internal / Confidential** | Keys and tenant isolation |
| | `parent_id` / `code` / `name` | uuid / text | **Internal** | Storage bin hierarchical structure |
| | `barcode` | text | **Confidential** | Physical bin barcode |
| | `location_type` / `path` / `depth` | text / text / int | **Internal** | Bin taxonomy and hierarchy path |
| | `status` / `version` / timestamps | text / int / timestamptz | **Internal** | State control |
| **field.material** | `id` / `tenant_id` | uuid | **Internal / Confidential** | Identifiers |
| | `material_no` | text | **Confidential** | ERP Part / SKU Number |
| | `description` | text | **Confidential** | Item description |
| | `plant` / `base_uom` | text | **Internal** | Plant code and unit of measure |
| | `storage_locations` | text[] | **Confidential** | Valid ERP storage locations |
| | `source_hash` | text | **Internal** | Synchronization cache hash |
| | `deleted_in_erp` / `missed_sync_cycles` | boolean / int | **Internal** | Cache eviction controls |
| **field.device** | `id` / `tenant_id` / `site_id` | uuid | **Internal / Confidential** | Device identifiers |
| | `device_identifier` | text | **Restricted-Personal** | Hardware serial / MAC / IMEI |
| | `device_type` | text | **Internal** | "glasses", "phone", "scanner" |
| | `os_version` / `app_version` | text | **Internal** | Device fleet metadata |
| | `status` | text | **Internal** | "active", "revoked", "suspended" |
| | `enrolled_at` / `last_seen_at` / `revoked_at` | timestamptz | **Restricted-Personal** | Operator presence & activity timeline |
| **field.task** | `id` / `tenant_id` / `site_id` | uuid | **Internal / Confidential** | Task identifiers |
| | `task_type` / `status` / `priority` | text | **Internal** | Task workflow parameters |
| | `doc_family` / `doc_number` | text | **Confidential** | ERP Delivery / PO document numbers |
| | `assigned_user_id` | uuid | **Restricted-Personal** | Operator user identifier |
| **field.task_line** | `id` / `tenant_id` / `site_id` / `task_id` | uuid | **Internal / Confidential** | Line keys |
| | `line_no` | integer | **Internal** | Line item step number |
| | `material_id` | uuid | **Confidential** | SKU reference |
| | `expected_qty` / `captured_qty` / `uom` | numeric / text | **Confidential** | Physical goods quantities |
| | `status` | text | **Internal** | Line item disposition |
| **field.capture** | `id` / `tenant_id` / `site_id` | uuid | **Internal / Confidential** | Capture keys |
| | `device_id` / `task_id` | uuid | **Restricted-Personal** | Audit link to physical device |
| | `is_probe` | boolean | **Internal** | Latency diagnostic marker |
| | `raw_text` | text | **Confidential** | Raw OCR / Barcode text string |
| | `parsed_data` | jsonb | **Confidential** | Parsed GS1 AI tags (lot, expiry, serial) |
| | `confidence` | numeric(4,3) | **Internal** | Algorithm confidence score |
| | `status` | text | **Internal** | "verified", "rejected", "flagged" |
| **field.erp_document** | `id` / `tenant_id` / `site_id` | uuid | **Internal / Confidential** | Document IDs |
| | `doc_type` / `doc_number` / `fiscal_year` | text | **Confidential** | SAP Material Document / Delivery |
| | `movement_type` | text | **Confidential** | Movement code (101, 601, 701, etc.) |
| | `reversal_of_id` | uuid | **Confidential** | Cancellation linkage |
| | `payload` | jsonb | **Confidential** | Full ERP payload and line items |
| **field.posting_job** | `id` / `tenant_id` / `erp_doc_id` | uuid | **Internal / Confidential** | Queue identifiers |
| | `queue_key` | text | **Internal** | Ordering partition key |
| | `status` / `attempts` / `next_attempt_at` | text / int / timestamptz | **Internal** | Retry & backoff state |
| | `payload` | jsonb | **Confidential** | ERP posting request payload |
| **field.outbox** | `id` / `tenant_id` | uuid | **Internal / Confidential** | Event identifiers |
| | `event_type` | text | **Internal** | Event classification |
| | `aggregate_id` | uuid | **Internal** | Aggregate entity UUID |
| | `payload` | jsonb | **Confidential** | Outbox event payload |
| | `published_at` / `created_at` | timestamptz | **Internal** | Dispatch timestamps |
| **field.idempotency_record** | `id` / `tenant_id` | uuid | **Internal / Confidential** | Idempotency record IDs |
| | `idempotency_key` | text | **Internal** | Client UUID key |
| | `fingerprint` | text | **Internal** | SHA-256 payload digest |
| | `status` / `status_code` | text / int | **Internal** | HTTP execution state |
| | `headers` / `body` / `media_type` | jsonb / bytea / text | **Confidential** | Cached response content |
| **field.role_grant** | `id` / `tenant_id` | uuid | **Internal / Confidential** | Grant keys |
| | `user_id` | uuid | **Restricted-Personal** | Assigned operator user ID |
| | `role` | text | **Internal** | "field.admin", "field.operator", etc. |
| | `granted_by` | uuid | **Restricted-Personal** | Grantor user ID |
| | `granted_at` | timestamptz | **Internal** | Grant timestamp |
