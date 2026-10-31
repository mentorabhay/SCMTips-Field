package com.scmtips.field.app.slice

import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.net.FieldSession
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Drives the app's real FieldSession + JobRunner against a running field-test stack, with no Android or
 * glasses: register, wait for the delivery, scan each line's material, count by voice, "post" … "yes",
 * wait for the erp.posted event. Run by `uv run python -m tools.android_check.drive_backend` (not a JUnit
 * test: it needs the live stack from tools/dev_stack).
 */
object BackendDriver {
    @JvmStatic
    fun main(args: Array<String>) = runBlocking {
        val pairing = PairingPayload.parse(args[0])
        val delivery = args[1]
        val s = FieldSession(pairing.apiBaseUrl, pairing.coreToken, null)
        val serial = "jvm-drive-${System.nanoTime()}"
        val key = java.util.UUID.randomUUID().toString()
        val id = s.registerPhone(serial, "JVM driver", "Linux", "check", key)
        println("registered phone $id")
        // PhoneBinding relies on these two answers (owner report 2026-10-31, "Device already bound"):
        val replayed = s.registerPhone(serial, "JVM driver", "Linux", "check", key)
        check(replayed == id) { "same Idempotency-Key must replay the same device, got $replayed for $id" }
        val dup = runCatching { s.registerPhone(serial, "JVM driver", "Linux", "check", java.util.UUID.randomUUID().toString()) }
        val err = dup.exceptionOrNull() as? com.scmtips.field.app.net.HttpError
        check(err?.code == com.scmtips.field.app.net.PhoneBinding.DEVICE_EXISTS) { "same serial, new key must be 409 EXISTS, got $dup" }
        println("re-registration: same key replays $id; new key -> ${err?.code}")
        s.bind(id)
        suspend fun find() = s.tasks(pairing.siteId).firstOrNull { it.type == JobType.RECEIVE && it.refDocNo == delivery }
        var task = find()
        var tries = 0
        while (task == null && tries++ < 30) { delay(2000); task = find() }
        requireNotNull(task) { "delivery $delivery not imported" }
        val speaker = object : Speaker {
            override fun say(text: String) = println("SAY: $text")
            override fun earcon(cue: EarconCue) = println("EARCON: $cue")
        }
        val r = JobRunner(task, s, speaker, id, siteId = pairing.siteId)
        r.start()
        r.act(JobAction.Primary)
        for (l in task.lines) {
            r.act(JobAction.Scanned(l.material ?: error("line without material")))
            r.act(JobAction.Heard("${(l.expectedQty ?: 0.0).toInt()}", 0.92f))
        }
        r.act(JobAction.Heard("post", 0.95f))
        r.act(JobAction.Heard("yes", 0.93f))
        var last: String? = null
        repeat(40) {
            for (ev in s.pollEvents(last)) {
                last = (ev["id"] as JsonPrimitive).contentOrNull
                val kind = (ev["kind"] as JsonPrimitive).content
                val p = (ev["payload"] as? JsonObject).orEmpty().mapValues { (_, v) -> (v as? JsonPrimitive)?.contentOrNull }
                r.onLiveEvent(kind, p)
                if (r.view.value.kind == StepKind.DONE) { println("RESULT: PASS"); return@runBlocking }
                if (r.view.value.kind == StepKind.FAILED) { println("RESULT: FAIL (${r.view.value.body})"); return@runBlocking }
            }
            delay(1500)
        }
        println("RESULT: FAIL (no erp.posted; last step: ${r.view.value.title} / ${r.view.value.message})")
    }
}
