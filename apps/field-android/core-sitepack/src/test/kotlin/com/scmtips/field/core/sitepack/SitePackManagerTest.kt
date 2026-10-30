package com.scmtips.field.core.sitepack

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.Duration
import java.time.Instant

/** Site pack storage on the phone (T4.062; FR4.058 size cap; FR4.059 offline cache). */
class SitePackManagerTest {

    private val dir: File = Files.createTempDirectory("sitepack").toFile().apply { deleteOnExit() }
    private val m = SitePackManager(dir)
    private val data = "{\"locations\":[]}".toByteArray()
    private val chunk = SitePackChunk("tree", data.size.toLong(), m.computeSha256(data), "https://example.invalid/tree")

    private fun manifest(size: Long = data.size.toLong(), at: Instant = Instant.parse("2026-11-01T00:00:00Z"), chunks: List<SitePackChunk> = listOf(chunk)) =
        SitePackManifest("site-1", "S1", "Site", "snap-42", size, "etag", chunks, at)

    @Test
    fun fr4_059_chunkStoredOnlyWhenSizeAndSha256Match() {
        assertNotNull(m.storeVerifiedChunk("site-1", chunk, data))
        assertTrue(File(dir, "site-1/tree.json").readBytes().contentEquals(data))
        assertNull(m.storeVerifiedChunk("site-1", chunk.copy(name = "bad"), "tampered!!!!!!!!".toByteArray()))
        assertNull(m.storeVerifiedChunk("site-1", chunk.copy(name = "short"), data.copyOf(3)))
        assertFalse(File(dir, "site-1/bad.json").exists())
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", m.computeSha256(ByteArray(0)))
    }

    @Test
    fun fr4_058_manifestAbove60MbOrInconsistentIsRefused() {
        assertEquals(emptyList<String>(), m.validateManifest(manifest()))
        val big = SitePackChunk("models", SitePackManager.MAX_PACK_BYTES + 1, "a".repeat(64), "u")
        assertTrue(m.validateManifest(manifest(size = big.sizeBytes, chunks = listOf(big))).any { "60 MB" in it })
        assertTrue(m.validateManifest(manifest(size = 999)).isNotEmpty())
        assertTrue(m.validateManifest(manifest().copy(snapshotVersion = "")).isNotEmpty())
    }

    @Test
    fun fr4_059_packOlderThan14DaysExpiresAndIsEvicted() {
        val t0 = Instant.parse("2026-11-01T00:00:00Z")
        assertFalse(m.isPackExpired(manifest(at = t0), t0.plus(Duration.ofDays(14))))
        assertTrue(m.isPackExpired(manifest(at = t0), t0.plus(Duration.ofDays(14)).plusSeconds(1)))
        m.saveChunk("site-1", "tree", data)
        assertEquals(listOf("site-1"), m.evictExpiredPacks(listOf(manifest(at = t0)), t0.plus(Duration.ofDays(15))))
        assertFalse(File(dir, "site-1").exists())
    }

    @Test
    fun fr4_059_namesCannotEscapeTheCacheDirectory() {
        val f = m.saveChunk("../../etc", "../passwd", data)
        assertTrue(f.canonicalPath.startsWith(dir.canonicalPath + File.separator))
    }

    @Test
    fun wifiByDefaultCellularOnlyWhenAllowed() {
        assertTrue(m.mayDownload(isUnmeteredNetwork = true, cellularAllowed = false))
        assertFalse(m.mayDownload(isUnmeteredNetwork = false, cellularAllowed = false))
        assertTrue(m.mayDownload(isUnmeteredNetwork = false, cellularAllowed = true))
    }
}
