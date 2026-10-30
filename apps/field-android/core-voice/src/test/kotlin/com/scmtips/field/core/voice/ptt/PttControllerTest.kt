package com.scmtips.field.core.voice.ptt

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** PttController and SecureAudioRamBuffer against FR2.011 (record only while held) and FR2.035 (RAM only, zeroed). */
class PttControllerTest {

    @Test
    fun fr2_011_audioIsRecordedOnlyWhileHeldForEveryTrigger() {
        for (source in PttTriggerSource.values()) {
            var heard: ByteArray? = null
            val ptt = PttController(onPttStopped = { heard = it.copyOf() })
            ptt.appendAudioChunk(byteArrayOf(9, 9))
            ptt.startPtt(source)
            assertTrue(ptt.isListening())
            ptt.appendAudioChunk(byteArrayOf(1, 2, 3))
            ptt.stopPtt()
            ptt.appendAudioChunk(byteArrayOf(7, 7))
            assertArrayEquals(source.name, byteArrayOf(1, 2, 3), heard)
            assertEquals(PttState.IDLE, ptt.state.value)
        }
    }

    @Test
    fun fr2_035_bufferAndSnapshotAreZeroedAfterRecognition() {
        var snapshotRef: ByteArray? = null
        var bufferZeroedDuringRecognition = false
        lateinit var ptt: PttController
        ptt = PttController(onPttStopped = { pcm ->
            snapshotRef = pcm
            assertTrue("recogniser receives the audio", pcm.any { it != 0.toByte() })
            bufferZeroedDuringRecognition = ptt.audioBuffer.isZeroed()
        })
        ptt.startPtt(PttTriggerSource.ON_SCREEN_TOUCH)
        ptt.appendAudioChunk(ByteArray(3_200) { (it % 251 + 1).toByte() })
        assertFalse(ptt.audioBuffer.isZeroed())
        ptt.stopPtt()
        assertTrue("ring buffer wiped before recognition", bufferZeroedDuringRecognition)
        assertTrue(ptt.audioBuffer.isZeroed())
        assertTrue("snapshot wiped after recognition", snapshotRef!!.all { it == 0.toByte() })
    }

    @Test
    fun fr2_035_snapshotIsZeroedEvenWhenRecognitionThrows() {
        var ref: ByteArray? = null
        val ptt = PttController(onPttStopped = { ref = it; error("recogniser crashed") })
        ptt.startPtt(PttTriggerSource.BLUETOOTH_MEDIA_BUTTON)
        ptt.appendAudioChunk(byteArrayOf(5, 6, 7))
        runCatching { ptt.stopPtt() }
        assertTrue(ref!!.all { it == 0.toByte() })
        assertEquals(PttState.IDLE, ptt.state.value)
    }

    @Test
    fun bufferCapsAtTenSecondsOf16kHzMono() {
        val buf = SecureAudioRamBuffer()
        assertEquals(320_000, buf.capacityBytes)
        buf.write(ByteArray(400_000) { 1 })
        assertEquals(320_000, buf.bytesWritten())
        buf.zeroAndReset()
        assertTrue(buf.isZeroed())
    }

    @Test
    fun secondStartWhileListeningIsIgnored() {
        val starts = mutableListOf<PttTriggerSource>()
        val ptt = PttController(onPttStarted = { starts += it })
        ptt.startPtt(PttTriggerSource.VOLUME_DOWN_LONG_PRESS)
        ptt.startPtt(PttTriggerSource.ON_SCREEN_TOUCH)
        assertEquals(listOf(PttTriggerSource.VOLUME_DOWN_LONG_PRESS), starts)
    }
}
