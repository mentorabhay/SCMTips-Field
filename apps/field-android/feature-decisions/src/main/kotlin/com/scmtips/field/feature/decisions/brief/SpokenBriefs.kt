package com.scmtips.field.feature.decisions.brief

import com.scmtips.field.feature.decisions.api.CoreHttp
import com.scmtips.field.feature.decisions.api.CoreJson
import com.scmtips.field.feature.decisions.api.CoreJson.s
import com.scmtips.field.feature.decisions.api.CoreUrls
import com.scmtips.field.feature.decisions.api.HttpBody
import com.scmtips.field.feature.decisions.api.HttpCall
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/** What the approver hears: the model's ~20 s version checked by the core, or the core's own template. */
data class SpokenBrief(val text: String, val source: String, val reasons: List<String> = emptyList()) {
    companion object {
        const val MODEL = "model"
        const val TEMPLATE = "template"
    }
}

fun interface BriefSource {
    /** Never throws: on any trouble the answer is the template ([SpokenBrief.TEMPLATE]). */
    suspend fun spoken(decisionId: String, templateText: String): SpokenBrief
}

/**
 * `POST {field-api}/v1/briefs/spoken {decision_id, template_text}` (M4 contract §4, stream M builds it):
 * field-api asks Muse for a spoken version, sends it to the core's number check and answers
 * `{text, source: "model"|"template", reasons[]}`. The wearable token travels as `X-Core-Token` (forwarded
 * to the core, never stored by field-api) with `X-Device-Id`; the field token, when the phone has one,
 * as the usual Authorization. Any error, an empty text or a slow answer ([deadlineMs]) speaks the template.
 */
class FieldBriefClient(
    private val fieldApiBaseUrl: () -> String?,
    private val coreToken: () -> String?,
    private val deviceId: () -> String,
    private val fieldToken: suspend () -> String?,
    private val http: CoreHttp,
    private val deadlineMs: Long = 8_000,
    private val log: (String) -> Unit = {},
) : BriefSource {
    override suspend fun spoken(decisionId: String, templateText: String): SpokenBrief {
        val template = SpokenBrief(templateText, SpokenBrief.TEMPLATE)
        val base = fieldApiBaseUrl() ?: return template.also { log("brief: no field-api address, template spoken") }
        val token = coreToken() ?: return template
        return try {
            withTimeoutOrNull(deadlineMs) {
                val bearer = runCatching { fieldToken() }.getOrNull()
                val reply = http.execute(request(base, decisionId, templateText, token, deviceId(), bearer))
                if (!reply.ok) {
                    log("brief: field-api answered HTTP ${reply.status}, template spoken")
                    return@withTimeoutOrNull template
                }
                parse(reply.body, templateText)
            } ?: template.also { log("brief: no answer within ${deadlineMs / 1000} s, template spoken") }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            log("brief: ${e.javaClass.simpleName}, template spoken")
            template
        }
    }

    companion object {
        const val PATH = "/v1/briefs/spoken"

        fun request(base: String, decisionId: String, templateText: String, coreToken: String, deviceId: String, fieldToken: String?): HttpCall {
            val headers = buildMap {
                put("X-Core-Token", coreToken)
                put("X-Device-Id", deviceId)
                fieldToken?.let { put("Authorization", "Bearer $it") }
            }
            val body = buildJsonObject { put("decision_id", decisionId); put("template_text", templateText) }
            return HttpCall("POST", CoreUrls.normalise(base).orEmpty() + PATH, headers, HttpBody.Json(body.toString()))
        }

        /** The answer, or the template when the text is missing or blank. */
        fun parse(text: String, templateText: String): SpokenBrief {
            val o = CoreJson.obj(text) ?: return SpokenBrief(templateText, SpokenBrief.TEMPLATE)
            val spoken = o.s("text")?.trim().orEmpty()
            val reasons = (o["reasons"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            if (spoken.isEmpty()) return SpokenBrief(templateText, SpokenBrief.TEMPLATE, reasons)
            val source = if (o.s("source") == SpokenBrief.MODEL) SpokenBrief.MODEL else SpokenBrief.TEMPLATE
            return SpokenBrief(spoken, source, reasons)
        }
    }
}
