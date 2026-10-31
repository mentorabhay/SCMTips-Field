package com.scmtips.field.app.net

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Owner report 2026-10-31: crash right after pairing, then "Device already bound" on every new scan.
 * [FakeFieldApi] answers like field-api: an Idempotency-Key it has seen replays its first answer; the same
 * serial under a new key is 409 FIELD-DEV-409-EXISTS (spec TC1.168); an unknown or revoked device id
 * cannot be exchanged (403 DEVICE-REVOKED).
 */
class PhoneBindingTest {
    private class MapStore : PhoneBinding.Store {
        val m = mutableMapOf<String, String>()
        override fun get(key: String) = m[key]
        override fun put(key: String, value: String) { m[key] = value }
        override fun remove(key: String) { m.remove(key) }
    }

    private class FakeFieldApi : PhoneBinding.Api {
        val devices = mutableMapOf<String, String>() // serial -> id
        val revoked = mutableSetOf<String>()
        val replay = mutableMapOf<String, String>() // idempotency key -> id
        var registrations = 0
        var boundTo: String? = null

        override suspend fun exchange(deviceId: String?) {
            if (deviceId != null && (deviceId !in devices.values || deviceId in revoked)) {
                throw HttpError(403, PhoneBinding.DEVICE_REVOKED, "Device revoked", null, "HTTP 403")
            }
            boundTo = deviceId
        }

        override suspend fun register(serial: String, idempotencyKey: String): String {
            replay[idempotencyKey]?.let { return it }
            if (serial in devices) throw HttpError(409, PhoneBinding.DEVICE_EXISTS, "Device already bound", null, "HTTP 409")
            registrations++
            val id = "dev-${devices.size + 1}"
            devices[serial] = id
            replay[idempotencyKey] = id
            return id
        }

        fun forgetReplays() = replay.clear()
    }

    private var n = 0
    private fun binding(store: MapStore) = PhoneBinding(store) { "id-${++n}" }
    private val pc = PhoneBinding.scope("http://192.168.29.204:8003/", "tenant-1")

    @Test
    fun firstPairingRegistersOnceAndBindsTheSession() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        val id = binding(store).connect(pc, fromScan = true, api)
        assertEquals("dev-1", id)
        assertEquals("dev-1", api.boundTo)
        assertEquals(1, api.registrations)
    }

    @Test
    fun crashBeforeTheIdIsSavedThenScanAgainReplaysTheSameDevice() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        binding(store).connect(pc, fromScan = true, api)
        store.remove(PhoneBinding.KEY_DEVICE) // the app died before it could keep the id
        val again = binding(store).connect(pc, fromScan = true, api)
        assertEquals("dev-1", again)
        assertEquals(1, api.registrations)
    }

    @Test
    fun scanningTheSameCodeAgainKeepsTheDeviceWithoutRegistering() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        val b = binding(store)
        val first = b.connect(pc, fromScan = true, api)
        assertEquals(first, b.connect(pc, fromScan = true, api))
        assertEquals(first, b.savedDevice(pc))
        assertEquals(1, api.registrations)
    }

    @Test
    fun alreadyBoundWithNoReplayLeftRegistersOnceAsANewInstall() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        binding(store).connect(pc, fromScan = true, api)
        val oldSerial = store.get(PhoneBinding.KEY_SERIAL)
        store.remove(PhoneBinding.KEY_DEVICE); store.remove(PhoneBinding.KEY_REG_KEY) // e.g. an app from before the fix
        api.forgetReplays()
        val id = binding(store).connect(pc, fromScan = true, api)
        assertEquals("dev-2", id)
        assertNotEquals(oldSerial, store.get(PhoneBinding.KEY_SERIAL))
        assertEquals(id, store.get(PhoneBinding.KEY_DEVICE))
    }

    @Test
    fun anotherPcStartsFreshAndComingBackDoesNotReuseItsId() = runBlocking {
        val store = MapStore(); val home = FakeFieldApi(); val office = FakeFieldApi()
        val b = binding(store)
        b.connect(pc, fromScan = true, home)
        val other = PhoneBinding.scope("http://10.0.0.5:8000", "tenant-1")
        assertEquals(null, b.savedDevice(other))
        assertEquals("dev-1", b.connect(other, fromScan = true, office))
        assertEquals(1, office.registrations)
    }

    @Test
    fun revokedPhoneStaysOutOnRestartButAFreshScanRegistersIt() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        val b = binding(store)
        val id = b.connect(pc, fromScan = true, api)
        api.revoked += id
        try {
            b.connect(pc, fromScan = false, api)
            fail("a revoked phone must not reconnect by itself")
        } catch (e: HttpError) {
            assertEquals(PhoneBinding.DEVICE_REVOKED, e.code)
        }
        val fresh = b.connect(pc, fromScan = true, api)
        assertNotEquals(id, fresh)
        assertTrue(fresh !in api.revoked)
    }

    @Test
    fun otherErrorsAreNotSwallowed() = runBlocking {
        val store = MapStore()
        val api = object : PhoneBinding.Api {
            override suspend fun exchange(deviceId: String?) = Unit
            override suspend fun register(serial: String, idempotencyKey: String): String =
                throw HttpError(403, "FIELD-AUTH-403-PERMISSION", "Forbidden", null, "HTTP 403")
        }
        try {
            binding(store).connect(pc, fromScan = true, api)
            fail("403 must reach the screen")
        } catch (e: HttpError) {
            assertEquals("FIELD-AUTH-403-PERMISSION", e.code)
        }
    }

    @Test
    fun appsFromBeforeTheFixKeepTheirDevice() = runBlocking {
        val store = MapStore(); val api = FakeFieldApi()
        binding(store).connect(pc, fromScan = true, api)
        store.remove(PhoneBinding.KEY_SCOPE) // older installs saved no scope
        assertEquals("dev-1", binding(store).connect(pc, fromScan = false, api))
        assertEquals(1, api.registrations)
    }
}
