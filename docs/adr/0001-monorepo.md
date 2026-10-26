# ADR-0001: Monorepo Architecture for SCMTIPS Field

## Context
SCMTIPS Field combines Python backend services (`field-api`, `field-worker`, `erp-sim`, `connectors`), a Next.js web console (`field-console`), shared contract packages, and end-to-end integration and verification suites. Polyglot coordination is required without inter-repo synchronization friction.

## Decision
Adopt a single private repository `SCMTips-Field` utilizing:
1. Python workspace driven by `uv` (`pyproject.toml`, pinned Python 3.13).
2. TypeScript workspace driven by `pnpm` (`pnpm-workspace.yaml`).
3. Shared Docker Compose environment for local parity.
4. Single root-level verification script `scripts/verify-all.sh`.

## Consequences
### Positive
- Atomic PRs spanning API contracts, client packages, migrations, and UI.
- Unified typechecking, linting, and vulnerability scanning.
- No direct dependency on core SCMTips codebase.

### Negative / Trade-offs
- Requires developers to have both Python 3.13 and Node.js/pnpm environments.
