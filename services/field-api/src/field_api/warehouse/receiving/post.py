"""Goods receipt staging (T3.022 / FR3.010 / TC3.109).

On confirm (API3.06, field_api.tasks.api.confirm_task) the receive task is staged as one
field.erp_document (doc_type GR, movement 101) with ordered posting jobs in queue IBD:<delivery>:
one PATCH ActualDeliveryQuantity per line in confirm order, then PostGoodsReceipt. The worker posts
them through ErpPort and writes the material document number back (field_worker.posting.queue).

This module builds the job list; staging itself is field_api.posting.staging.stage_document.
"""

from collections.abc import Sequence

from field_api.posting.staging import JobSpec

GR_DOC_TYPE = "GR"
GR_MOVEMENT_TYPE = "101"


def goods_receipt_queue_key(delivery_document: str) -> str:
    return f"IBD:{delivery_document}"


def goods_receipt_jobs(delivery_document: str, received: Sequence[tuple[int | str, float]],
                       soft_pegging: bool = False) -> list[JobSpec]:
    """PATCH per (line_no, received_qty) in the given order, then one PostGoodsReceipt.

    ``soft_pegging`` (M3 sandbox receipts): each PATCH also sets the delivery quantity to the received one,
    so expected = counted in the ERP too.
    """
    if not received:
        raise ValueError("a goods receipt needs at least one line")
    jobs = [
        JobSpec("InboundDeliveryItem", {
            "DeliveryDocument": delivery_document,
            "DeliveryDocumentItem": str(line_no).zfill(6),
            "ActualDeliveryQuantity": f"{max(0.0, qty):.3f}",
            **({"SoftPegging": True} if soft_pegging else {}),
        })
        for line_no, qty in received
    ]
    jobs.append(JobSpec("GoodsReceipt", {"DeliveryDocument": delivery_document}))
    return jobs
