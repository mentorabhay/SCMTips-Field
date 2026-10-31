package com.scmtips.field.feature.decisions.api

/**
 * One HTTP exchange as data, so the core client's paths, headers, bodies and error mapping are pure
 * Kotlin and JVM-tested ([CoreClient], [CoreSignIn], the spoken-brief client). [OkHttpCoreHttp] is the
 * only implementation that touches the network.
 *
 * Secrets travel only in [headers]; [toString] never prints them (A-02: tokens are never logged).
 */
data class HttpCall(
    val method: String,
    val url: String,
    val headers: Map<String, String> = emptyMap(),
    val body: HttpBody? = null,
) {
    override fun toString(): String =
        "HttpCall($method $url, headers=${headers.mapValues { (k, v) -> if (k.lowercase() in SECRET_HEADERS) "<redacted>" else v }}, body=${body?.kind})"

    companion object {
        /** Header names (lower case) whose values are credentials. */
        val SECRET_HEADERS = setOf("authorization", "x-core-token")
    }
}

sealed interface HttpBody {
    val kind: String

    /** A JSON document (`application/json; charset=utf-8`). Never logged: it may hold a password. */
    class Json(val text: String) : HttpBody {
        override val kind: String get() = "json"
        override fun toString(): String = "Json(<${text.length} chars>)"
    }

    /** `multipart/form-data` (photo evidence). */
    class Multipart(val parts: List<FormPart>) : HttpBody {
        override val kind: String get() = "multipart"
        override fun toString(): String = "Multipart(${parts.map { it.name }})"
    }
}

/** One multipart field: a plain value, or a file ([bytes] with [fileName] and [mimeType]). */
class FormPart private constructor(
    val name: String,
    val value: String?,
    val fileName: String?,
    val mimeType: String?,
    val bytes: ByteArray?,
) {
    override fun toString(): String = if (bytes != null) "FormPart($name, file=$fileName, $mimeType, ${bytes.size} bytes)" else "FormPart($name=$value)"

    companion object {
        fun text(name: String, value: String) = FormPart(name, value, null, null, null)
        fun file(name: String, fileName: String, mimeType: String, bytes: ByteArray) = FormPart(name, null, fileName, mimeType, bytes)
    }
}

/** An answer. Its body may carry tokens (the sign-in reply), so [toString] shows only the status and size. */
class HttpReply(val status: Int, val body: String) {
    val ok: Boolean get() = status in 200..299
    override fun toString(): String = "HttpReply($status, <${body.length} chars>)"
}

/** The network. Throws [java.io.IOException] when there is no answer at all (offline, TLS, timeout). */
fun interface CoreHttp {
    suspend fun execute(call: HttpCall): HttpReply
}
