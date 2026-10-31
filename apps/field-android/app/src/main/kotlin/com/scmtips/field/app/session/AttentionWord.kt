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

    /** What recognisers commonly write for a spoken "Field". */
    private val HEARD_AS = setOf("field", "feild", "fields", "field's")

    /** The words to act on, or null when they are to be ignored. */
    fun filter(text: String, on: Boolean): String? {
        val t = text.trim()
        if (!on) return t.ifEmpty { null }
        val first = t.substringBefore(' ')
        val word = first.trimEnd(',', '.', '!', '?', ':', ';').lowercase()
        if (word !in HEARD_AS) return null
        val rest = t.substring(first.length).trimStart(' ', ',', '.', ':', ';', '!', '?', '-').trim()
        return rest.ifEmpty { null }
    }
}
