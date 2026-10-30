package com.scmtips.field.core.outbox.crypto

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import javax.crypto.AEADBadTagException

/** CropEncryptedStorage: AES-256-GCM crop files (FR2.043; the Keystore-held key is out of scope here). */
class CropEncryptedStorageTest {
    private val dir = Files.createTempDirectory("crops").toFile()
    private val key = ByteArray(32) { (it * 7).toByte() }
    private val store = CropEncryptedStorage(dir) { key }
    private val jpeg = ByteArray(4_096) { (it % 256).toByte() }

    @Test
    fun fr2_043_cropFileIsCiphertextAndRoundTrips() {
        val f = store.writeEncryptedCrop("c1", jpeg)
        val raw = f.readBytes()
        assertEquals(12 + jpeg.size + 16, raw.size)
        assertFalse("plaintext must not appear on disk", raw.toList().windowed(64).contains(jpeg.take(64)))
        assertArrayEquals(jpeg, store.readDecryptedCrop(f))
        val f2 = store.writeEncryptedCrop("c2", jpeg)
        assertFalse("fresh IV per file", raw.copyOfRange(0, 12).contentEquals(f2.readBytes().copyOfRange(0, 12)))
    }

    @Test
    fun fr2_043_tamperingOrAWrongKeyIsDetected() {
        val f = store.writeEncryptedCrop("c3", jpeg)
        val bytes = f.readBytes(); bytes[40] = (bytes[40].toInt() xor 1).toByte(); f.writeBytes(bytes)
        assertTrue(runCatching { store.readDecryptedCrop(f) }.exceptionOrNull() is AEADBadTagException)
        val g = store.writeEncryptedCrop("c4", jpeg)
        val other = CropEncryptedStorage(dir) { ByteArray(32) { 1 } }
        assertTrue(runCatching { other.readDecryptedCrop(g) }.exceptionOrNull() is AEADBadTagException)
    }

    @Test
    fun onlyAes256KeysAreAccepted() {
        val weak = CropEncryptedStorage(dir) { ByteArray(16) }
        assertTrue(runCatching { weak.writeEncryptedCrop("c5", jpeg) }.exceptionOrNull() is IllegalArgumentException)
    }

    @Test
    fun sha256IsHex() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", store.computeSha256(ByteArray(0)))
    }
}
