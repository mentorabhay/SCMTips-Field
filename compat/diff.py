"""OpenAPI Compatibility Difference Classifier (Task T1.033 / PR1.13 / TC1.128, TC1.129)."""

from typing import Any


def classify_openapi_diff(
    base_spec: dict[str, Any],
    mutated_spec: dict[str, Any],
    used_paths: set[str],
) -> tuple[str, list[str]]:
    """Classify differences between base and mutated OpenAPI specs for used endpoints.

    Returns:
        ("BREAK", reasons) if any breaking change is detected.
        ("NO_BREAK", []) if changes are strictly additive/backwards-compatible.
    """
    reasons: list[str] = []
    base_paths = base_spec.get("paths", {})
    mutated_paths = mutated_spec.get("paths", {})

    for path in used_paths:
        if path not in base_paths:
            continue

        # 1. Path removed
        if path not in mutated_paths:
            reasons.append(f"PATH_REMOVED: Endpoint {path} was removed")
            continue

        base_ops = base_paths[path]
        mutated_ops = mutated_paths[path]

        for method, base_op in base_ops.items():
            if method.startswith("x-"):
                continue

            # 2. Method removed
            if method not in mutated_ops:
                reasons.append(f"METHOD_REMOVED: Method {method.upper()} on {path} was removed")
                continue

            mutated_op = mutated_ops[method]

            # 3. Check response fields
            base_responses = base_op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
            mutated_responses = mutated_op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})

            base_props = set(base_responses.get("properties", {}).keys())
            mutated_props = set(mutated_responses.get("properties", {}).keys())

            removed_props = base_props - mutated_props
            if removed_props:
                reasons.append(f"RESP_FIELD_REMOVED: Response fields {removed_props} removed on {path}")

            # 4. Check required request fields
            base_req = set(base_op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("required", []))
            mutated_req = set(mutated_op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("required", []))

            new_required = mutated_req - base_req
            if new_required:
                reasons.append(f"NEW_REQUIRED: New required request fields {new_required} added to {path}")

    verdict = "BREAK" if reasons else "NO_BREAK"
    return verdict, reasons
