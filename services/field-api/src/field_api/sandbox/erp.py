"""The ERP adapter the sandbox calls, chosen by config (FIELD_ERP_ADAPTER), as the worker chooses its port.

``sim`` (default): erp-sim at FIELD_ERP_SIM_URL through field_sap's simulator adapter.
``s4``: the S/4 adapter, which refuses every sandbox operation (they are not SAP capabilities); a
sandbox site on an S/4 tenant therefore cannot add items (409 FIELD-SBX-409-NOT-SUPPORTED).

The adapter is async; field-api's sandbox handlers are synchronous (FastAPI runs them in its thread
pool), so ``run`` executes one coroutine to completion, also when called from inside an event loop.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from field_sap.ports.erp_port import ErpSandboxPort


def get_sandbox_port(sim_url: str | None = None) -> ErpSandboxPort:
    """``sim_url`` (the hosted sandbox seed's --erp-sim-url) overrides FIELD_ERP_SIM_URL for the simulator."""
    kind = os.getenv("FIELD_ERP_ADAPTER", "sim")
    if kind == "sim":
        from field_sap.sim.adapter import SimAdapter

        url = sim_url if sim_url else os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")
        return SimAdapter(base_url=url)
    from field_sap.s4.adapter import S4Config, S4ODataAdapter

    return S4ODataAdapter(S4Config(base_url=os.getenv("FIELD_S4_BASE_URL", "")))


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion from synchronous code (a worker thread when a loop is already running)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
