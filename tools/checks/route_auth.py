#!/usr/bin/env python3
"""Every field-api route enforces authentication (verifier finding, 2026-10-30).

AuthMiddleware lets unauthenticated requests through to the route, so each route must depend on
require_principal / require_permission. A few routes are public or authenticate in their own body;
they are listed in PUBLIC with the reason. Any other route without an auth dependency FAILS.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

# (method, path) -> why it may run without the auth dependency
PUBLIC: dict[tuple[str, str], str] = {
    ("GET", "/v1/health"): "liveness probe",
    ("GET", "/v1/ready"): "readiness probe",
    ("POST", "/v1/auth/exchange"): "verifies the core token itself (it is the login)",
    ("GET", "/v1/devices/{device_id}/events"): "SSE: _authorise() verifies the access_token query/header",
    ("GET", "/v1/evidence/{id}"): "bearer principal OR HMAC-signed URL, checked in the handler",
}
AUTH_DEPS = ("require_principal", "require_permission")


def _routes(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":  # FastAPI >= 0.16x wraps included routers
            ctx = getattr(r, "include_context", None)
            yield from _routes(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif isinstance(r, APIRoute):
            yield prefix, r


def _deps(dependant: Any, seen: set[str]) -> set[str]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            seen.add(getattr(sub.call, "__qualname__", repr(sub.call)))
        _deps(sub, seen)
    return seen


def unauthenticated_routes(app: Any = None) -> list[str]:
    if app is None:
        from field_api.app import app

    bad: list[str] = []
    n = 0
    for prefix, route in _routes(list(app.routes)):
        path = prefix + route.path
        deps = _deps(route.dependant, set())
        for method in sorted(route.methods or ()):
            n += 1
            if any(a in d for d in deps for a in AUTH_DEPS) or (method, path) in PUBLIC:
                continue
            bad.append(f"{method} {path} ({route.endpoint.__module__})")
    if n == 0:
        bad.append("no routes found: the walker no longer understands FastAPI's router structure")
    return bad


def main() -> int:
    bad = unauthenticated_routes()
    if bad:
        print(f"[FAIL] {len(bad)} route(s) run without an auth dependency:")
        for b in bad:
            print(f"  - {b}")
        return 1
    print(f"[PASS] every route enforces auth ({len(PUBLIC)} documented public/self-authenticating routes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
