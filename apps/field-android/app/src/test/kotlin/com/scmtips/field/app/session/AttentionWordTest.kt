package com.scmtips.field.app.session

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** M3 fix (owner test, 31 Oct): the optional attention word "Field". */
class AttentionWordTest {
    @Test
    fun offByDefault_everyUtteranceIsActedOnAsHeard() {
        assertEquals("next", AttentionWord.filter(" next ", on = false))
        assertEquals("field next", AttentionWord.filter("field next", on = false))
        assertNull(AttentionWord.filter("  ", on = false))
    }

    @Test
    fun whenOn_onlyWordsStartingWithFieldAreActedOn_withoutTheWord() {
        assertEquals("next", AttentionWord.filter("Field, next", on = true))
        assertEquals("approve option two", AttentionWord.filter("field approve option two", on = true))
        assertEquals("start receive", AttentionWord.filter("FIELD: start receive", on = true))
        assertEquals("decisions", AttentionWord.filter("Feild decisions", on = true))
        assertNull(AttentionWord.filter("next", on = true))
        assertNull(AttentionWord.filter("the field is wet", on = true))
        assertNull(AttentionWord.filter("Field", on = true))
        assertNull(AttentionWord.filter("Field.", on = true))
    }
}
