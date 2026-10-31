package com.scmtips.field.app.scan

/**
 * Scan by looking (M3 contract §5): barcodes decoded from the glasses' low-rate video become a scan only
 * when the same code is in two consecutive decoded frames, and the same code is not reported again
 * within [repeatMs] of its last report. A frame that could not be decoded counts as a frame with no
 * codes, so "consecutive" really means back to back.
 */
class FrameScanFilter(private val repeatMs: Long = 3_000) {
    private var previous: Set<String> = emptySet()
    private val lastReport = mutableMapOf<String, Long>()

    /** The codes of one frame (in ML Kit order); returns the codes that count as scans now. */
    fun onFrame(codes: List<String>, atMs: Long): List<String> {
        val cleaned = codes.map { it.trim() }.filter { it.isNotEmpty() }.distinctBy(::key)
        val stable = cleaned.filter { key(it) in previous }
        previous = cleaned.map(::key).toSet()
        lastReport.entries.removeAll { atMs - it.value >= repeatMs } // older reports may be repeated
        val out = stable.filter { key(it) !in lastReport }
        out.forEach { lastReport[key(it)] = atMs }
        return out
    }

    /** A new session, a pause or a scan from elsewhere: the next scan needs two fresh frames again. */
    fun reset() {
        previous = emptySet()
        lastReport.clear()
    }

    private fun key(c: String): String = c.trim().uppercase()
}

/** Pixel conversion for ML Kit, which takes NV21 (or YV12) byte arrays but not the decoder's I420. */
object Yuv {
    /**
     * I420 (Y plane, then U, then V, no padding) to NV21 (Y plane, then interleaved V/U). Null when the
     * buffer is not exactly width x height x 1.5 bytes (padded or compressed frames are skipped).
     */
    fun i420ToNv21(src: ByteArray, width: Int, height: Int): ByteArray? {
        if (width <= 0 || height <= 0 || width % 2 != 0 || height % 2 != 0) return null
        val y = width * height
        val q = y / 4
        if (src.size != y + 2 * q) return null
        val out = ByteArray(src.size)
        System.arraycopy(src, 0, out, 0, y)
        var o = y
        for (i in 0 until q) {
            out[o++] = src[y + q + i] // V
            out[o++] = src[y + i] // U
        }
        return out
    }
}
