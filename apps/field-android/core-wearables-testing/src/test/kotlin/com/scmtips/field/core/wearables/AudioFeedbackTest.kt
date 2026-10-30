package com.scmtips.field.core.wearables

import com.scmtips.field.core.wearables.audio.AudioCueManager
import com.scmtips.field.core.wearables.audio.GlassesReadbackManager
import com.scmtips.field.core.wearables.mock.MockWearablesKit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Audio-only cue set (FR2.014, SCR2.08), feedback routing and TTS readback flush (FR2.012). */
class AudioFeedbackTest {

    @Test
    fun tc2_115_gen2ProfileEarconsAndPhrasesPerScr2_08() = runBlocking {
        val kit = MockWearablesKit()
        kit.connect("AA:BB", "Ray-Ban Meta Gen 2")
        val cues = AudioCueManager(kit.audioOut)
        val feedback = LookFeedback(kit, cues)
        assertFalse("Gen 2 has no display", feedback.usesLens())

        val phrases = mutableMapOf<LensState, List<String>>()
        val earcons = mutableMapOf<LensState, List<EarconCue>>()
        for (state in LensState.values()) {
            kit.speechLog.clear(); kit.playedEarcons.clear()
            feedback.show(state)
            phrases[state] = kit.speechLog.toList()
            earcons[state] = kit.playedEarcons.toList()
        }
        assertEquals(emptyList<String>(), phrases[LensState.READY])
        assertEquals(emptyList<EarconCue>(), earcons[LensState.READY])
        assertEquals(emptyList<String>(), phrases[LensState.MOVING])
        assertEquals(emptyList<EarconCue>(), earcons[LensState.MOVING])
        assertEquals(listOf("Two items. Left or right?"), phrases[LensState.TIE])
        assertEquals(emptyList<String>(), phrases[LensState.CAPTURED])
        assertEquals(listOf(EarconCue.CAPTURED), earcons[LensState.CAPTURED])
        assertEquals(listOf("Already captured"), phrases[LensState.DUPLICATE])
        assertEquals(listOf("Saved offline"), phrases[LensState.OFFLINE_QUEUED])
        assertEquals(listOf("Problem. Check phone."), phrases[LensState.ERROR])
        assertTrue("nothing reached the lens", kit.fakeRenderer.getDrawCalls().isEmpty())
    }

    @Test
    fun walkingQuietSuppressesPhrasesExceptErrors() = runBlocking {
        val kit = MockWearablesKit()
        val cues = AudioCueManager(kit.audioOut, isWalkingQuietActive = { true })
        for (s in LensState.values()) cues.emitStateCue(s)
        assertEquals(listOf("Problem. Check phone."), kit.speechLog)
        assertEquals("earcons still play", 5, kit.playedEarcons.size)
    }

    @Test
    fun fr2_014_displayGlassesUseLensUnlessForceAudioOnly() = runBlocking {
        val kit = MockWearablesKit()
        kit.connect("AA:BB", "Meta Ray-Ban Display")
        var force = false
        val feedback = LookFeedback(kit, AudioCueManager(kit.audioOut), forceAudioOnly = { force })
        feedback.show(LensState.DUPLICATE)
        assertEquals("Already captured", kit.fakeRenderer.getLastDrawCall()!!.line1)
        assertTrue(kit.speechLog.isEmpty())
        force = true
        feedback.show(LensState.DUPLICATE)
        assertEquals(1, kit.fakeRenderer.getDrawCalls().size)
        assertEquals(listOf("Already captured"), kit.speechLog)
    }

    @Test
    fun fr2_012_readbackSpeaksStagedCountAndPushToTalkFlushesIt() = runBlocking {
        val kit = MockWearablesKit()
        val readback = GlassesReadbackManager(kit.audioOut)
        readback.readbackCount(12)
        assertEquals(listOf("Count 12. Say confirm."), kit.playedSpeeches)
        assertEquals("Count 12. Say confirm.", readback.lastReadback.value)
        readback.onPushToTalkStarted()
        assertEquals(1, kit.stopAudioCalls)
        assertTrue(kit.playedSpeeches.isEmpty())
        assertFalse(readback.isSpeaking.value)
    }
}
