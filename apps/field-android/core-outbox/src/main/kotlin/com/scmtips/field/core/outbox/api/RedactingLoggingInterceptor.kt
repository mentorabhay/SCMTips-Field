package com.scmtips.field.core.outbox.api

import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException

/**
 * Custom OkHttp logging interceptor that guarantees zero leakage of credentials,
 * JWT tokens, or multipart image/audio binary bodies (Task T2.003 / FR2.045 / FR2.066).
 */
class RedactingLoggingInterceptor(
    private val logger: (String) -> Unit = { println(it) }
) : Interceptor {

    @Throws(IOException::class)
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val startNs = System.nanoTime()

        // 1. Redact sensitive headers for log output
        val redactedHeaders = StringBuilder()
        for (i in 0 until request.headers.size) {
            val name = request.headers.name(i)
            val value = when {
                name.equals("Authorization", ignoreCase = true) -> "[REDACTED TOKEN]"
                name.equals("X-Core-Token", ignoreCase = true) -> "[REDACTED TOKEN]"
                else -> request.headers.value(i)
            }
            redactedHeaders.append("  $name: $value\n")
        }

        // 2. Redact multipart / binary request bodies
        val contentType = request.body?.contentType()?.toString() ?: ""
        val bodySummary = when {
            request.body == null -> "(empty body)"
            contentType.contains("multipart", ignoreCase = true) -> "[MULTIPART BINARY BODY REDACTED - Content-Length: ${request.body?.contentLength()} bytes]"
            contentType.contains("image", ignoreCase = true) -> "[IMAGE BINARY REDACTED]"
            contentType.contains("audio", ignoreCase = true) -> "[AUDIO BINARY REDACTED]"
            else -> "(json payload redacted for privacy)"
        }

        logger("[HTTP REQ] ${request.method} ${request.url}\n$redactedHeaders  Body: $bodySummary")

        val response: Response
        try {
            response = chain.proceed(request)
        } catch (e: Exception) {
            logger("[HTTP FAIL] ${request.method} ${request.url} failed: ${e.message}")
            throw e
        }

        val tookMs = (System.nanoTime() - startNs) / 1e6
        logger("[HTTP RES] ${response.code} ${request.url} (${tookMs}ms)")

        return response
    }
}
