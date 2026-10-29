"""Outbound Picking Posting Jobs Orchestrator (Task T3.032 / FR3.021 / TC3.118 / PR3.07).

Queues PickOneItem and ConfirmPickingOneItem per line into the ordered posting queue
with queue_key = 'OBD:<delivery_number>' preserving confirm order.
"""

import uuid
from typing import Any


def generate_pick_posting_jobs(
    delivery_no: str,
    lines: list[dict[str, Any]],
    tenant_id: str = "tenant-default",
) -> list[dict[str, Any]]:
    """Generates sequential posting jobs for outbound picking under OBD:<delivery_no>."""
    queue_key = f"OBD:{delivery_no}"
    jobs: list[dict[str, Any]] = []

    seq = 1
    for line in lines:
        line_item = line.get("line_item_no", str(seq * 10).zfill(6))
        picked_qty = float(line.get("picked_qty", 0.0))
        if picked_qty <= 0:
            continue

        # 1. PickOneItem job
        pick_job_id = str(uuid.uuid4())
        jobs.append(
            {
                "id": pick_job_id,
                "tenant_id": tenant_id,
                "queue_key": queue_key,
                "seq": seq,
                "action": "PickOneItem",
                "delivery_no": delivery_no,
                "line_item_no": line_item,
                "quantity": picked_qty,
                "status": "pending",
            }
        )
        seq += 1

        # 2. ConfirmPickingOneItem job
        confirm_job_id = str(uuid.uuid4())
        jobs.append(
            {
                "id": confirm_job_id,
                "tenant_id": tenant_id,
                "queue_key": queue_key,
                "seq": seq,
                "action": "ConfirmPickingOneItem",
                "delivery_no": delivery_no,
                "line_item_no": line_item,
                "quantity": picked_qty,
                "status": "pending",
            }
        )
        seq += 1

    return jobs
