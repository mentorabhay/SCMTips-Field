package com.scmtips.field.core.outbox.api

import okhttp3.Interceptor
import okhttp3.Response
import java.security.SecureRandom
import java.util.UUID

/**
 * Generates monotonic UUIDv7 IDs compliant with RFC 9562.
 */
object UUIDv7 {
    private val random = SecureRandom()

    fun generate(): String {
        val timestamp = System.currentTimeMillis()
        val randomBytes = ByteArray(10)
        random.nextBytes(randomBytes)

        val msb = (timestamp shl 16) or (0x7000L) or ((randomBytes[0].toLong() and 0x0F) shl 8) or (randomBytes[1].toLong() and 0xFF)
        val lsb = (0x8000000000000000UL.toLong()) or
                ((randomBytes[2].toLong() and 0x3F) shl 56) or
                ((randomBytes[3].toLong() and 0xFF) shl 48) or
                ((randomBytes[4].toLong() and 0xFF) shl 40) or
                ((randomBytes[5].toLong() and 0xFF) shl 32) or
                ((randomBytes[6].toLong() and 0xFF) shl 24) or
                ((randomBytes[7].toLong() and 0xFF) shl 16) or
                ((randomBytes[8].toLong() and 0xFF) shl 8) or
                (randomBytes[9].toLong() and 0xFF)

        return UUID(msb, lsb).toString()
    }
}

/**
 * In-memory token provider interface for Authorization header.
 */
interface TokenProvider {
    fun getFieldToken(): String?
}

/**
 * OkHttp Interceptor adding X-Request-Id, W3C traceparent, Authorization, and Idempotency-Key.
 * (Task T2.003 / FR2.045).
 */
class HeaderInterceptor(
    private val tokenProvider: TokenProvider? = null
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val builder = original.newBuilder()

        // 1. Monotonic X-Request-Id (UUIDv7)
        if (original.header("X-Request-Id") == null) {
            builder.header("X-Request-Id", UUIDv7.generate())
        }

        // 2. W3C traceparent: 00-{32 hex trace_id}-{16 hex span_id}-01
        if (original.header("traceparent") == null) {
            val traceId = UUID.randomUUID().toString().replace("-", "")
            val spanId = UUID.randomUUID().toString().replace("-", "").take(16)
            builder.header("traceparent", "00-$traceId-$spanId-01")
        }

        // 3. Authorization Bearer token (if available)
        val token = tokenProvider?.getFieldToken()
        if (token != null && original.header("Authorization") == null) {
            builder.header("Authorization", "Bearer $token")
        }

        // 4. Idempotency-Key for POST/PUT requests
        if ((original.method == "POST" || original.method == "PUT") &&
            original.header("Idempotency-Key") == null &&
            !original.url.encodedPath.contains("/auth/exchange")
        ) {
            builder.header("Idempotency-Key", UUIDv7.generate())
        }

        return chain.proceed(builder.build())
    }
}
