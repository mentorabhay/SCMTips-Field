# SCMTIPS Field - Secrets Management Architecture (Task T1.071 / FR1.062)

**Document Reference**: `docs/security/SECRETS.md`  
**Governing Standard**: Zero Secrets in Version Control (TC1.160)

---

## 1. Secrets Ingestion Hierarchy

`field-api` and `field-worker` NEVER load sensitive credentials from repository code or checked-in configuration files. Secrets are resolved through `field_api.secrets.load_secret()` in strict order of precedence:

1. **Vault / KMS Secrets Provider (`FIELD_SECRETS_SOURCE=vault://...` or `kms://...`)**:
   - In production, secrets are fetched dynamically from HashiCorp Vault or AWS KMS / GCP Secret Manager using workload identity.
2. **Mounted Secrets File (`FIELD_SECRETS_FILE=/etc/secrets/...`)**:
   - In Kubernetes / Docker container environments, secrets are mounted from Kubernetes Secret volumes into read-only paths (e.g. `/run/secrets/`).
3. **Process Environment Variables**:
   - Pre-injected by CI/CD or orchestrator runtime (`DATABASE_URL`, `JWT_PUBLIC_KEY`, `SAP_API_KEY`).
4. **Local Development Exemption (`.env.local`)**:
   - Excluded by `.gitignore` (`.env*`). Dev defaults are restricted to insecure loopback testing values (e.g. `dev-postgres-password`).

---

## 2. Response & Log Secret Scrubber

All outbound API responses, error problem details (RFC 9457), and structlog log messages pass through `field_api.secrets.scrub_secrets()`.

Patterns scrubbed automatically:
- Password fields (`password`, `pass`, `pwd`, `secret`, `api_key`, `token`, `authorization`)
- Private keys (`-----BEGIN PRIVATE KEY-----`, Ed25519 seed bytes)
- Database credentials (`postgresql://user:pass@host:port/db` scrubbed to `postgresql://user:***@host:port/db`)
- Bearer tokens (`Bearer ey...` scrubbed to `Bearer [REDACTED]`)

---

## 3. Automated Verification & CI Gates

1. **Semgrep Secrets Scan**: Pinned Semgrep rules verify that no private keys, passwords, or cloud tokens are committed.
2. **Property / Unit Test `TC1.160`**: Submits payloads containing sensitive credentials to `field_api.secrets.scrub_secrets()` and validates that all sensitive patterns are redacted before serialization.
