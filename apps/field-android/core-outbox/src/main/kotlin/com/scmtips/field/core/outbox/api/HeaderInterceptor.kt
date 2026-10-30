package com.scmtips.field.core.outbox.api

import okhttp3.Interceptor
import okhttp3.Response
import com.scmtips.field.core.common.UUIDv7
import java.util.UUID

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
