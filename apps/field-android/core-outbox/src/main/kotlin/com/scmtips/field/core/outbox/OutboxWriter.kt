package com.scmtips.field.core.outbox

import com.scmtips.field.core.outbox.crypto.CropEncryptedStorage
import com.scmtips.field.core.outbox.db.CropFileEntity
import com.scmtips.field.core.outbox.db.OutboxDao
import com.scmtips.field.core.outbox.db.OutboxItemEntity
import com.scmtips.field.core.outbox.db.OutboxStatus
import java.io.File
import java.nio.ByteBuffer
import java.security.SecureRandom
import java.util.UUID

/**
 * Generates RFC 9562 UUIDv7 identifiers with monotonic sub-millisecond sequencing (FR2.039).
 */
object UuidV7 {
    private val random = SecureRandom()
    private var lastTimestampMs = -1L
    private var sequenceCounter = 0

    @Synchronized
    fun generate(): String {
        var currentMs = System.currentTimeMillis()
        if (currentMs < lastTimestampMs) {
            // Clock moved backwards, clamp
            currentMs = lastTimestampMs
        }

        if (currentMs == lastTimestampMs) {
            sequenceCounter = (sequenceCounter + 1) and 0x0FFF
            if (sequenceCounter == 0) {
                // Counter wrapped in same millisecond, increment millisecond
                currentMs++
                lastTimestampMs = currentMs
            }
        } else {
            lastTimestampMs = currentMs
            sequenceCounter = random.nextInt(0x0FFF)
        }

        val msb = (currentMs shl 16) or (0x7000L) or (sequenceCounter.toLong() and 0x0FFFL)
        val randBytes = ByteArray(8).apply { random.nextBytes(this) }
        val lsbRaw = ByteBuffer.wrap(randBytes).long
        val lsb = (0x8000000000000000UL.toLong()) or (lsbRaw and 0x3FFFFFFFFFFFFFFFL)

        return UUID(msb, lsb).toString()
    }
}

/**
 * OutboxWriter commits capture items and associated crop files atomically (Task T2.040 / FR2.039, FR2.044).
 * Enforces fsync of encrypted crop files before Room transaction commit.
 * Includes orphan crop sweep older than 10 minutes.
 */
class OutboxWriter(
    private val outboxDao: OutboxDao,
    private val cropStorage: CropEncryptedStorage,
    private val cropsDir: File,
    private val capacityGovernor: QueueCapacityGovernor? = null
) {

    /**
     * Commits a capture atomically.
     * 1. Check capacity limit (FR2.042)
     * 2. Generate UUIDv7 key at shutter time (FR2.039)
     * 3. Encrypt crop bytes and fsync to disk (FR2.044)
     * 4. Allocate next per-task clientSeq
     * 5. Commit outbox_item and crop_file atomically in a Room transaction
     */
    suspend fun commitCapture(
        taskId: String,
        payloadType: String,
        payloadJson: String,
        cropBytes: ByteArray?,
        shutterTimestamp: Long = System.currentTimeMillis(),
        faultInjectionPoint: ((String) -> Unit)? = null
    ): OutboxItemEntity {
        // Step 1: Check capacity
        if (capacityGovernor != null) {
            val estimatedSizeBytes = cropBytes?.size?.toLong() ?: 0L
            val refusalMsg = capacityGovernor.checkAdmission(1, estimatedSizeBytes)
            if (refusalMsg != null) {
                throw IllegalStateException(refusalMsg)
            }
        }

        // Step 2: UUIDv7 idempotency key assigned at shutter time
        val idempotencyKey = UuidV7.generate()
        faultInjectionPoint?.invoke("AFTER_UUID_GENERATION")

        var cropEntity: CropFileEntity? = null

        // Step 3: Fsync encrypted crop file if present
        if (cropBytes != null) {
            val cropId = "crop_$idempotencyKey"
            val sha256 = cropStorage.computeSha256(cropBytes)
            val writtenFile = cropStorage.writeEncryptedCrop(cropId, cropBytes)
            faultInjectionPoint?.invoke("AFTER_CROP_FSYNC")

            cropEntity = CropFileEntity(
                id = cropId,
                captureId = idempotencyKey,
                filePath = writtenFile.absolutePath,
                fileSizeBytes = writtenFile.length(),
                sha256Hash = sha256,
                isEncrypted = true,
                isFsynced = true,
                createdAt = shutterTimestamp
            )
        }

        faultInjectionPoint?.invoke("BEFORE_DB_TRANSACTION")

        // Step 4 & 5: Allocate sequence and insert atomically
        val currentMaxSeq = outboxDao.getMaxClientSeqForTask(taskId) ?: 0L
        val nextSeq = currentMaxSeq + 1L

        val item = OutboxItemEntity(
            id = idempotencyKey,
            taskId = taskId,
            clientSeq = nextSeq,
            shutterTimestamp = shutterTimestamp,
            payloadType = payloadType,
            payloadJson = payloadJson,
            cropFileId = cropEntity?.id,
            status = OutboxStatus.QUEUED.name,
            attempts = 0,
            lastError = null,
            nextRetryAt = 0L,
            createdAt = shutterTimestamp,
            updatedAt = shutterTimestamp
        )

        outboxDao.insertCaptureAtomic(item, cropEntity)
        faultInjectionPoint?.invoke("AFTER_DB_COMMIT")

        return item
    }

    /**
     * Sweeps orphan crop files older than 10 minutes (600,000 ms) that do not have
     * a committed record in Room (Task T2.040 / TC2.136).
     */
    suspend fun sweepOrphanCrops(now: Long = System.currentTimeMillis()): Int {
        if (!cropsDir.exists()) return 0
        val maxAgeMs = 10 * 60 * 1000L // 10 minutes
        val committedFiles = outboxDao.getAllCropFiles().map { it.filePath }.toSet()

        var deletedCount = 0
        val files = cropsDir.listFiles() ?: return 0
        for (file in files) {
            if (!committedFiles.contains(file.absolutePath)) {
                val age = now - file.lastModified()
                if (age > maxAgeMs) {
                    if (file.delete()) {
                        deletedCount++
                    }
                }
            }
        }
        return deletedCount
    }
}
