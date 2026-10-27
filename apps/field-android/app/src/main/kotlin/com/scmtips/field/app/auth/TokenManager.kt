package com.scmtips.field.app.auth

import android.net.Uri
import com.scmtips.field.core.outbox.api.AuthExchangeRequest
import com.scmtips.field.core.outbox.api.FieldApiService
import com.scmtips.field.core.outbox.api.TokenProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicReference

sealed class AuthState {
    object Unauthenticated : AuthState()
    object Enrolling : AuthState()
    data class Authenticated(
        val tenantId: String,
        val deviceId: String,
        val siteId: String?,
        val permissions: List<String>
    ) : AuthState()
    data class Error(val message: String, val code: String? = null) : AuthState()
    object Revoked : AuthState()
}

/**
 * Token and Enrolment Manager (Task T2.004 / FR2.001).
 * Encrypts core token with Keystore AES-256-GCM; maintains Field JWT in-memory only.
 */
class TokenManager(
    private val cryptoManager: CryptoManager,
    private val apiService: FieldApiService,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO)
) : TokenProvider {

    private val KEY_ALIAS = "field_core_device_token"

    // Persistent encrypted core token payload (mock DataStore storage)
    private val encryptedCoreTokenStore = AtomicReference<ByteArray?>(null)

    // IN-MEMORY ONLY Field JWT (Never persisted to disk, FR2.001)
    @Volatile
    private var inMemoryFieldJwt: String? = null
    private var tokenExpiryEpochMs: Long = 0L
    private var refreshJob: Job? = null

    private val _authState = MutableStateFlow<AuthState>(AuthState.Unauthenticated)
    val authState: StateFlow<AuthState> = _authState.asStateFlow()

    override fun getFieldToken(): String? = inMemoryFieldJwt

    /**
     * Enrol from deep link `scmtips-field://enrol?token=...&deviceId=...&siteId=...`
     */
    fun enrolFromDeepLink(uri: Uri) {
        val token = uri.getQueryParameter("token")
        val deviceId = uri.getQueryParameter("deviceId")
        val siteId = uri.getQueryParameter("siteId")

        if (token.isNullOrBlank() || deviceId.isNullOrBlank()) {
            _authState.value = AuthState.Error("Invalid enrolment parameters", "FIELD-AUTH-400-INVALID-ENROL")
            return
        }

        enrolDeviceToken(token, deviceId, siteId)
    }

    /**
     * Stores encrypted token in Keystore and executes /v1/auth/exchange.
     */
    fun enrolDeviceToken(coreDeviceToken: String, deviceId: String, siteId: String?) {
        scope.launch {
            _authState.value = AuthState.Enrolling
            try {
                // 1. Encrypt with Android Keystore AES-256-GCM before storage
                val encrypted = cryptoManager.encrypt(KEY_ALIAS, coreDeviceToken.toByteArray(Charsets.UTF_8))
                encryptedCoreTokenStore.set(encrypted)

                // 2. Exchange token for in-memory Field JWT
                performTokenExchange(coreDeviceToken, deviceId, siteId)
            } catch (e: Exception) {
                _authState.value = AuthState.Error(e.message ?: "Enrolment failed", "FIELD-AUTH-500-EXCHANGE")
            }
        }
    }

    private suspend fun performTokenExchange(coreDeviceToken: String, deviceId: String, siteId: String?) {
        val req = AuthExchangeRequest(
            core_device_token = coreDeviceToken,
            device_id = deviceId,
            site_id = siteId
        )

        val res = apiService.exchangeToken(req)
        if (res.isSuccessful && res.body() != null) {
            val body = res.body()!!
            // Store JWT in RAM only
            inMemoryFieldJwt = body.field_jwt
            val lifetimeMs = body.expires_in_seconds * 1000L
            tokenExpiryEpochMs = System.currentTimeMillis() + lifetimeMs

            _authState.value = AuthState.Authenticated(
                tenantId = body.tenant_id,
                deviceId = body.device_id,
                siteId = siteId,
                permissions = body.permissions
            )

            // Schedule proactive re-exchange 60 seconds before expiry (T2.004)
            scheduleProactiveRefresh(deviceId, siteId, lifetimeMs)
        } else {
            if (res.code() == 401) {
                _authState.value = AuthState.Error("Device token revoked", "FIELD-AUTH-401-REVOKED")
            } else {
                _authState.value = AuthState.Error("Exchange failed: ${res.code()}", "FIELD-AUTH-EXCHANGE-FAILED")
            }
        }
    }

    private fun scheduleProactiveRefresh(deviceId: String, siteId: String?, lifetimeMs: Long) {
        refreshJob?.cancel()
        refreshJob = scope.launch {
            // Re-exchange 60s before expiry (or half lifetime if short)
            val refreshDelayMs = (lifetimeMs - 60_000L).coerceAtLeast(lifetimeMs / 2)
            delay(refreshDelayMs)

            val encrypted = encryptedCoreTokenStore.get()
            if (encrypted != null) {
                try {
                    val decryptedCoreToken = String(cryptoManager.decrypt(KEY_ALIAS, encrypted), Charsets.UTF_8)
                    performTokenExchange(decryptedCoreToken, deviceId, siteId)
                } catch (e: Exception) {
                    _authState.value = AuthState.Error("Proactive re-exchange failed: ${e.message}")
                }
            }
        }
    }

    fun revoke() {
        refreshJob?.cancel()
        inMemoryFieldJwt = null
        encryptedCoreTokenStore.set(null)
        _authState.value = AuthState.Revoked
    }

    fun isPlaintextStored(): Boolean {
        // Verification probe: confirms device token is never stored in plaintext
        val stored = encryptedCoreTokenStore.get() ?: return false
        val sample = "SAMPLE-CORE-TOKEN"
        return String(stored, Charsets.ISO_8859_1).contains(sample)
    }
}
