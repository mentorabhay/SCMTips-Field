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

    /** M5: "look", "take a look", "look again", "count again": a look with the camera (the app takes it). */
    data object Look : Command

    /** M5: "make a claim": a supplier claim from the last look (the app makes it). */
    data object Claim : Command

    /**
     * M5: "receive 18, flag 2" / "receive eighteen flag two" / "receive 18" / "flag 2". [good] goes to
     * unrestricted stock, [flag] to quality inspection; either may be missing when only the other was said.
     */
    data class Receive(val good: Int?, val flag: Int?) : Command
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
            in LOOK -> Command.Look
            in CLAIM -> Command.Claim
            else -> receive(t) ?: number(t.removePrefix("count ").trim())?.let { Command.Number(it) }
        }
    }

    private val LOOK = setOf(
        "look", "take a look", "have a look", "look now", "look again", "take another look", "count again", "count them",
    )
    private val CLAIM = setOf("make a claim", "claim", "make claim", "raise a claim", "file a claim")
    private val RECEIVE = Regex("^(?:receive|received|receiving) (.+?)(?: good)?(?: (?:and )?flag(?:ged)? (.+?)(?: damaged| bad)?)?$")
    private val FLAG_ONLY = Regex("^flag(?:ged)? (.+?)(?: damaged| bad)?$")

    /** "receive N [good] [and] flag M", "receive N", "flag M"; null when a number does not parse. */
    private fun receive(t: String): Command.Receive? {
        RECEIVE.matchEntire(t)?.let { m ->
            val good = number(m.groupValues[1]) ?: return null
            val flagWords = m.groupValues[2]
            val flag = if (flagWords.isEmpty()) null else number(flagWords) ?: return null
            return Command.Receive(good, flag)
        }
        FLAG_ONLY.matchEntire(t)?.let { m -> return number(m.groupValues[1])?.let { Command.Receive(null, it) } }
        return null
    }

    private fun number(t: String): Int? = numbers.parse(t)?.takeIf { it in 0..9999 }

    internal fun normalise(s: String): String =
        s.lowercase().replace(PUNCTUATION, "").replace('-', ' ').trim().split(Regex("\\s+")).joinToString(" ")
}
