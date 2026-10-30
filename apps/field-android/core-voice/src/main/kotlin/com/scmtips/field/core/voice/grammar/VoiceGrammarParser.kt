package com.scmtips.field.core.voice.grammar

import com.scmtips.field.core.voice.numbers.NumberWordParser

enum class VoiceIntent {
    CAPTURE,
    COUNT,
    READING,
    UNDO,
    WRONG_ONE,
    MARK_DAMAGED,
    CONDITION_GOOD,
    CHOOSE_LEFT,
    CHOOSE_RIGHT,
    POST,
    CONFIRM,
    CANCEL,
    NEXT,
    REPEAT,
    WHAT_IS_THIS,
    UNKNOWN
}

data class ParsedUtterance(
    val rawTranscript: String,
    val confidence: Float,
    val intent: VoiceIntent,
    val quantityOrValue: Double? = null,
    val isAccepted: Boolean,
    val feedbackMessage: String? = null
)

/**
 * Grammar parser enforcing 0.80 confidence floor and vocabulary matching
 * (Task T2.034 / FR2.031 / FR2.032 / PR2.09 / TC2.128 / TC2.129).
 */
class VoiceGrammarParser(
    private val numberParser: NumberWordParser = NumberWordParser()
) {
    companion object {
        const val CONFIDENCE_FLOOR = 0.80f
        const val MSG2_10 = "Did not catch that. Nothing changed. Hold the button and say it again."
    }

    fun parse(transcript: String, confidence: Float): ParsedUtterance {
        val clean = transcript.trim().lowercase()

        // 1. Strict Confidence Floor check (FR2.032 / PR2.09)
        if (confidence < CONFIDENCE_FLOOR) {
            return ParsedUtterance(
                rawTranscript = transcript,
                confidence = confidence,
                intent = VoiceIntent.UNKNOWN,
                isAccepted = false,
                feedbackMessage = MSG2_10
            )
        }

        // 2. Command Grammar Matching
        return when {
            clean == "capture" -> ParsedUtterance(transcript, confidence, VoiceIntent.CAPTURE, isAccepted = true)
            clean.startsWith("count ") -> {
                val numStr = clean.removePrefix("count ").trim()
                val parsedNumber = numberParser.parse(numStr)
                if (parsedNumber != null) {
                    ParsedUtterance(transcript, confidence, VoiceIntent.COUNT, quantityOrValue = parsedNumber.toDouble(), isAccepted = true)
                } else {
                    ParsedUtterance(transcript, confidence, VoiceIntent.UNKNOWN, isAccepted = false, feedbackMessage = MSG2_10)
                }
            }
            clean.startsWith("reading ") -> {
                val valStr = clean.removePrefix("reading ").trim()
                val parsedVal = numberParser.parse(valStr)
                if (parsedVal != null) {
                    ParsedUtterance(transcript, confidence, VoiceIntent.READING, quantityOrValue = parsedVal.toDouble(), isAccepted = true)
                } else {
                    ParsedUtterance(transcript, confidence, VoiceIntent.UNKNOWN, isAccepted = false, feedbackMessage = MSG2_10)
                }
            }
            clean == "undo" -> ParsedUtterance(transcript, confidence, VoiceIntent.UNDO, isAccepted = true)
            clean == "wrong one" -> ParsedUtterance(transcript, confidence, VoiceIntent.WRONG_ONE, isAccepted = true)
            clean == "mark damaged" -> ParsedUtterance(transcript, confidence, VoiceIntent.MARK_DAMAGED, isAccepted = true)
            clean == "condition good" -> ParsedUtterance(transcript, confidence, VoiceIntent.CONDITION_GOOD, isAccepted = true)
            clean == "left" -> ParsedUtterance(transcript, confidence, VoiceIntent.CHOOSE_LEFT, isAccepted = true)
            clean == "right" -> ParsedUtterance(transcript, confidence, VoiceIntent.CHOOSE_RIGHT, isAccepted = true)
            clean == "post" -> ParsedUtterance(transcript, confidence, VoiceIntent.POST, isAccepted = true)
            clean == "confirm" -> ParsedUtterance(transcript, confidence, VoiceIntent.CONFIRM, isAccepted = true)
            clean == "cancel" -> ParsedUtterance(transcript, confidence, VoiceIntent.CANCEL, isAccepted = true)
            clean == "next" -> ParsedUtterance(transcript, confidence, VoiceIntent.NEXT, isAccepted = true)
            clean == "repeat" -> ParsedUtterance(transcript, confidence, VoiceIntent.REPEAT, isAccepted = true)
            clean == "what is this" -> ParsedUtterance(transcript, confidence, VoiceIntent.WHAT_IS_THIS, isAccepted = true)
            else -> {
                // Out of grammar -> no state change (FR2.032)
                ParsedUtterance(transcript, confidence, VoiceIntent.UNKNOWN, isAccepted = false, feedbackMessage = MSG2_10)
            }
        }
    }
}
