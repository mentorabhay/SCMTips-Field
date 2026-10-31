package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.feature.decisions.api.NextItem

/** Builds the decision cards (ported from the core's wearable app). Pure Kotlin. */
object CardFormatter {
    const val MAX_CARD_CHARS = 240
    const val MAX_TITLE_CHARS = 80
    private const val ELLIPSIS = "…"

    /** Truncates to at most [max] characters (ellipsis included), preferring a word boundary. */
    fun truncate(text: String, max: Int = MAX_CARD_CHARS): String {
        val clean = text.replace(Regex("\\s+"), " ").trim()
        if (clean.length <= max) return clean
        val room = max - ELLIPSIS.length
        val cut = clean.substring(0, room)
        val space = cut.lastIndexOf(' ')
        val base = if (space >= room / 2) cut.substring(0, space) else cut
        return base.trimEnd(' ', ',', ';', ':', '.', '-') + ELLIPSIS
    }

    /** Decision card: body ≤ 240 chars, one "Approve X" button per option plus "Reject". */
    fun decisionCard(item: NextItem): DecisionCard = DecisionCard(
        title = truncate(item.title, MAX_TITLE_CHARS),
        body = truncate(item.card, MAX_CARD_CHARS),
        buttons = item.options.mapIndexed { i, o ->
            CardButton(id = CardAction.Approve(o.letter).id, label = "Approve ${o.letter}", primary = i == 0)
        } + CardButton(id = CardAction.Reject.id, label = "Reject"),
    )

    /** After a readback: "Confirm" / "Cancel". [say] is the core's readback text. */
    fun confirmCard(title: String, say: String): DecisionCard = DecisionCard(
        title = truncate(title, MAX_TITLE_CHARS),
        body = truncate(say, MAX_CARD_CHARS),
        buttons = listOf(
            CardButton(id = CardAction.Confirm.id, label = "Confirm", primary = true),
            CardButton(id = CardAction.Cancel.id, label = "Cancel"),
        ),
    )
}

/**
 * Buttons are only a shortcut for phrases the core's grammar already understands; the core decides
 * every intent. The app never approves anything on its own.
 */
sealed class CardAction(val id: String) {
    data class Approve(val letter: String) : CardAction("approve:$letter")
    data object Reject : CardAction("reject")
    data object Confirm : CardAction("confirm")
    data object Cancel : CardAction("cancel")

    companion object {
        fun parse(id: String): CardAction? = when {
            id.startsWith("approve:") -> Approve(id.removePrefix("approve:"))
            id == Reject.id -> Reject
            id == Confirm.id -> Confirm
            id == Cancel.id -> Cancel
            else -> null
        }

        /** Transcript sent to POST /v1/voice/commands for a button. Reject needs a spoken reason first. */
        fun transcript(action: CardAction, reason: String? = null): String = when (action) {
            is Approve -> "approve option ${action.letter}"
            Reject -> if (reason.isNullOrBlank()) "reject" else "reject because $reason"
            Confirm -> "confirm"
            Cancel -> "cancel"
        }
    }
}
