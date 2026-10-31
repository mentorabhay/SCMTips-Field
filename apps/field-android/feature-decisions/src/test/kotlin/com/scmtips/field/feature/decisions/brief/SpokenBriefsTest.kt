package com.scmtips.field.feature.decisions.brief

import com.scmtips.field.feature.decisions.ScriptedHttp
import com.scmtips.field.feature.decisions.api.CoreHttp
import com.scmtips.field.feature.decisions.api.HttpBody
import com.scmtips.field.feature.decisions.api.HttpReply
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The spoken brief from field-api `POST /v1/briefs/spoken` (M4 contract §4), with the template fallback. */
class SpokenBriefsTest {
    private val template = "Supplier A is six days late. Option A: air freight, twelve thousand."
    private val http = ScriptedHttp()
    private val logs = mutableListOf<String>()

    private fun client(base: String? = "http://192.168.1.20:8000/", core: String? = "scmw_core", field: String? = "field-jwt", h: CoreHttp = http, deadline: Long = 8_000) =
        FieldBriefClient({ base }, { core }, { "dev-1" }, { field }, h, deadline) { logs += it }

    @Test
    fun postsDecisionAndTemplate_withTheWearableTokenAsXCoreToken_andReadsTheModelText() = runBlocking {
        http.reply(200, """{"text":"Magnet parts are six days late. Air freight costs twelve thousand.","source":"model","reasons":[]}""")
        val b = client().spoken("d-1", template)
        assertEquals(SpokenBrief("Magnet parts are six days late. Air freight costs twelve thousand.", SpokenBrief.MODEL), b)
        val call = http.calls.single()
        assertEquals("POST", call.method)
        assertEquals("http://192.168.1.20:8000/v1/briefs/spoken", call.url)
        assertEquals("scmw_core", call.headers["X-Core-Token"])
        assertEquals("dev-1", call.headers["X-Device-Id"])
        assertEquals("Bearer field-jwt", call.headers["Authorization"])
        val body = Json.parseToJsonElement((call.body as HttpBody.Json).text).jsonObject
        assertEquals("d-1", body["decision_id"]!!.jsonPrimitive.content)
        assertEquals(template, body["template_text"]!!.jsonPrimitive.content)
        assertFalse(logs.joinToString().contains("scmw_core"))
    }

    @Test
    fun theTemplateAnswer_withTheChecksReasons_isPassedOn() = runBlocking {
        http.reply(200, """{"text":"$template","source":"template","reasons":["number 11000 is not in the template"]}""")
        assertEquals(SpokenBrief(template, SpokenBrief.TEMPLATE, listOf("number 11000 is not in the template")), client().spoken("d-1", template))
    }

    @Test
    fun withoutAFieldToken_theAuthorizationHeaderIsLeftOut() = runBlocking {
        http.reply(200, """{"text":"x","source":"model"}""")
        client(field = null).spoken("d-1", template)
        assertNull(http.calls.single().headers["Authorization"])
    }

    @Test
    fun anyTrouble_speaksTheTemplate() = runBlocking {
        http.reply(500, """{"title":"boom"}""")
        http.fail()
        http.reply(200, "not json")
        http.reply(200, """{"text":"   ","source":"model"}""")
        repeat(4) { assertEquals(SpokenBrief(template, SpokenBrief.TEMPLATE), client().spoken("d-1", template)) }
        // No field-api address or no wearable token: nothing is sent at all.
        assertEquals(SpokenBrief.TEMPLATE, client(base = null).spoken("d-1", template).source)
        assertEquals(SpokenBrief.TEMPLATE, client(core = null).spoken("d-1", template).source)
        assertEquals(4, http.calls.size)
    }

    @Test
    fun aSlowAnswer_speaksTheTemplateAfterTheDeadline() = runBlocking {
        val slow = CoreHttp { awaitCancellation() }
        val b = client(h = slow, deadline = 50).spoken("d-1", template)
        assertEquals(SpokenBrief(template, SpokenBrief.TEMPLATE), b)
        assertTrue(logs.last(), logs.last().contains("no answer"))
    }

    @Test
    fun anUnknownSourceIsTreatedAsTheTemplate() {
        assertEquals(SpokenBrief.TEMPLATE, FieldBriefClient.parse("""{"text":"x","source":"something"}""", template).source)
        assertEquals(HttpReply(200, "").ok, true)
    }
}
