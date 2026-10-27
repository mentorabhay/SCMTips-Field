package com.scmtips.field.app.auth

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Android Keystore AES-256-GCM authenticated encryption manager (Task T2.004 / FR2.001).
 * Guarantees cryptographic keys are backed by hardware keystore where available.
 */
class CryptoManager {

    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply {
        load(null)
    }

    private fun getOrCreateSecretKey(alias: String): SecretKey {
        val existingKey = keyStore.getEntry(alias, null) as? KeyStore.SecretKeyEntry
        return existingKey?.secretKey ?: createSecretKey(alias)
    }

    private fun createSecretKey(alias: String): SecretKey {
        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore"
        )
        val spec = KeyGenParameterSpec.Builder(
            alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()

        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }

    fun encrypt(alias: String, plaintext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey(alias))
        val iv = cipher.iv
        val ciphertext = cipher.doFinal(plaintext)
        
        // Return IV prepended to ciphertext: [IV length (1 byte)] + [IV] + [Ciphertext + Tag]
        return byteArrayOf(iv.size.toByte()) + iv + ciphertext
    }

    fun decrypt(alias: String, encryptedPayload: ByteArray): ByteArray {
        val ivSize = encryptedPayload[0].toInt()
        val iv = encryptedPayload.copyOfRange(1, 1 + ivSize)
        val ciphertext = encryptedPayload.copyOfRange(1 + ivSize, encryptedPayload.size)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val spec = GCMParameterSpec(128, iv)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateSecretKey(alias), spec)
        return cipher.doFinal(ciphertext)
    }
}
