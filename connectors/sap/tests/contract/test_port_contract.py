"""Port Contract Test Suite for ErpPort Implementations (Task T1.060 / FR1.011).

Runs uniform contract scenarios against SimAdapter (using in-process erp-sim app)
and verifies S4ODataAdapter interface conformity.
"""

import uuid

import pytest
from erp_sim.app import app as erpsim_app
from erp_sim.seed import reset_database
from field_sap.ports.erp_port import ErpError, ErpErrorKind, ErpPort, ErpPostingRequest
from field_sap.s4.adapter import S4Config, S4ODataAdapter
from field_sap.sim.adapter import SimAdapter


@pytest.fixture(scope="module", autouse=True)
def setup_contract_db():
    reset_database("100")
    yield


@pytest.fixture
def sim_adapter():
    return SimAdapter(app=erpsim_app)


@pytest.mark.contract
def test_port_protocol_conformance(sim_adapter):
    """Verify SimAdapter conforms to ErpPort Protocol."""
    assert isinstance(sim_adapter, ErpPort)


@pytest.mark.contract
def test_s4_adapter_protocol_and_not_implemented():
    """Verify S4ODataAdapter conforms to ErpPort and raises NotImplementedError in F0."""
    cfg = S4Config(base_url="https://s4hana.sample.corp:44300")
    s4 = S4ODataAdapter(cfg)
    assert isinstance(s4, ErpPort)

    req = ErpPostingRequest(
        idempotency_key="test_k1",
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        posting_date="2026-10-27",
        header_data={"DeliveryDocument": "180000001"},
        items=(),
    )

    with pytest.raises(NotImplementedError) as exc:
        import asyncio

        asyncio.run(s4.post_inbound_goods_receipt(req))
    assert "S4 adapter: post_inbound_goods_receipt not implemented in F0" in str(exc.value)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_sim_adapter_goods_receipt_and_cancellation_contract(sim_adapter):
    """Verify full Goods Receipt and Cancellation contract flow on SimAdapter."""
    key = f"contract_gr_{uuid.uuid4().hex[:8]}"
    req = ErpPostingRequest(
        idempotency_key=key,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        posting_date="2026-10-27",
        header_data={"DeliveryDocument": "180000005"},
        items=(),
    )

    # 1. Post Goods Receipt
    res = await sim_adapter.post_inbound_goods_receipt(req)
    assert res.document_number.startswith("4900")
    assert res.fiscal_year == "2026"
    assert res.document_family == "GoodsReceipt"

    # 2. Cancel Material Document
    cancel_req = ErpPostingRequest(
        idempotency_key=f"contract_cancel_{uuid.uuid4().hex[:8]}",
        doc_family="Cancellation",
        site_id="WH1",
        plant="1010",
        posting_date="2026-10-27",
        header_data={
            "MaterialDocument": res.document_number,
            "MaterialDocumentYear": res.fiscal_year,
        },
        items=(),
    )
    cancel_res = await sim_adapter.cancel_material_document(cancel_req)
    assert cancel_res.reversal_of == res.document_number

    # 3. Repeat cancel with a new key fails with ErpError kind BUSINESS
    cancel_req_2 = ErpPostingRequest(
        idempotency_key=f"contract_cancel_2_{uuid.uuid4().hex[:8]}",
        doc_family="Cancellation",
        site_id="WH1",
        plant="1010",
        posting_date="2026-10-27",
        header_data={
            "MaterialDocument": res.document_number,
            "MaterialDocumentYear": res.fiscal_year,
        },
        items=(),
    )
    with pytest.raises(ErpError) as exc_info:
        await sim_adapter.cancel_material_document(cancel_req_2)
    assert exc_info.value.kind == ErpErrorKind.BUSINESS
    assert exc_info.value.retryable is False
