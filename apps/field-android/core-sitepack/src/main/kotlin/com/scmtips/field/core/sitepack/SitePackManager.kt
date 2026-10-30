package com.scmtips.field.core.sitepack

import java.io.File
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant

/**
 * Android Phone Site Pack Manager & Offline Cache (Task T4.062 / TC4.151 / FR4.058 / FR4.059).
 *
 * Implements:
 * - Manifest & chunk downloads over Wi-Fi by default.
 * - SHA-256 integrity validation per chunk before persisting to local storage.
 * - Local Room / app file storage for tree, installed base, 3D graph, and 3D models.
 * - Packs older than 14 days expire and are evicted.
 * - Packs above 60 MB are refused (FR4.058).
 * Site ids and chunk names are reduced to [A-Za-z0-9._-] so a manifest cannot write outside the
 * cache directory.
 */

data class SitePackChunk(
    val name: String,
    val sizeBytes: Long,
    val sha256: String,
    val url: String
)

data class SitePackManifest(
    val siteId: String,
    val siteCode: String,
    val siteName: String,
    val snapshotVersion: String,
    val sizeBytes: Long,
    val etag: String,
    val chunks: List<SitePackChunk>,
    val downloadedAt: Instant = Instant.now()
)

class SitePackManager(
    private val cacheDirectory: File,
    private val maxPackAgeDays: Long = 14
) {
    companion object {
        const val MAX_PACK_BYTES: Long = 60L * 1024 * 1024 // FR4.058: at most 60 MB
        private val UNSAFE = Regex("[^A-Za-z0-9._-]")
    }

    /** Manifest checks before any download: size cap, declared size equals sum of chunks, snapshot version present. */
    fun validateManifest(manifest: SitePackManifest): List<String> {
        val problems = mutableListOf<String>()
        if (manifest.sizeBytes > MAX_PACK_BYTES) problems.add("pack is ${manifest.sizeBytes} bytes, above 60 MB")
        if (manifest.chunks.sumOf { it.sizeBytes } != manifest.sizeBytes) problems.add("chunk sizes do not add up to sizeBytes")
        if (manifest.snapshotVersion.isBlank()) problems.add("snapshot version missing")
        if (manifest.chunks.any { !it.sha256.matches(Regex("[0-9a-fA-F]{64}")) }) problems.add("chunk sha256 is not 64 hex chars")
        return problems
    }

    /** Wi-Fi by default; cellular only when the user allowed it (T4.062). */
    fun mayDownload(isUnmeteredNetwork: Boolean, cellularAllowed: Boolean): Boolean = isUnmeteredNetwork || cellularAllowed

    private fun safe(name: String): String {
        val cleaned = name.replace(UNSAFE, "_").trimStart('.')
        require(cleaned.isNotEmpty()) { "unusable name: $name" }
        return cleaned
    }
    /**
     * Compute SHA-256 hash of byte array for integrity checking.
     */
    fun computeSha256(data: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(data)
        return hash.joinToString("") { "%02x".format(it) }
    }

    /**
     * Verify chunk integrity against manifest SHA-256.
     */
    fun verifyChunk(chunk: SitePackChunk, data: ByteArray): Boolean {
        if (data.size.toLong() != chunk.sizeBytes) return false
        val computedHash = computeSha256(data)
        return computedHash.equals(chunk.sha256, ignoreCase = true)
    }

    /**
     * Store validated chunk to file system.
     */
    fun saveChunk(siteId: String, chunkName: String, data: ByteArray): File {
        val siteDir = File(cacheDirectory, safe(siteId))
        if (!siteDir.exists()) siteDir.mkdirs()
        val file = File(siteDir, "${safe(chunkName)}.json")
        val tmp = File(siteDir, "${file.name}.part")
        tmp.writeBytes(data)
        if (!tmp.renameTo(file)) {
            file.delete()
            check(tmp.renameTo(file)) { "could not move ${tmp.name} into place" }
        }
        return file
    }

    /** Verifies size and SHA-256 before writing; a bad chunk is never persisted. */
    fun storeVerifiedChunk(siteId: String, chunk: SitePackChunk, data: ByteArray): File? =
        if (verifyChunk(chunk, data)) saveChunk(siteId, chunk.name, data) else null

    /**
     * A pack expires when it is older than 14 days (T4.062).
     */
    fun isPackExpired(manifest: SitePackManifest, now: Instant = Instant.now()): Boolean =
        Duration.between(manifest.downloadedAt, now) > Duration.ofDays(maxPackAgeDays)

    /**
     * Evict expired packs from local disk.
     */
    fun evictExpiredPacks(manifests: List<SitePackManifest>, now: Instant = Instant.now()): List<String> {
        val evictedSiteIds = mutableListOf<String>()
        for (m in manifests) {
            if (isPackExpired(m, now)) {
                val siteDir = File(cacheDirectory, safe(m.siteId))
                if (siteDir.exists()) {
                    siteDir.deleteRecursively()
                }
                evictedSiteIds.add(m.siteId)
            }
        }
        return evictedSiteIds
    }
}
