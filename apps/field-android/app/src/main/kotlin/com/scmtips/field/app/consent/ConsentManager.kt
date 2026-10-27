package com.scmtips.field.app.consent

import com.scmtips.field.core.outbox.api.ConsentRecordRequest
import com.scmtips.field.core.outbox.api.FieldApiService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class ConsentStatus {
    object NotChecked : ConsentStatus()
    object ConsentRequired : ConsentStatus()
    object Granted : ConsentStatus()
    data class Refused(val reason: String, val errorCode: String) : ConsentStatus()
}

/**
 * Consent Manager enforcing site privacy consent and hardware capture indicator check
 * (Task T2.010 / FR2.064 / TC2.154 / TC2.155).
 */
class ConsentManager(
    private val apiService: FieldApiService,
    private val checkToolkitIndicatorAvailable: () -> Boolean = { true }
) {
    companion object {
        const val CONSENT_TYPE = "site_and_bystander_privacy"
        const val ERR_NO_CONSENT = "FIELD-CAP-403-NO-CONSENT"
        const val ERR_INDICATOR_UNAVAILABLE = "FIELD-CAP-503-INDICATOR-UNAVAILABLE"
    }

    private val localConsentCache = mutableSetOf<String>() // key: "$userId:$deviceId:$siteId"
    private val _status = MutableStateFlow<ConsentStatus>(ConsentStatus.NotChecked)
    val status: StateFlow<ConsentStatus> = _status.asStateFlow()

    private fun cacheKey(userId: String, deviceId: String, siteId: String): String =
        "$userId:$deviceId:$siteId"

    /**
     * Checks whether valid consent exists and validates toolkit hardware LED indicator.
     */
    fun checkCanStartSession(userId: String, deviceId: String, siteId: String): ConsentStatus {
        // 1. Hardware Privacy Indicator Check (TC2.155)
        if (!checkToolkitIndicatorAvailable()) {
            val refused = ConsentStatus.Refused(
                "Hardware capture indicator LED is unavailable or disabled.",
                ERR_INDICATOR_UNAVAILABLE
            )
            _status.value = refused
            return refused
        }

        // 2. Consent Record Check (TC2.154)
        val key = cacheKey(userId, deviceId, siteId)
        return if (localConsentCache.contains(key)) {
            _status.value = ConsentStatus.Granted
            ConsentStatus.Granted
        } else {
            _status.value = ConsentStatus.ConsentRequired
            ConsentStatus.ConsentRequired
        }
    }

    /**
     * Records affirmative consent (SCR2.09 Agree) and posts to /v1/consents.
     */
    suspend fun grantConsent(userId: String, deviceId: String, siteId: String): Boolean {
        // Verify capture indicator is operational
        if (!checkToolkitIndicatorAvailable()) {
            _status.value = ConsentStatus.Refused(
                "Capture indicator is unavailable",
                ERR_INDICATOR_UNAVAILABLE
            )
            return false
        }

        try {
            val req = ConsentRecordRequest(
                user_id = userId,
                device_id = deviceId,
                site_id = siteId,
                consent_type = CONSENT_TYPE,
                granted = true
            )
            val res = apiService.recordConsent(req)
            if (res.isSuccessful) {
                localConsentCache.add(cacheKey(userId, deviceId, siteId))
                _status.value = ConsentStatus.Granted
                return true
            } else {
                _status.value = ConsentStatus.Refused(
                    "Server failed to record consent: ${res.code()}",
                    ERR_NO_CONSENT
                )
                return false
            }
        } catch (e: Exception) {
            _status.value = ConsentStatus.Refused(
                "Consent grant error: ${e.message}",
                ERR_NO_CONSENT
            )
            return false
        }
    }

    /**
     * Withdraws consent (SCR2.09 Withdraw), clearing local cache and blocking future sessions.
     */
    fun withdrawConsent(userId: String, deviceId: String, siteId: String) {
        localConsentCache.remove(cacheKey(userId, deviceId, siteId))
        _status.value = ConsentStatus.Refused(
            "Consent withdrawn by user. Session blocked.",
            ERR_NO_CONSENT
        )
    }
}
