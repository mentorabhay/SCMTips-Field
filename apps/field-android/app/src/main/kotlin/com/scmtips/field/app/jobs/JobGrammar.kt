package com.scmtips.field.app.jobs

import com.scmtips.field.core.voice.grammar.VoiceGrammarParser
import com.scmtips.field.core.voice.numbers.NumberWordParser

/** What the operator can say during any job (design: Glasses.dc.html, "What you can say, any time"). */
sealed interface Command {
    data object Capture : Command
    data object AllHere : Command
    data class Number(val value: Int) : Command
    data object Next : Command
    data object Repeat : Command
    data object WhatIsThis : Command
    data object Post : Command
    data object Yes : Command
    data object Cancel : Command
    data object Clipped : Command
}

/**
 * The small M2 job grammar. Speech below the 0.80 confidence floor, or outside the grammar, gives null:
 * the caller changes nothing and says MSG2.10 (FR2.032). "count twelve" and "confirm" from the M1 slice
 * stay accepted.
 */
object JobGrammar {
    const val FLOOR = VoiceGrammarParser.CONFIDENCE_FLOOR
    const val NOT_UNDERSTOOD = VoiceGrammarParser.MSG2_10
    private val numbers = NumberWordParser()
    private val PUNCTUATION = Regex("[.,!?;:\"“”‘’']")

    fun parse(transcript: String, confidence: Float): Command? {
        if (confidence < FLOOR) return null
        val t = normalise(transcript)
        if (t.isEmpty()) return null
        return when (t) {
            "capture" -> Command.Capture
            "all here", "all are here", "all of them are here" -> Command.AllHere
            "next" -> Command.Next
            "repeat", "say again" -> Command.Repeat
            "what is this" -> Command.WhatIsThis
            "post" -> Command.Post
            "yes", "confirm" -> Command.Yes
            "cancel", "no" -> Command.Cancel
            "clipped", "clipped in", "harness clipped" -> Command.Clipped
            else -> number(t.removePrefix("count ").trim())?.let { Command.Number(it) }
        }
    }

    private fun number(t: String): Int? = numbers.parse(t)?.takeIf { it in 0..9999 }

    internal fun normalise(s: String): String =
        s.lowercase().replace(PUNCTUATION, "").replace('-', ' ').trim().split(Regex("\\s+")).joinToString(" ")
}
