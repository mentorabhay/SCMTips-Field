package com.scmtips.field.feature.decisions.api

import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * [CoreHttp] over OkHttp (the same enqueue + cancellable await as the core's wearable client). No
 * logging interceptor: bodies and the Authorization / X-Core-Token headers are never written anywhere.
 */
class OkHttpCoreHttp(private val client: OkHttpClient = defaultClient()) : CoreHttp {
    override suspend fun execute(call: HttpCall): HttpReply {
        val rb = Request.Builder().url(call.url)
        call.headers.forEach { (k, v) -> rb.header(k, v) }
        rb.method(call.method, body(call))
        return client.newCall(rb.build()).await().use { r -> HttpReply(r.code, r.body?.string().orEmpty()) }
    }

    private fun body(call: HttpCall): RequestBody? = when (val b = call.body) {
        is HttpBody.Json -> b.text.toRequestBody(JSON)
        is HttpBody.Multipart -> MultipartBody.Builder().setType(MultipartBody.FORM).apply {
            b.parts.forEach { p ->
                val bytes = p.bytes
                if (bytes != null) addFormDataPart(p.name, p.fileName, bytes.toRequestBody(p.mimeType?.toMediaType()))
                else addFormDataPart(p.name, p.value.orEmpty())
            }
        }.build()
        null -> if (call.method == "GET" || call.method == "DELETE") null else ByteArray(0).toRequestBody(null)
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }
}

private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    cont.invokeOnCancellation { runCatching { cancel() } }
    enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }

        override fun onResponse(call: Call, response: Response) {
            cont.resume(response)
        }
    })
}
