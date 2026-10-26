"""SCMTIPS Field Role-to-Permission Mapping (Task T1.039 / FR1.033)."""

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "field.operator": [
        "field.capture.create",
        "field.task.read",
        "field.task.execute",
        "field.location.read",
        "field.material.read",
        "field.site.read",
    ],
    "field.technician": [
        "field.capture.create",
        "field.asset.read",
        "field.asset.inspect",
        "field.part.replace",
        "field.task.execute",
        "field.location.read",
        "field.site.read",
    ],
    "field.supervisor": [
        "field.discrepancy.read",
        "field.discrepancy.approve",
        "field.recount.assign",
        "field.override.grant",
        "field.device.read",
        "field.device.revoke",
        "field.task.manage",
        "field.site.read",
    ],
    "inventory.controller": [
        "field.stock.read",
        "field.stock.adjust",
        "field.audit.review",
        "field.recount.assign",
        "field.tolerance.configure",
        "field.discrepancy.approve",
        "field.site.read",
    ],
    "field.integration": [
        "field.material.sync",
        "field.export.execute",
        "field.sync.trigger",
        "field.erp.post",
    ],
    "field.viewer": [
        "field.site.read",
        "field.location.read",
        "field.material.read",
        "field.task.read",
    ],
    "field.admin": [
        "field.*",
    ],
}


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
