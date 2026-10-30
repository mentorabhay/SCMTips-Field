"""The route-auth gate catches an unauthenticated route and accepts an authenticated one."""

from fastapi import APIRouter, Depends, FastAPI
from field_api.deps import require_permission, require_principal

from tools.checks.route_auth import unauthenticated_routes


def _app() -> FastAPI:
    app = FastAPI()
    r = APIRouter(prefix="/v1/x")

    @r.get("/open")
    def open_route() -> dict[str, str]:
        return {}

    @r.get("/closed")
    def closed_route(p: object = Depends(require_principal)) -> dict[str, str]:
        return {}

    @r.post("/perm")
    def perm_route(p: object = Depends(require_permission("field.site.read"))) -> dict[str, str]:
        return {}

    app.include_router(r)
    return app


def test_gate_flags_only_the_open_route() -> None:
    bad = unauthenticated_routes(_app())
    assert len(bad) == 1 and bad[0].startswith("GET /v1/x/open")


def test_the_real_app_has_no_unauthenticated_route() -> None:
    assert unauthenticated_routes() == []
