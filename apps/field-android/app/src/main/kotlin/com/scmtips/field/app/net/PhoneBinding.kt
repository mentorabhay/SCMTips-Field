package com.scmtips.field.app.net

/**
 * Which field device this phone is, per PC and company (scope = api base URL + tenant), and how to get
 * there again without "Device already bound".
 *
 * Owner report 2026-10-31: the app crashed right after a successful registration; scanning the QR again
 * forgot the saved device id and registered the same serial with a fresh Idempotency-Key, which the API
 * rightly answers with 409 FIELD-DEV-409-EXISTS (spec TC1.168). Now:
 * - the device id is kept when the scanned code is for the same scope;
 * - the first registration's Idempotency-Key is saved before the call, so a repeat replays the original
 *   201 (same id) instead of 409;
 * - if the API still says EXISTS (its replay record expired), the phone registers once more under a new
 *   install id, like a reinstall; the old entry stays listed for supervisors to revoke;
 * - a saved id the API calls revoked (403 DEVICE-REVOKED, also the answer for an unknown id) is replaced
 *   only when the person has just scanned a pairing code ([fromScan]); on a plain restart the error
 *   stands, so revoking a phone is never undone silently.
 */
class PhoneBinding(private val store: Store, private val newId: () -> String) {
    interface Store {
        fun get(key: String): String?
        fun put(key: String, value: String)
        fun remove(key: String)
    }

    interface Api {
        /** Exchange the core token, bound to [deviceId] when given. Throws [HttpError] on refusal. */
        suspend fun exchange(deviceId: String?)

        /** POST /v1/devices for this phone with the given Idempotency-Key; returns the device id. */
        suspend fun register(serial: String, idempotencyKey: String): String
    }

    /** The device id saved for [scope], if any. */
    fun savedDevice(scope: String): String? = store.get(KEY_SCOPE).let { if (it == null || it == scope) store.get(KEY_DEVICE) else null }

    suspend fun connect(scope: String, fromScan: Boolean, api: Api): String {
        val stored = store.get(KEY_SCOPE)
        if (stored != null && stored != scope) { // another PC or company: its device id means nothing here
            store.remove(KEY_DEVICE)
            store.remove(KEY_REG_KEY)
        }
        store.put(KEY_SCOPE, scope) // installs from before 2026-10-31 had no scope: adopt the current one
        store.get(KEY_DEVICE)?.let { saved ->
            try {
                api.exchange(saved)
                return saved
            } catch (e: HttpError) {
                if (e.code != DEVICE_REVOKED || !fromScan) throw e
                newInstall()
            }
        }
        api.exchange(null)
        val id = try {
            api.register(serial(), regKey())
        } catch (e: HttpError) {
            if (e.code != DEVICE_EXISTS) throw e
            newInstall()
            api.register(serial(), regKey())
        }
        store.put(KEY_DEVICE, id)
        api.exchange(id)
        return id
    }

    private fun serial(): String = store.get(KEY_SERIAL) ?: newId().also { store.put(KEY_SERIAL, it) }

    /**
     * This install's id (the serial field-api knows the phone by), made once. M4: also the `device_id`
     * the core's sign-in binds the wearable token to (a UUID: 36 of [A-Za-z0-9._:-]).
     */
    fun installId(): String = serial()

    private fun regKey(): String = store.get(KEY_REG_KEY) ?: newId().also { store.put(KEY_REG_KEY, it) }

    private fun newInstall() {
        store.remove(KEY_DEVICE)
        store.remove(KEY_REG_KEY)
        store.put(KEY_SERIAL, newId())
    }

    companion object {
        const val KEY_SCOPE = "device_scope"
        const val KEY_DEVICE = "device_id"
        const val KEY_SERIAL = "serial"
        const val KEY_REG_KEY = "device_registration_key"
        const val DEVICE_EXISTS = "FIELD-DEV-409-EXISTS"
        const val DEVICE_REVOKED = "FIELD-AUTH-403-DEVICE-REVOKED"

        fun scope(apiBaseUrl: String, tenantId: String): String = apiBaseUrl.trimEnd('/').lowercase() + "|" + tenantId
    }
}
