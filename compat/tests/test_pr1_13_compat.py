"""Property Test PR1.13: OpenAPI Compatibility Change Detection (Hypothesis)."""

import copy
from typing import Any

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from compat.diff import classify_openapi_diff

BASE_SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/.well-known/jwks.json": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "properties": {
                                        "keys": {"type": "array"},
                                        "kty": {"type": "string"},
                                        "kid": {"type": "string"},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/v1/auth/token": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "properties": {"principal_id": {"type": "string"}},
                                "required": ["principal_id"],
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "properties": {
                                        "access_token": {"type": "string"},
                                        "token_type": {"type": "string"},
                                    }
                                }
                            }
                        }
                    }
                },
            }
        },
    },
}

USED_PATHS = {"/.well-known/jwks.json", "/api/v1/auth/token"}


@pytest.mark.property
@settings(max_examples=40)
@given(
    st.sampled_from(["remove_path", "remove_field", "add_required", "add_optional"]),
    st.text(min_size=2, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"),
)
def test_pr1_13_compat_change_detection(mutation_kind: str, field_name: str) -> None:
    """PR1.13: Classifier reports BREAK iff mutation breaks used endpoints (TC1.128, TC1.129)."""
    mutated = copy.deepcopy(BASE_SPEC)

    if mutation_kind == "remove_path":
        del mutated["paths"]["/.well-known/jwks.json"]
        verdict, reasons = classify_openapi_diff(BASE_SPEC, mutated, USED_PATHS)
        assert verdict == "BREAK"
        assert any("PATH_REMOVED" in r for r in reasons)

    elif mutation_kind == "remove_field":
        # Remove required kid from JWKS
        del mutated["paths"]["/.well-known/jwks.json"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["kid"]
        verdict, reasons = classify_openapi_diff(BASE_SPEC, mutated, USED_PATHS)
        assert verdict == "BREAK"
        assert any("RESP_FIELD_REMOVED" in r for r in reasons)

    elif mutation_kind == "add_required":
        # Add a new required request field
        mutated["paths"]["/api/v1/auth/token"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"].append(field_name)
        verdict, reasons = classify_openapi_diff(BASE_SPEC, mutated, USED_PATHS)
        assert verdict == "BREAK"
        assert any("NEW_REQUIRED" in r for r in reasons)

    elif mutation_kind == "add_optional":
        # Add an optional response field -> strictly backwards-compatible
        props = mutated["paths"]["/.well-known/jwks.json"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
        props[f"opt_{field_name}"] = {"type": "string"}
        verdict, reasons = classify_openapi_diff(BASE_SPEC, mutated, USED_PATHS)
        assert verdict == "NO_BREAK"
        assert len(reasons) == 0
