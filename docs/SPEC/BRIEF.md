# SCMTIPS Field — Engineering Architecture Brief

## 1. Product Invariants
1. **Never edit Core during Add-on Development:** SCMTips-Field lives in its own standalone repository. All dependencies on core are routed via `CS-01` through `CS-15` (Core Seams), to be contributed as a single PR when P14 lands.
2. **Fail Closed Tenancy:** Every database table possesses a `tenant_id` UUID column with `FORCE ROW LEVEL SECURITY`. Queries must execute within a session where `app.tenant_id` is set.
3. **No Autonomous ERP Postings:** The AI never commits postings directly. All actions follow a 2-turn staged transition: speech or tap stages the action, explicit "Confirm" posts it.
4. **Offline First Outbox:** Devices write actions to encrypted local storage (SQLCipher / Keystore). Actions upload asynchronously via the outbox pattern.
5. **Human and Motion Safety:** Lens HUD prompts are suppressed when climbing towers (vertical $>0.3\text{ m/s}$, horizontal $>0.6\text{ m/s}$) or walking fast ($>1.0\text{ m/s}$).

## 2. Latency Budget
- Lens confirmation: $\le 400\text{ ms}$ p95 on 5G.
- Glasses draw call: $\le 40\text{ ms}$ p95.
- Target crop upload size: $\sim 40\text{ KB}$.
- API Ingest: $\le 120\text{ ms}$ p95.

## 3. Technology Baseline
- **Backend Services:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16.
- **Worker:** Python 3.13, PostgreSQL `SKIP LOCKED` job queue.
- **Console:** Next.js 15, TypeScript, Tailwind CSS, ui-tokens.
- **Android App:** Kotlin, Jetpack Compose, CameraX, ML Kit, MediaPipe/TFLite, Meta Wearables Device Access Toolkit.
- **Simulated ERP:** FastAPI S/4HANA OData mock with number ranges, enqueue locks, reversals (102/602/702), and fault injection.
