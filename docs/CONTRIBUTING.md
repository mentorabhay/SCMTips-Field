# SCMTIPS Field — Contributing & Branching Conventions

## 1. Branch Naming Convention
Branches follow the format:
`f<phase>/<workstream>-<slug>`

Examples:
- `f0/ws1-repo-tooling`
- `f0/ws2-api-core`
- `f0/ws3-data-model`
- `f0/ws5-erp-sim`
- `f1/ws1-capture-engine`

## 2. Commit Message Convention
Commits MUST follow Conventional Commits with a work package scope:
`<type>(f<phase>-ws<number>): <imperative summary>`

Valid types: `feat`, `fix`, `test`, `refactor`, `docs`, `chore`, `perf`.

Examples:
- `feat(f0-ws1): scaffold python and typescript workspaces`
- `feat(f0-ws2): implement 24h idempotency key middleware`
- `test(f0-ws3): verify forced rls on 12 field tables`
- `feat(f0-ws5): add simulated sap enqueue lock engine`

## 3. Review & Verification Gate
Before any merge:
1. `./scripts/verify-all.sh` MUST report 12 PASS jobs with 0 FAIL.
2. Code review from assigned CODEOWNERS role.
3. No direct mutations or imports of core `SCMTips` / `ARO`.
