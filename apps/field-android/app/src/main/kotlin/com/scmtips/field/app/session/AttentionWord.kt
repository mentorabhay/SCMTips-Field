package com.scmtips.field.app.session

/**
 * The optional attention word "Field" (Me → Attention word, off by default; M4 contract §4 B). When on,
 * only what the session microphone hears starting with "Field" is acted on, with the word taken off:
 * "Field, next" → "next"; "next" alone is ignored. Words the operator says while holding the phone's talk
 * button are meant for the app anyway and are not filtered.
 *
 * "Hey Meta" cannot be used or intercepted: the glasses hand it to Meta AI before any app hears it.
 */
object AttentionWord {
    const val WORD = "field"

    /** What recognisers commonly write for a spoken "Field" ("Feel": the owner's phone, 4 Nov 2026). */
    private val HEARD_AS = setOf("field", "feild", "fields", "field's", "feel", "feels", "feeld")

    /**
     * The words to act on, or null when they are to be ignored. With the word off, a leading "Field" is still taken
     * off ("Field, look" acts like "look", owner's test 4 Nov), unless nothing would be left.
     */
    fun filter(text: String, on: Boolean): String? {
        val t = text.trim()
        val first = t.substringBefore(' ')
        val word = first.trimEnd(',', '.', '!', '?', ':', ';').lowercase()
        val rest = if (word in HEARD_AS) t.substring(first.length).trimStart(' ', ',', '.', ':', ';', '!', '?', '-').trim() else null
        if (!on) return (rest?.ifEmpty { null } ?: t).ifEmpty { null }
        return rest?.ifEmpty { null }
    }

    /** Hold-to-talk words: meant for the app anyway, so a leading "Field" is just taken off (never ignored). */
    fun strip(text: String): String = filter(text, on = false) ?: text.trim()
}
