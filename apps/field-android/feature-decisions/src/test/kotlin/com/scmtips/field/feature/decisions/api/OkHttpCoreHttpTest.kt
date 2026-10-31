package com.scmtips.field.feature.decisions.api

import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException

/**
 * The OkHttp layer under [CoreClient] (Gradle unit test; okhttp3 is not on the JVM gate's classpath).
 * A scripted application interceptor answers instead of a server: MockWebServer is not a dependency
 * resolved by this build (rule 2.4). What reaches the interceptor is exactly what OkHttp would send.
 */
class OkHttpCoreHttpTest {
    private class Recorder(private val code: Int, private val body: String, private val fail: Boolean = false) : Interceptor {
        val requests = mutableListOf<Request>()
        val bodies = mutableListOf<String?>()
        override fun intercept(chain: Interceptor.Chain): Response {
            val r = chain.request()
            requests += r
            bodies += r.body?.let { b -> Buffer().also { b.writeTo(it) }.readUtf8() }
            if (fail) throw IOException("connect timed out")
            return Response.Builder().request(r).protocol(Protocol.HTTP_1_1).code(code).message("scripted")
                .body(body.toResponseBody("application/json".toMediaType())).build()
        }
    }

    private fun http(rec: Recorder) = OkHttpCoreHttp(OkHttpClient.Builder().addInterceptor(rec).build())

    @Test
    fun jsonPost_carriesHeadersAndBody_andTheAnswerIsReturnedAsText() = runBlocking {
        val rec = Recorder(201, """{"nonce":"n1"}""")
        val reply = http(rec).execute(HttpCall("POST", "http://core.test/v1/voice/challenges",
            mapOf("Authorization" to "Bearer t", "X-Device-Id" to "dev-1", "X-Requested-With" to "lr"), HttpBody.Json("""{"decision_id":"d1"}""")))
        assertEquals(201, reply.status)
        assertEquals("""{"nonce":"n1"}""", reply.body)
        val req = rec.requests.single()
        assertEquals("POST", req.method)
        assertEquals("http://core.test/v1/voice/challenges", req.url.toString())
        assertEquals("Bearer t", req.header("Authorization"))
        assertEquals("dev-1", req.header("X-Device-Id"))
        assertEquals("lr", req.header("X-Requested-With"))
        assertTrue(req.body!!.contentType().toString().startsWith("application/json"))
        assertEquals("""{"decision_id":"d1"}""", rec.bodies.single())
    }

    @Test
    fun getAndDeleteHaveNoBody_andAnErrorStatusIsAnAnswerNotAnException() = runBlocking {
        val rec = Recorder(401, """{"code":"token_expired"}""")
        val h = http(rec)
        assertEquals(401, h.execute(HttpCall("GET", "http://core.test/v1/wearable/next")).status)
        assertEquals(401, h.execute(HttpCall("DELETE", "http://core.test/v1/wearable/sessions/s1")).status)
        assertNull(rec.requests[0].body)
        assertNull(rec.requests[1].body)
        assertEquals("DELETE", rec.requests[1].method)
    }

    @Test
    fun multipart_hasTheImageFileAndTheTextFields() = runBlocking {
        val rec = Recorder(201, "{}")
        http(rec).execute(HttpCall("POST", "http://core.test/v1/evidence/photos", emptyMap(), HttpBody.Multipart(listOf(
            FormPart.file("image", "evidence.jpg", "image/jpeg", byteArrayOf(1, 2, 3)),
            FormPart.text("subject_kind", "recovery_plan"),
            FormPart.text("consent", "true"),
        ))))
        assertTrue(rec.requests.single().body!!.contentType().toString().startsWith("multipart/form-data; boundary="))
        val body = rec.bodies.single()!!
        assertTrue(body.contains("""Content-Disposition: form-data; name="image"; filename="evidence.jpg""""))
        assertTrue(body.contains("Content-Type: image/jpeg"))
        assertTrue(body.contains("""name="subject_kind""""))
        assertTrue(body.contains("recovery_plan"))
        assertTrue(body.contains("""name="consent""""))
    }

    @Test
    fun noAnswer_isAnIOException() = runBlocking {
        try {
            http(Recorder(200, "", fail = true)).execute(HttpCall("GET", "http://core.test/v1/wearable/next")); fail()
        } catch (e: IOException) { /* expected: CoreClient maps it to CoreException.Network */ }
    }
}
