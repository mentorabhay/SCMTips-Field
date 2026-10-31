package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.feature.decisions.DecisionFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ported from the core's wearable app (flow/CardFormatterTest). */
class CardFormatterTest {
    @Test
    fun shortText_isUnchanged() {
        assertEquals("Supplier A is late.", CardFormatter.truncate("Supplier A   is late. "))
    }

    @Test
    fun longText_isAtMost240_andEndsWithEllipsis_onAWordBoundary() {
        val long = (1..80).joinToString(" ") { "word$it" }
        val out = CardFormatter.truncate(long)
        assertTrue(out.length <= 240)
        assertTrue(out.endsWith("…"))
        assertTrue(long.startsWith(out.removeSuffix("…")))
        assertTrue(out.removeSuffix("…").split(" ").all { it.startsWith("word") && long.split(" ").contains(it) })
    }

    @Test
    fun unbrokenText_isCutHard_at240() {
        assertEquals(240, CardFormatter.truncate("x".repeat(1000)).length)
    }

    @Test
    fun exactly240_isKept() {
        val s = "y".repeat(240)
        assertEquals(s, CardFormatter.truncate(s))
    }

    @Test
    fun decisionCard_truncatesBody_andHasOneApprovePerOptionPlusReject() {
        val card = CardFormatter.decisionCard(DecisionFixtures.item(card = "Supplier A delay. ".repeat(40)))
        assertTrue(card.body.length <= CardFormatter.MAX_CARD_CHARS)
        assertEquals(listOf("approve:A", "approve:B", "reject"), card.buttons.map { it.id })
        assertEquals(listOf(true, false, false), card.buttons.map { it.primary })
    }

    @Test
    fun confirmCard_hasConfirmThenCancel() {
        val card = CardFormatter.confirmCard("t".repeat(200), "Say confirm.")
        assertEquals(CardFormatter.MAX_TITLE_CHARS, card.title.length)
        assertEquals(listOf("confirm", "cancel"), card.buttons.map { it.id })
    }

    @Test
    fun buttonTranscripts_matchTheCoresGrammarPhrases() {
        assertEquals("approve option A", CardAction.transcript(CardAction.parse("approve:A")!!))
        assertEquals("reject because late", CardAction.transcript(CardAction.Reject, "late"))
        assertEquals("reject", CardAction.transcript(CardAction.Reject))
        assertEquals("confirm", CardAction.transcript(CardAction.parse("confirm")!!))
        assertEquals("cancel", CardAction.transcript(CardAction.parse("cancel")!!))
        assertEquals(null, CardAction.parse("something"))
    }
}
