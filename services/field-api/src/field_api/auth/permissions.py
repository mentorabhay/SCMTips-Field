"""SCMTIPS Field Role-to-Permission Mapping (Task T1.039 / FR1.022)."""

from collections.abc import Mapping
from types import MappingProxyType

# Immutable (rule 2.2.b): role -> permission tuples. The spec fixes the roles and the
# field.<area>.<verb> scheme (FR1.022) and leaves the mapping to least privilege. Note the
# separation of duties: inventory.controller requests PI postings, field.supervisor approves.
ROLE_PERMISSIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "field.operator": (
            "field.capture.create",
            "field.task.read",
            "field.task.execute",
            "field.task.update",
            "field.location.read",
            "field.material.read",
            "field.site.read",
            "field.post.confirm",
            "field.post.request",
            "field.count.create",
            "field.consent.record",
            "field.device.register",
            "field.device.pair",
            "field.visit.checkin",
            "field.visit.ack",
        ),
        "field.technician": (
            "field.capture.create",
            "field.asset.read",
            "field.asset.inspect",
            "field.part.replace",
            "field.task.execute",
            "field.location.read",
            "field.site.read",
            "field.post.confirm",
            "field.count.create",
            "field.consent.record",
            "field.device.register",
            "field.device.pair",
            "field.visit.checkin",
            "field.visit.ack",
            "field.safety.checklist",
            "field.swap.post",
            "field.task.read",
        ),
        "field.supervisor": (
            "field.system.read",
            "field.discrepancy.read",
            "field.discrepancy.approve",
            "field.recount.assign",
            "field.override.grant",
            "field.device.read",
            "field.device.revoke",
            "field.task.manage",
            "field.task.update",
            "field.quality.release",
            "field.site.read",
            "field.queue.manage",
            "field.queue.read",
            "field.post.confirm",
            "field.graph.edit",
            "field.site.edit",
            "field.location.edit",
            "field.task.read",
            "field.capture.read",
            "field.evidence.read",
            "field.exception.read",
            "field.exception.decide",
            "field.visit.override",
            "field.visit.ack",  # acknowledge a lone-worker escalation (FR4.044, console)
            "field.trail.read",
        ),
        "inventory.controller": (
            "field.stock.read",
            "field.stock.adjust",
            "field.audit.review",
            "field.recount.assign",
            "field.tolerance.configure",
            "field.discrepancy.approve",
            "field.site.read",
            "field.pi.create",
            "field.pi.post",
            "field.pi.book",
            "field.task.read",
            "field.capture.read",
            "field.evidence.read",
        ),
        "field.integration": (
            "field.material.sync",
            "field.export.execute",
            "field.sync.trigger",
            "field.erp.post",
            "field.queue.manage",
            "field.queue.read",
            "field.integration",
            "field.export.run",
            "field.site.import",
        ),
        "field.viewer": (
            "field.site.read",
            "field.location.read",
            "field.material.read",
            "field.task.read",
        ),
        "field.admin": (
            "field.*",
        ),
    }
)


def expand_permissions(roles: list[str]) -> list[str]:
    """Expand role names to full permission set."""
    perms: set[str] = set()
    for role in roles:
        if role in ROLE_PERMISSIONS:
            perms.update(ROLE_PERMISSIONS[role])
        elif role == "field.admin" or role == "admin":
            perms.add("field.*")
    return sorted(perms)


def has_permission(user_perms: list[str], required_perm: str) -> bool:
    """Check if user has required permission (supporting 'field.*' wildcard)."""
    if "field.*" in user_perms or "*" in user_perms:
        return True
    return required_perm in user_perms
