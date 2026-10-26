# ADR-0002: Simulation-First ERP (`erp-sim`) Development Pattern

## Context
Testing against live SAP S/4HANA systems during development and CI introduces external dependencies, unrepeatable number ranges, shared locking conflicts, and lack of fault injection capabilities.

## Decision
Build `erp-sim` as a dedicated mock service exposing realistic SAP OData APIs (`API_INBOUND_DELIVERY_SRV`, `API_MATERIAL_DOCUMENT_SRV`, `API_PHYSICAL_INVENTORY_DOC_SRV`):
1. Strict number range allocation (`erp_sim/numbering.py`).
2. Pessimistic Enqueue Locks (`erp_sim/locks.py`).
3. Material document reversals (Movement types 102, 602, 702) maintaining stock invariants.
4. Deterministic fault injection (`/_sim/faults` for timeout, latency, 5xx, lock failure).
5. Visual inspection console at `/_sim/ui`.

## Consequences
### Positive
- Fully reproducible property tests (PR1.05 to PR1.08, PR1.14) and CI without SAP credentials.
- Zero risk of corrupting real production or QA ERP systems.

### Negative / Trade-offs
- Requires keeping `erp-sim` contracts synchronized with real S/4HANA OData specifications.
