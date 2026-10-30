package com.scmtips.field.core.voice

import com.scmtips.field.core.voice.grammar.VoiceGrammarParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** VoiceEventRecorder against FR2.038: every utterance, accepted or not, becomes a voice_event. */
class VoiceEventRecorderTest {

    @Test
    fun fr2_038_everyUtteranceIsRecordedInOrderWithAllFields() {
        val sink = mutableListOf<VoiceEventRecord>()
        var now = 1_000L
        val rec = VoiceEventRecorder(outboxSink = { sink += it }, clock = { now++ })
        val parser = VoiceGrammarParser()
        rec.recordUtterance("T-1", "C-1", parser.parse("count twelve", 0.93f), "en-US")
        rec.recordUtterance("T-1", "C-1", parser.parse("count twelve", 0.42f), "en-US")
        rec.recordUtterance("T-1", null, parser.parse("banana", 0.99f), "hi-IN")

        assertEquals(3, sink.size)
        assertEquals(sink, rec.getRecordedEvents())
        val (a, b, c) = sink
        assertTrue(a.isAccepted); assertEquals("COUNT", a.intent); assertEquals(0.93f, a.confidence, 0f)
        assertFalse(b.isAccepted); assertEquals("UNKNOWN", b.intent); assertEquals("count twelve", b.transcript)
        assertFalse(c.isAccepted); assertEquals("hi-IN", c.locale); assertEquals(null, c.captureId)
        assertEquals(listOf(1_000L, 1_001L, 1_002L), sink.map { it.timestampMs })
        assertEquals("ids are unique", 3, sink.map { it.id }.toSet().size)
        assertEquals("ids sort in recording order", sink.map { it.id }, sink.map { it.id }.sorted())
    }
}
