# SCMTIPS Field - Dependency & Supply Chain Security Policy (Task T1.072 / FR1.064)

**Document Reference**: `docs/security/DEPENDENCY_POLICY.md`  
**Governing Gate**: `tools/checks/deps.py` executed in `scripts/verify_all.py` (TC1.165)

---

## 1. Core Principles

1. **Deterministic Lockfiles**: Every runtime dependency and transitive child must be resolved via pinned cryptographic lockfiles (`uv.lock` for Python, `pnpm-lock.yaml` for JavaScript/TypeScript). Loose version ranges (`^`, `~`, `>=`) are forbidden in deployment manifests.
2. **14-Day Minimum Package Age**: To prevent npm/PyPI supply-chain injection and typo-squatting zero-days, no package version released less than 14 days prior may be introduced into the dependency tree without explicit security lead approval.
3. **Approved Licence Allowlist**:
   - `MIT`
   - `Apache-2.0`
   - `BSD-2-Clause`
   - `BSD-3-Clause`
   - `ISC`
   - `PSF-2.0` (Python Software Foundation)
   - `MPL-2.0` (Mozilla Public License 2.0 - permitted for build tools and standalone CLIs)
   - *Strictly Forbidden*: GPL v2/v3, AGPL v3, SSPL, or any non-commercial / copyleft viral licenses.
4. **Software Bill of Materials (SBOM)**: Every release candidate generates a standard CycloneDX v1.5 JSON SBOM (`sbom.json`) documenting package names, purls, SHA-256 hashes, and verified licenses.

---

## 2. Enforcement via `tools/checks/deps.py`

`tools/checks/deps.py` validates:
1. `uv.lock` and `pnpm-lock.yaml` exist and are synchronized with `pyproject.toml` and `package.json`.
2. Inspects declared package licenses against the approved licence allowlist.
3. Flags any unapproved or copyleft licenses immediately with exit code 1.
