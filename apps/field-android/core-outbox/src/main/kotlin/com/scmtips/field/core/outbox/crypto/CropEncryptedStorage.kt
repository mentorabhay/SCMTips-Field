package com.scmtips.field.core.outbox.crypto

import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Handles encrypted storage of image crops under noBackupFilesDir using AES-256-GCM (FR2.043, TC2.135).
 * Enforces fsync before returning to guarantee crash safety.
 */
class CropEncryptedStorage(
    private val storageDir: File,
    private val keyProvider: () -> ByteArray
) {

    init {
        if (!storageDir.exists()) {
            storageDir.mkdirs()
        }
    }

    private fun getSecretKey(): SecretKey {
        val keyBytes = keyProvider()
        require(keyBytes.size == 32) { "AES-256 requires a 32-byte key" }
        return SecretKeySpec(keyBytes, "AES")
    }

    /**
     * Encrypts plaintext crop bytes, writes to disk under storageDir, and fsyncs.
     * File structure: [12-byte IV] + [AES-256-GCM ciphertext + 16-byte auth tag].
     */
    fun writeEncryptedCrop(cropId: String, plaintextBytes: ByteArray): File {
        val file = File(storageDir, "$cropId.enc")
        val secretKey = getSecretKey()

        val iv = ByteArray(12).apply { SecureRandom().nextBytes(this) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey, GCMParameterSpec(128, iv))
        val ciphertextWithTag = cipher.doFinal(plaintextBytes)

        FileOutputStream(file).use { fos ->
            fos.write(iv)
            fos.write(ciphertextWithTag)
            fos.flush()
            fos.fd.sync() // Critical: hardware fsync before returning (FR2.044)
        }
        return file
    }

    /**
     * Reads and decrypts the encrypted crop file, verifying the AES-GCM authentication tag.
     */
    fun readDecryptedCrop(file: File): ByteArray {
        require(file.exists()) { "Crop file does not exist: ${file.absolutePath}" }
        val rawBytes = file.readBytes()
        require(rawBytes.size > 28) { "Corrupt crop file: minimum size is 28 bytes (12 IV + 16 Tag)" }

        val iv = rawBytes.copyOfRange(0, 12)
        val ciphertextWithTag = rawBytes.copyOfRange(12, rawBytes.size)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, getSecretKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertextWithTag)
    }

    /**
     * Computes SHA-256 hex digest of byte array.
     */
    fun computeSha256(data: ByteArray): String {
        val md = MessageDigest.getInstance("SHA-256")
        val digest = md.digest(data)
        return digest.joinToString("") { "%02x".format(it) }
    }
}
