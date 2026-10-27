# SCMTIPS Field - Data Protection Impact Assessment (DPIA) Starter (Task T1.070 / FR1.061)

**Document Reference**: `docs/privacy/DPIA_STARTER.md`  
**Governing Jurisdictions**:
- **India**: Digital Personal Data Protection Act, 2023 (DPDP Act 2023)
- **European Union**: General Data Protection Regulation (GDPR - Regulation (EU) 2016/679)
- **United States**: California Consumer Privacy Act / CPRA

---

## 1. Description of Processing & Purposes

SCMTIPS Field processes optical and barcode data captured by wearable devices (smart glasses) and mobile handhelds operated by warehouse personnel for:
1. **Goods Receipt Verification**: Confirming inbound deliveries against ERP purchase orders (SAP 101).
2. **Picking & Inventory Control**: Verifying storage bin barcodes, material SKU numbers, and lot quantities (SAP 601 / 701).
3. **Auditing & Equipment Installation**: Timestamped logging of physical goods movement and serial number registration.

---

## 2. Lawful Basis for Processing

| Jurisdiction | Applicable Statute | Lawful Basis | Justification |
| :--- | :--- | :--- | :--- |
| **India** | DPDP Act 2023, Section 7(i) | **Legitimate Uses (Employment & Operations)** | Processing is necessary for employment purposes, safeguarding corporate inventory, and preventing operational losses in industrial logistics facilities. |
| **European Union** | GDPR Article 6(1)(f) & Article 88 | **Legitimate Interests / Employment Context** | Legitimate interest in accurate supply chain fulfillment, subject to strict data minimization and bystander safeguards. |
| **All Regions** | Tenant Enterprise Agreement | **Contractual Necessity (Article 6(1)(b))** | Processing required to deliver the core warehouse automation service contracted by the tenant employer. |

---

## 3. Bystander Privacy & Wearable Camera Governance

Smart glasses worn in logistics facilities could inadvertently capture coworkers or visitors. To mitigate this risk:
1. **No Continuous Video Recording**: The glasses do NOT record or stream video continuously. The camera operates in snapshot mode triggered solely by operator intent (shutter press or barcode aim).
2. **Local Frame Cropping & Minimization**: ML Kit scans for barcode bounding boxes immediately upon frame arrival. Images lacking recognized barcodes or labels are immediately discarded from memory without disk persistence.
3. **Tally Light Indication**: Hardware LED tally light activates whenever the optical sensor is energized, alerting coworkers in physical proximity.
4. **No Biometric Facial Identification**: SCMTIPS Field does not extract facial embeddings, facial landmarks, or biometric identities.

---

## 4. Data Retention & Erasure Schedule (Core Policy P13e Alignment)

| Data Category | Storage Location | Retention Window | Purge Mechanism |
| :--- | :--- | :--- | :--- |
| **Raw Capture Images** | Edge Phone Temporary Cache | **72 hours** | Automatic OS cache eviction upon successful ERP posting |
| **Capture Metadata (`field.capture`)** | PostgreSQL Database | **90 days** | Automated Alembic partitioning & cron purge |
| **Idempotency Records** | `field.idempotency_record` | **24 hours** | Scheduled job deletes records older than 24h |
| **Posting Jobs & Outbox** | `field.posting_job`, `outbox` | **30 days** post-completion | Background worker archiving |
| **ERP Document Audit Ledger** | `field.erp_document` | **7 years** (Statutory requirement) | Read-only immutable financial audit ledger |

---

## 5. Data Principal Rights & Governance

- **Right to Access & Correction**: Operators may query their assigned tasks and enrolled devices through the core user portal.
- **Revocation of Device Access**: If an operator leaves employment or reports a lost device, `field-api` immediately revokes the device via `POST /v1/devices/{id}/revoke`, terminating all active session keys within 600 seconds.
- **Data Protection Officer (DPO)**: Field platform operations are reviewed quarterly by the designated DPO to ensure ongoing compliance with DPDP 2023 statutory guidelines.
