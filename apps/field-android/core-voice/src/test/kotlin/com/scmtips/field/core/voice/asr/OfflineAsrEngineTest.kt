package com.scmtips.field.core.voice.asr

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** OfflineAsrEngine adapter rules (T2.033): primary then fallback, n-best capped at 5, no invented transcript. */
class OfflineAsrEngineTest {
    private val pcm = ByteArray(16)

    @Test
    fun nBestIsSortedAndCappedAtFive() = runBlocking {
        val engine = OfflineAsrEngine(primary = { _, _ ->
            (1..8).map { AsrCandidate("c$it", it / 10f) }
        })
        val r = engine.recognise(pcm, "en")!!
        assertEquals("c8", r.primaryTranscript)
        assertEquals(0.8f, r.confidence, 0f)
        assertEquals(listOf("c8", "c7", "c6", "c5", "c4"), r.nBest.map { it.transcript })
    }

    @Test
    fun fallbackIsUsedWhenPrimaryFailsOrIsEmpty() = runBlocking {
        val failing = OfflineAsrEngine(primary = { _, _ -> error("no offline model") }, fallback = { _, _ -> listOf(AsrCandidate("post", 0.9f)) })
        assertEquals("post", failing.recognise(pcm, "en")!!.primaryTranscript)
        val empty = OfflineAsrEngine(primary = { _, _ -> emptyList() }, fallback = { _, _ -> listOf(AsrCandidate("next", 0.9f)) })
        assertEquals("next", empty.recognise(pcm, "en")!!.primaryTranscript)
    }

    @Test
    fun noCandidateMeansNoResult() = runBlocking {
        assertNull(OfflineAsrEngine(primary = { _, _ -> emptyList() }).recognise(pcm, "en"))
        assertNull(OfflineAsrEngine(primary = { _, _ -> error("x") }, fallback = { _, _ -> error("y") }).recognise(pcm, "en"))
    }

    @Test
    fun localeIsPassedToTheBackend() = runBlocking {
        var seen = ""
        OfflineAsrEngine(primary = { _, loc -> seen = loc; listOf(AsrCandidate("x", 1f)) }).recognise(pcm, "hi-IN")
        assertEquals("hi-IN", seen)
    }
}
