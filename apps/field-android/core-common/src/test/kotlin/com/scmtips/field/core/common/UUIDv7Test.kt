package com.scmtips.field.core.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

/** UUIDv7 against RFC 9562 layout and the monotonic ordering FR2.039 relies on. */
class UUIDv7Test {

    @Test
    fun fr2_039_versionVariantAndTimestampFollowRfc9562() {
        val now = 1_793_000_000_123L
        val u = UUIDv7Generator().next(now)
        assertEquals(7, u.version())
        assertEquals(2, u.variant())
        assertEquals(now, u.mostSignificantBits ushr 16)
        val s = UUIDv7.generate()
        assertEquals(s, UUID.fromString(s).toString())
        assertEquals('7', s[14])
    }

    @Test
    fun fr2_039_idsAreStrictlyIncreasingWithinOneMillisecondAndAcrossClockSteps() {
        val clock = listOf(5_000L) * 5_000 + listOf(5_001L, 4_999L, 4_999L, 5_002L) // includes a backwards step
        val gen = UUIDv7Generator()
        val ids = clock.map { gen.next(it) }
        for (i in 1 until ids.size) {
            assertTrue("id $i", ids[i] > ids[i - 1])
            assertTrue("string order $i", ids[i].toString() > ids[i - 1].toString())
        }
        assertEquals(ids.size, ids.toSet().size)
    }

    private operator fun List<Long>.times(n: Int): List<Long> = (1..n).flatMap { this }
}
