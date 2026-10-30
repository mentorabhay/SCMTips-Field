package com.scmtips.field.core.capture.motion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

/** Look segmentation (T2.021, D2.07): start after 150 ms at <= 8 deg/s, end above 25 deg/s or on record. */
class LookSegmenterTest {

    @Test
    fun fr2_029_lookStartsAfter150msStill() {
        val s = LookSegmenter()
        assertEquals(LookState.Searching, s.processMotionSample(3f, 0))
        assertEquals(LookState.Searching, s.processMotionSample(5f, 100))
        val active = s.processMotionSample(8f, 150)
        assertTrue(active is LookState.LookActive)
        assertTrue(s.isLookActive())
    }

    @Test
    fun fr2_029_moderateMotionBeforeStartResetsTheClock() {
        val s = LookSegmenter()
        s.processMotionSample(2f, 0)
        s.processMotionSample(12f, 100) // between 8 and 25: not still
        assertEquals(LookState.Searching, s.processMotionSample(2f, 150))
        assertEquals(LookState.Searching, s.processMotionSample(2f, 299))
        assertTrue(s.processMotionSample(2f, 300) is LookState.LookActive)
    }

    @Test
    fun fr2_029_lookEndsAbove25DegPerSecButNotAt25() {
        val s = LookSegmenter()
        s.processMotionSample(1f, 0)
        val id = (s.processMotionSample(1f, 200) as LookState.LookActive).lookId
        assertTrue(s.processMotionSample(25f, 250) is LookState.LookActive)
        val ended = s.processMotionSample(25.1f, 300)
        assertEquals(LookState.LookEnded(id, "MOTION_BREAK_EXCEEDED_25_DEG_S"), ended)
        assertFalse(s.isLookActive())
    }

    @Test
    fun fr2_029_recordCommitEndsLookAndNextLookGetsNewUuid7() {
        val s = LookSegmenter()
        s.processMotionSample(1f, 0)
        val first = (s.processMotionSample(1f, 150) as LookState.LookActive).lookId
        assertEquals(7, UUID.fromString(first).version())
        assertEquals(LookState.LookEnded(first, "RECORD_COMMITTED"), s.completeRecordCommitted())
        s.processMotionSample(1f, 400)
        val second = (s.processMotionSample(1f, 550) as LookState.LookActive).lookId
        assertNotEquals(first, second)
    }
}
