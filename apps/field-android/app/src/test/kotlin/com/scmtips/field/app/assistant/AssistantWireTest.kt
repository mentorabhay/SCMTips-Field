package com.scmtips.field.app.assistant

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobState
import com.scmtips.field.app.jobs.RecordingTransport
import com.scmtips.field.app.jobs.obj
import com.scmtips.field.app.jobs.str
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** `POST /v1/assistant/turns` as docs/design/M3_CONTRACT.md §4 writes it: request body, reply parsing, session id. */
class AssistantWireTest {
    private fun json(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    @Test
    fun requestBodyHasEveryContractFieldWithNullsForTheMissingOnes() {
        val req = AssistantWire.request("key-1", null, AssistantTurn("site-1", AssistantEvent.SESSION_START))
        assertEquals("POST", req.method)
        assertEquals("/v1/assistant/turns", req.path)
        assertEquals("key-1", req.idempotencyKey)
        val b = req.body!!
        assertEquals(setOf("session_id", "site_id", "event", "text", "code", "photo_jpeg_b64", "client_state"), b.keys)
        assertEquals(JsonNull, b["session_id"])
        assertEquals("site-1", req.str("site_id"))
        assertEquals("session_start", req.str("event"))
        assertEquals(JsonNull, b["text"]); assertEquals(JsonNull, b["code"]); assertEquals(JsonNull, b["photo_jpeg_b64"])
        assertEquals(setOf("task_id", "line_id", "step"), req.obj("client_state")!!.keys)
    }

    @Test
    fun requestCarriesWordsCodePhotoAndTheJobState() {
        val t = AssistantTurn("site-1", AssistantEvent.UNKNOWN_CODE, text = "a box of tea", code = "8901234567890", photoJpegB64 = "/9j/AA==",
            state = JobState("t-rcv", "l10", "line.scan"))
        val req = AssistantWire.request("k", "sess-9", t)
        assertEquals("sess-9", req.str("session_id"))
        assertEquals("unknown_code", req.str("event"))
        assertEquals("a box of tea", req.str("text"))
        assertEquals("8901234567890", req.str("code"))
        assertEquals("/9j/AA==", req.str("photo_jpeg_b64"))
        val cs = req.obj("client_state")!!
        assertEquals("t-rcv", cs.str("task_id")); assertEquals("l10", cs.str("line_id")); assertEquals("line.scan", cs.str("step"))
        assertEquals(listOf("session_start", "utterance", "scan", "unknown_code", "photo", "step_done", "pause", "resume", "session_end"),
            AssistantEvent.entries.map { it.wire })
    }

    @Test
    fun replyParsesSayCardEveryActionTypeAiAndCost() {
        val r = AssistantWire.parse(json("""
            {"session_id": "s-1", "say": " Start the delivery. ", "card": {"title": "Delivery 1800000022", "body": "2 items"},
             "actions": [{"type": "open_task", "task_id": "t-rcv"},
                         {"type": "command", "command": "count", "value": 4},
                         {"type": "command", "command": "ALL_HERE"},
                         {"type": "refresh_task", "task_id": "t-rcv", "focus_code": "8901234567890"},
                         {"type": "listen", "mode": "free"}],
             "ai": "model", "cost_usd": 0.0021}
        """))!!
        assertEquals("s-1", r.sessionId)
        assertEquals("Start the delivery.", r.say)
        assertEquals(AssistantCard("Delivery 1800000022", "2 items"), r.card)
        assertEquals(listOf(
            AssistantAction.OpenTask("t-rcv"),
            AssistantAction.Command("count", 4),
            AssistantAction.Command("all_here", null),
            AssistantAction.RefreshTask("t-rcv", "8901234567890"),
            AssistantAction.Listen("free"),
        ), r.actions)
        assertEquals("model", r.ai)
        assertEquals(0.0021, r.costUsd!!, 1e-9)
        assertTrue(r.dropped.isEmpty())
    }

    @Test
    fun confirmAndUnknownActionsAreDroppedNeverParsed() {
        val r = AssistantWire.parse(json("""
            {"session_id": "s-1", "say": "ok", "actions": [
               {"type": "command", "command": "confirm"}, {"type": "command", "command": "yes"},
               {"type": "command", "command": "count"}, {"type": "post_now"}, "junk",
               {"type": "command", "command": "post"}]}
        """))!!
        assertEquals(listOf(AssistantAction.Command("post", null)), r.actions)
        assertEquals(5, r.dropped.size)
        assertTrue("there is no confirm command", "confirm" !in AssistantWire.COMMANDS && "yes" !in AssistantWire.COMMANDS)
    }

    @Test
    fun aReplyWithoutSessionIdIsNotTrusted() {
        assertNull(AssistantWire.parse(json("""{"say": "hello", "actions": []}""")))
        val r = AssistantWire.parse(json("""{"session_id": "s", "card": {"title": "", "body": ""}, "listen": 1}"""))!!
        assertNull(r.card); assertEquals("", r.say); assertTrue(r.actions.isEmpty())
    }

    @Test
    fun clientKeepsTheSessionIdStartsFreshAndForgetsItAtTheEnd() = runBlocking {
        val tr = RecordingTransport()
        var n = 0
        tr.rules += { req -> if (req.path == AssistantWire.PATH) ApiResult.Ok(200, json("""{"session_id": "s-${++n}", "say": "hi", "actions": []}""")) else null }
        val c = AssistantClient(tr) { "key-${tr.sent.size}" }
        val first = c.turn(AssistantTurn("site-1", AssistantEvent.SESSION_START)) as AssistantOutcome.Ok
        assertEquals("s-1", first.reply.sessionId)
        c.turn(AssistantTurn("site-1", AssistantEvent.UTTERANCE, text = "what's next"))
        assertEquals("the second turn names the session", "s-1", tr.sent[1].str("session_id"))
        assertEquals("s-2", c.sessionId)
        c.turn(AssistantTurn("site-1", AssistantEvent.SESSION_START))
        assertEquals("session_start always asks for a new session", JsonNull, tr.sent[2].body!!["session_id"])
        c.turn(AssistantTurn("site-1", AssistantEvent.SESSION_END))
        assertNull(c.sessionId)
        assertEquals("every turn has its own Idempotency-Key", 4, tr.sent.map { it.idempotencyKey }.toSet().size)
    }

    @Test
    fun httpProblemsOfflineAndBadBodiesAreFailuresNotCrashes() = runBlocking {
        val tr = RecordingTransport()
        val c = AssistantClient(tr) { "k" }
        tr.rules += { ApiResult.Problem(503, "FIELD-AI-503", "Unavailable", null) }
        assertEquals(AssistantOutcome.Failed("HTTP 503 FIELD-AI-503"), c.turn(AssistantTurn("s", AssistantEvent.UTTERANCE, text = "hi")))
        tr.rules.clear(); tr.rules += { ApiResult.Offline("timeout") }
        assertEquals(AssistantOutcome.Failed("offline: timeout"), c.turn(AssistantTurn("s", AssistantEvent.UTTERANCE, text = "hi")))
        tr.rules.clear() // default answer {"ok": true}: no session id
        assertTrue(c.turn(AssistantTurn("s", AssistantEvent.UTTERANCE, text = "hi")) is AssistantOutcome.Failed)
    }
}
