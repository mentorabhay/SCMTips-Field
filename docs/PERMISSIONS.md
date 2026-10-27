# SCMTIPS Field - Role-to-Permission Mapping (Task T1.039 / FR1.033)

This document formalizes the 7 canonical field persona roles and their expanded permission grants.

| Role ID | Persona / Scope | Granted Permissions |
|:--------|:----------------|:--------------------|
| `field.operator` | Warehouse operator with mobile/glasses | `field.capture.create`, `field.task.read`, `field.task.execute`, `field.location.read`, `field.material.read`, `field.site.read` |
| `field.technician` | Field service technician / tower inspections | `field.capture.create`, `field.asset.read`, `field.asset.inspect`, `field.part.replace`, `field.task.execute`, `field.location.read`, `field.site.read` |
| `field.supervisor` | Shift supervisor / warehouse lead | `field.discrepancy.read`, `field.discrepancy.approve`, `field.recount.assign`, `field.override.grant`, `field.device.read`, `field.device.revoke`, `field.task.manage`, `field.site.read` |
| `inventory.controller` | Inventory controller / cycle count manager | `field.stock.read`, `field.stock.adjust`, `field.audit.review`, `field.recount.assign`, `field.tolerance.configure`, `field.discrepancy.approve`, `field.site.read` |
| `field.integration` | Backend worker / ERP sync daemon | `field.material.sync`, `field.export.execute`, `field.sync.trigger`, `field.erp.post` |
| `field.viewer` | Read-only auditor or guest | `field.site.read`, `field.location.read`, `field.material.read`, `field.task.read` |
| `field.admin` | Tenant field administrator | `field.*` (all permissions) |

> **Glasses Restriction (CS-07 interim)**: When a principal connects via a smart-glasses device session, mutating approvals (`field.discrepancy.approve`, `field.override.grant`) are restricted to phone-assisted confirmations or explicit voice verification.
