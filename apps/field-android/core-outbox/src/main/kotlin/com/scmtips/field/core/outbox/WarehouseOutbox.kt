package com.scmtips.field.core.outbox

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Warehouse Outbox Adapter (Task T3.065 / FR3.056 / TC3.148).
 *
 * Queues warehouse pick confirmations and inventory counts in the same encrypted outbox as captures,
 * ordered per queue key (OBD:<delivery> / PID:<pi doc>) by the outbox's per-key client sequence.
 * Returns the item's UUIDv7 idempotency key. (Previously called a non-existent `enqueue` and never
 * compiled; payloads were string-built JSON.)
 */
class WarehouseOutbox(
    private val outboxWriter: OutboxWriter,
) {
    suspend fun stagePickConfirmation(deliveryNo: String, lineItemNo: String, pickedQty: Double, bin: String): String =
        outboxWriter.commitCapture(
            taskId = "OBD:$deliveryNo",
            payloadType = "warehouse.pick.confirm",
            payloadJson = buildJsonObject {
                put("delivery", deliveryNo); put("item", lineItemNo); put("qty", pickedQty); put("bin", bin)
            }.toString(),
            cropBytes = null,
        ).id

    suspend fun stageInventoryCount(piDocNo: String, lineId: String, countedQty: Double, bin: String): String =
        outboxWriter.commitCapture(
            taskId = "PID:$piDocNo",
            payloadType = "warehouse.inventory.count",
            payloadJson = buildJsonObject {
                put("pi_doc", piDocNo); put("line", lineId); put("qty", countedQty); put("bin", bin)
            }.toString(),
            cropBytes = null,
        ).id
}
