package com.scmtips.field.app.pairing

import com.scmtips.field.core.outbox.api.DeviceRegisterRequest
import com.scmtips.field.core.outbox.api.FieldApiService
import com.scmtips.field.core.wearables.GlassesSession
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PairedGlasses(
    val glassesDeviceId: String,
    val model: String,
    val hasDisplay: Boolean,
    val btAddress: String,
    val pairedWithPhoneId: String,
    val pairedAtMs: Long = System.currentTimeMillis()
)

sealed class PairingState {
    object Idle : PairingState()
    object Discovering : PairingState()
    data class Pairing(val address: String) : PairingState()
    data class Paired(val glasses: PairedGlasses) : PairingState()
    data class Error(val message: String) : PairingState()
}

/**
 * Manages phone-to-glasses pairing, Meta companion hand-off, and server device registration.
 * (Task T2.012 / SCR2.03 / FR2.003 / TC2.103).
 */
class GlassesPairingManager(
    private val apiService: FieldApiService,
    private val glassesSession: GlassesSession,
    private val phoneDeviceId: String
) {
    private val _pairingState = MutableStateFlow<PairingState>(PairingState.Idle)
    val pairingState: StateFlow<PairingState> = _pairingState.asStateFlow()

    // Enforce Rule: Only one active glasses pairing per phone (TC2.103)
    private var activeGlasses: PairedGlasses? = null

    fun getActiveGlasses(): PairedGlasses? = activeGlasses

    /**
     * Executes pairing flow:
     * 1. Connects Bluetooth / session to glasses
     * 2. Registers glasses device in Field API (POST /v1/devices with paired_with = phoneDeviceId)
     * 3. Re-pair replaces any previous pairing (TC2.103)
     */
    suspend fun pairGlasses(
        btAddress: String,
        model: String = "Ray-Ban Display",
        hasDisplay: Boolean = true
    ): Boolean {
        _pairingState.value = PairingState.Pairing(btAddress)

        try {
            // 1. Establish session
            glassesSession.connect(btAddress, model)

            // 2. Register glasses device with Field API
            val glassesRegReq = DeviceRegisterRequest(
                kind = if (hasDisplay) "glasses_display" else "glasses_audio",
                model = model,
                app_version = "1.0.0",
                paired_with = phoneDeviceId
            )
            val res = apiService.registerDevice(glassesRegReq)
            val serverGlassesId = if (res.isSuccessful && res.body() != null) {
                res.body()!!.id
            } else {
                "gls-" + btAddress.replace(":", "").takeLast(8)
            }

            // 3. Replace any old pairing
            val newPairing = PairedGlasses(
                glassesDeviceId = serverGlassesId,
                model = model,
                hasDisplay = hasDisplay,
                btAddress = btAddress,
                pairedWithPhoneId = phoneDeviceId
            )
            activeGlasses = newPairing
            _pairingState.value = PairingState.Paired(newPairing)
            return true
        } catch (e: Exception) {
            _pairingState.value = PairingState.Error("Pairing failed: ${e.message}")
            return false
        }
    }

    suspend fun unpair() {
        glassesSession.disconnect()
        activeGlasses = null
        _pairingState.value = PairingState.Idle
    }
}
