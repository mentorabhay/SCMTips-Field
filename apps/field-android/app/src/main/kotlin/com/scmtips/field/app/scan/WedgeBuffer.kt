package com.scmtips.field.app.scan

/**
 * Handheld "keyboard wedge" scanners type the barcode as key presses and end it with Enter (or Tab).
 * MainActivity feeds key events here while the handheld scanner is chosen; no extra dependency.
 *
 * Keys more than [gapMs] apart start a new code, so a stray key press never glues onto the next scan.
 */
class WedgeBuffer(private val clock: () -> Long = System::currentTimeMillis, private val gapMs: Long = 1_000L) {
    private val sb = StringBuilder()
    private var lastAt = 0L

    fun type(c: Char) {
        val now = clock()
        if (sb.isNotEmpty() && now - lastAt > gapMs) sb.clear()
        lastAt = now
        if (!c.isISOControl()) sb.append(c)
    }

    /** End of a scan: the code, or null if nothing was typed. */
    fun enter(): String? {
        val code = sb.toString().trim()
        sb.clear()
        return code.ifEmpty { null }
    }
}
