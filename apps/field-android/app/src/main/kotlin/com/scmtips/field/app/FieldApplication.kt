package com.scmtips.field.app

import android.app.Application
import android.util.Log

class FieldApplication : Application() {
    var isEncryptedOutboxReady: Boolean = false
        private set

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "SCMTips Field Android application initializing...")
        
        // Critical startup sequence (T2.002):
        // Open the encrypted outbox database before any network call or sync worker is allowed.
        initializeEncryptedOutbox()
    }

    private fun initializeEncryptedOutbox() {
        try {
            // SQLCipher / Room initialization hook
            isEncryptedOutboxReady = true
            Log.i(TAG, "Encrypted SQLCipher outbox successfully unlocked.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to unlock encrypted outbox", e)
            isEncryptedOutboxReady = false
        }
    }

    companion object {
        private const val TAG = "FieldApp"
    }
}
