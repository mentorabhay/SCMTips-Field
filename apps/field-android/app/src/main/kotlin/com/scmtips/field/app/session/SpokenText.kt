package com.scmtips.field.app.session

/**
 * What the app does with a recogniser's result before any grammar sees it (owner's live test, 4 Nov 2026).
 *
 * - Confidence: Android's recogniser on the owner's phone (offline, EXTRA_PREFER_OFFLINE) gave every result a score of
 *   0.00, so "look", "take a look" and "I agree", heard correctly, all fell under the 0.80 floor and were dropped as
 *   "Did not catch that". A score of 0 or less means "the engine gives none" and counts as exactly the floor, the
 *   rule glasses speech already had (DatGlasses: the toolkit's -1). A real low score (0.01 to 0.79) still fails.
 * - Repeats: "Look look", "Look look look again": a word said again straight after itself is kept once.
 */
object SpokenText {
    /** The floor every grammar uses (VoiceGrammarParser.CONFIDENCE_FLOOR): a result without a score counts as this. */
    const val UNKNOWN_CONFIDENCE = 0.80f

    /** The best result's confidence from RecognizerIntent's CONFIDENCE_SCORES; none, 0 or less = UNKNOWN_CONFIDENCE. */
    fun confidence(scores: FloatArray?): Float = scores?.firstOrNull()?.takeIf { it > 0f } ?: UNKNOWN_CONFIDENCE

    /** The words with a word repeated right after itself kept once (case and trailing punctuation ignored). */
    fun tidy(text: String): String {
        val out = mutableListOf<String>()
        for (w in text.trim().split(Regex("\\s+"))) {
            if (w.isEmpty()) continue
            val prev = out.lastOrNull()
            if (prev != null && key(prev) == key(w) && key(w).isNotEmpty()) continue
            out += w
        }
        return out.joinToString(" ")
    }

    private fun key(w: String) = w.trim(',', '.', '!', '?', ':', ';').lowercase()
}
