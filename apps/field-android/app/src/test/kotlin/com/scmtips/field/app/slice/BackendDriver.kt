package com.scmtips.field.app.slice

import com.scmtips.field.app.net.FieldSession



import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Drives the app's real FieldSession + ReceiveFlow against a running field-test stack, with no Android or
 * glasses: register, wait for the delivery, scan each line's material, count, post, confirm, wait for the
 * erp.posted event. Run by `uv run python -m tools.android_check.drive_backend` (not a JUnit test: it needs
 * the live stack from tools/dev_stack).
 */
object BackendDriver {
    @JvmStatic
    fun main(args: Array<String>) = runBlocking {
        val pairing = PairingPayload.parse(args[0])
        val delivery = args[1]
        val s = FieldSession(pairing.apiBaseUrl, pairing.coreToken, null)
        val id = s.registerPhone("jvm-drive-${System.nanoTime()}", "JVM driver", "Linux", "check")
        println("registered phone $id")
        var task = s.receiveTasks(pairing.siteId).firstOrNull { it.erpRef == delivery }
        var tries = 0
        while (task == null && tries++ < 30) { delay(2000); task = s.receiveTasks(pairing.siteId).firstOrNull { it.erpRef == delivery } }
        requireNotNull(task) { "delivery $delivery not imported" }
        val speaker = object : Speaker {
            override fun say(text: String) = println("SAY: $text")
            override fun earcon(cue: EarconCue) = println("EARCON: $cue")
        }
        val f = ReceiveFlow(task, s, speaker)
        f.start()
        for (l in task.lines) {
            f.onBarcode(l.material ?: error("line without material"))
            f.onSpeech("count ${l.expectedQty.toInt()}", 0.92f)
        }
        f.onSpeech("post", 0.95f)
        f.onSpeech("confirm", 0.93f)
        var last: String? = null
        repeat(40) {
            for (ev in s.pollEvents(last)) {
                last = (ev["id"] as JsonPrimitive).contentOrNull
                val p = ev["payload"] as JsonObject
                f.onLiveEvent((ev["kind"] as JsonPrimitive).content, (p["erp_document_id"] as? JsonPrimitive)?.contentOrNull,
                    (p["doc_number"] as? JsonPrimitive)?.contentOrNull)
                if ((ev["kind"] as JsonPrimitive).content == "erp.posted") { println("RESULT: PASS"); return@runBlocking }
            }
            delay(1500)
        }
        println("RESULT: FAIL (no erp.posted)")
    }
}
