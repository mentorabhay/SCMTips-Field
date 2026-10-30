package com.scmtips.field.core.voice.asr

data class AsrCandidate(
    val transcript: String,
    val confidence: Float,
)

data class AsrResult(
    val primaryTranscript: String,
    val confidence: Float,
    val nBest: List<AsrCandidate> = emptyList(),
    val isOffline: Boolean = true,
)

interface AsrEngine {
    suspend fun recognise(
        pcmData: ByteArray,
        locale: String = "en",
    ): AsrResult?
}

/**
 * A platform recogniser (Android SpeechRecognizer with EXTRA_PREFER_OFFLINE, or Vosk) wrapped as raw
 * candidates. Implementations live in the app module because they need Android APIs.
 */
fun interface RecognizerBackend {
    suspend fun recognise(pcmData: ByteArray, locale: String): List<AsrCandidate>
}

/**
 * ASR adapter (T2.033; FR2.031, FR2.035; D2.04). Tries the primary backend, then the fallback, and
 * returns transcript, confidence and at most 5 n-best candidates only; audio never leaves memory.
 * Returns null when no backend produced a candidate: there is no built-in default transcript.
 */
class OfflineAsrEngine(
    private val primary: RecognizerBackend,
    private val fallback: RecognizerBackend? = null,
) : AsrEngine {
    companion object {
        const val N_BEST = 5
    }

    override suspend fun recognise(pcmData: ByteArray, locale: String): AsrResult? {
        val candidates = runCatching { primary.recognise(pcmData, locale) }.getOrNull().orEmpty()
            .ifEmpty { fallback?.let { runCatching { it.recognise(pcmData, locale) }.getOrNull() }.orEmpty() }
        if (candidates.isEmpty()) return null
        val ranked = candidates.sortedByDescending { it.confidence }.take(N_BEST)
        return AsrResult(ranked.first().transcript, ranked.first().confidence, ranked, isOffline = true)
    }
}
