package com.scmtips.field.core.common

import java.security.SecureRandom
import java.util.UUID

/**
 * RFC 9562 UUIDv7 generator (FR2.039).
 *
 * Layout: 48-bit Unix ms timestamp | ver=7 | 12-bit rand_a | var=0b10 | 62-bit rand_b.
 * Monotonic within one process (RFC 9562 §6.2 method 1): rand_a is a counter seeded randomly
 * each new millisecond and incremented for every further id in the same millisecond; on counter
 * overflow the timestamp is advanced by 1 ms. Ids from one generator therefore sort strictly
 * increasing as strings and as UUIDs.
 */
object UUIDv7 {
    private val default = UUIDv7Generator()

    fun generate(): String = default.next(System.currentTimeMillis()).toString()

    /** Next id from the process-wide generator for a given clock reading. */
    fun next(nowMs: Long): UUID = default.next(nowMs)
}

/** One monotonic UUIDv7 sequence; [UUIDv7] holds the process-wide instance. */
class UUIDv7Generator(private val random: SecureRandom = SecureRandom()) {
    private var lastMs: Long = -1L
    private var counter: Int = 0

    @Synchronized
    fun next(nowMs: Long): UUID {
        var ms = maxOf(nowMs, lastMs)
        if (ms == lastMs) {
            counter += 1
            if (counter > 0xFFF) {
                ms += 1
                counter = random.nextInt(0x800)
            }
        } else {
            // Seed below half the range so a burst in one millisecond has room to count up.
            counter = random.nextInt(0x800)
        }
        lastMs = ms
        val msb = ((ms and 0xFFFFFFFFFFFFL) shl 16) or 0x7000L or counter.toLong()
        val lsb = (random.nextLong() and 0x3FFFFFFFFFFFFFFFL) or Long.MIN_VALUE
        return UUID(msb, lsb)
    }
}
