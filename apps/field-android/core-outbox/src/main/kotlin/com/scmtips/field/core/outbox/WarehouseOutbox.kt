package com.scmtips.field.core.outbox

/**
 * Warehouse Outbox Adapter (Task T3.065 / FR3.056 / TC3.148).
 *
 * Provides offline queuing and ordered replay for warehouse picking confirms,
 * inventory count commitments, and goods receipts.
 */
class WarehouseOutbox(
    private val outboxWriter: OutboxWriter
) {
    suspend fun stagePickConfirmation(
        deliveryNo: String,
        lineItemNo: String,
        pickedQty: Double,
        bin: String
    ): String {
        return outboxWriter.enqueue(
            topic = "warehouse.pick.confirm",
            queueKey = "OBD:$deliveryNo",
            payload = """{"delivery":"$deliveryNo","item":"$lineItemNo","qty":$pickedQty,"bin":"$bin"}"""
        )
    }

    suspend fun stageInventoryCount(
        piDocNo: String,
        lineId: String,
        countedQty: Double,
        bin: String
    ): String {
        return outboxWriter.enqueue(
            topic = "warehouse.inventory.count",
            queueKey = "PID:$piDocNo",
            payload = """{"pi_doc":"$piDocNo","line":"$lineId","qty":$countedQty,"bin":"$bin"}"""
        )
    }
}
