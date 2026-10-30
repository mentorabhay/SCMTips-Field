package com.scmtips.field.app.slice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** The QR contract with tools/dev_stack/stack.py `pairing_payload` (test_stack.py pins the producer). */
class PairingPayloadTest {
    private val good =
        """{"v":1,"api":"http://192.168.1.23:8000/","token":"tok","tenant":"t-1","site":"s-1","site_name":"SAMPLE warehouse"}"""

    @Test
    fun parsesTheExactProducerFormat() {
        assertEquals(Pairing("http://192.168.1.23:8000", "tok", "t-1", "s-1", "SAMPLE warehouse"), PairingPayload.parse(good))
    }

    @Test
    fun httpsTunnelsAreAccepted() {
        val p = PairingPayload.parse(good.replace("http://192.168.1.23:8000/", "https://abc.trycloudflare.com"))
        assertEquals("https://abc.trycloudflare.com", p.apiBaseUrl)
    }

    @Test
    fun plainHttpToAPublicHostIsRefused() {
        assertRefused(good.replace("192.168.1.23", "203.0.113.9"), "Plain http")
    }

    @Test
    fun wrongVersionMissingFieldsAndJunkAreRefused() {
        assertRefused(good.replace("\"v\":1", "\"v\":2"), "version 2")
        assertRefused(good.replace(",\"token\":\"tok\"", ""), "'token'")
        assertRefused("https://example.com", "not a SCMTips pairing code")
        assertRefused("[1,2]", "not a SCMTips pairing code")
    }

    @Test
    fun privateHostRules() {
        for (h in listOf("10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.0.10", "127.0.0.1", "localhost", "169.254.1.1")) {
            assertTrue(h, PairingPayload.isPrivateHost(h))
        }
        for (h in listOf("172.32.0.1", "8.8.8.8", "192.169.0.1", "example.com", "10.0.0", "300.1.1.1")) {
            assertFalse(h, PairingPayload.isPrivateHost(h))
        }
    }

    private fun assertRefused(text: String, expect: String) {
        try {
            PairingPayload.parse(text)
            fail("accepted: $text")
        } catch (e: IllegalArgumentException) {
            assertTrue("${e.message}", e.message!!.contains(expect))
        }
    }
}
