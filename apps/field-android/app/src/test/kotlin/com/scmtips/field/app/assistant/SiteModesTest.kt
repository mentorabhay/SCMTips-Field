package com.scmtips.field.app.assistant

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.RecordingTransport
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Site mode from `GET /v1/sites` (`mode`) or `GET /v1/codes/{code}` (`site_mode`), M3 contract §2. */
class SiteModesTest {
    private fun json(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    @Test
    fun parsesTheSiteListAndTheCodeLookup() {
        val sites = json("""{"items": [{"id": "a", "mode": "production"}, {"id": "home", "mode": "sandbox"}, {"id": "b", "mode": "weird"}]}""")
        assertEquals("sandbox", SiteModes.fromSites(sites, "home"))
        assertEquals("production", SiteModes.fromSites(sites, "a"))
        assertNull("an unknown mode word is not trusted", SiteModes.fromSites(sites, "b"))
        assertNull(SiteModes.fromSites(sites, "zzz"))

        val info = SiteModes.parseCode(json("""{"code": "8901234567890", "kind": "material",
            "material": {"material": "HOME-0001", "description": "Tea", "uom": "EA"}, "bin": null, "site_mode": "sandbox"}"""))!!
        assertEquals(CodeInfo("8901234567890", "material", "HOME-0001", "Tea", null, "sandbox"), info)
        assertEquals("unknown", SiteModes.parseCode(json("""{"code": "X", "material": null}"""))!!.kind)
        assertEquals("GET /v1/codes/A%2FB%201?site_id=home", SiteModes.codeLookup(" A/B 1 ", "home").let { "${it.method} ${it.path}" })
    }

    @Test
    fun sandboxIsAskedOnceThenRemembered() = runBlocking {
        val tr = RecordingTransport()
        tr.rules += { r -> if (r.path.startsWith("/v1/codes/")) ApiResult.Ok(200, json("""{"code": "X", "kind": "unknown", "site_mode": "sandbox"}""")) else null }
        val m = SiteModes(tr)
        assertTrue(m.allowsNewItems("home", "X"))
        assertTrue(m.allowsNewItems("home", "Y"))
        assertEquals(1, tr.all("/v1/codes/").size)
    }

    @Test
    fun productionOrNoAnswerRefusesNewItems() = runBlocking {
        val tr = RecordingTransport()
        tr.rules += { r -> if (r.path.startsWith("/v1/sites")) ApiResult.Ok(200, json("""{"items": [{"id": "wh", "mode": "production"}]}""")) else null }
        tr.rules += { r -> if (r.path.startsWith("/v1/codes/")) ApiResult.Problem(404, null, "Not Found", null) else null }
        val m = SiteModes(tr)
        m.prime("wh")
        assertFalse(m.allowsNewItems("wh", "X"))
        assertEquals("a known production site is not asked again", 0, tr.all("/v1/codes/").size)
        assertFalse("an older field-api without the codes route: production", m.allowsNewItems("other", "X"))
        assertNull(m.modeOf("other"))
    }
}
