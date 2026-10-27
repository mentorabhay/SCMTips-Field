package com.scmtips.field.core.outbox.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.scmtips.field.core.outbox.api.FieldApiClient
import com.scmtips.field.core.outbox.crypto.CropEncryptedStorage
import com.scmtips.field.core.outbox.db.OutboxDao
import com.scmtips.field.core.outbox.db.OutboxDatabase
import com.scmtips.field.core.outbox.db.OutboxItemEntity
import com.scmtips.field.core.outbox.db.OutboxStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Worker interface for sync delivery, abstracted for production WorkManager
 * and unit test simulation harness (Task T2.041 / FR2.040, FR2.045).
 */
interface SyncEngine {
    suspend fun processOneRound(): Boolean
}

/**
 * Core sync orchestration logic guaranteeing:
 * 1. Per-task strict sequential delivery (item n+1 waits for terminal result of item n) (FR2.040, PR2.08)
 * 2. Round-robin fairness across concurrent tasks
 * 3. Exact conflict handling per BR2.11 (FR2.041)
 * 4. Exponential backoff ladder (FR2.045)
 */
class OutboxSyncEngine(
    private val outboxDao: OutboxDao,
    private val cropStorage: CropEncryptedStorage,
    private val networkSender: suspend (item: OutboxItemEntity, cropBytes: ByteArray?) -> SyncNetworkResponse
) : SyncEngine {

    data class SyncNetworkResponse(
        val statusCode: Int,
        val body: String?,
        val isNetworkFailure: Boolean = false
    )

    override suspend fun processOneRound(): Boolean {
        val activeTaskIds = outboxDao.getActiveTaskIds()
        if (activeTaskIds.isEmpty()) return false

        var anyItemProcessed = false
        val now = System.currentTimeMillis()

        // Serve tasks round-robin
        for (taskId in activeTaskIds) {
            val nextItem = outboxDao.getNextPendingItemForTask(taskId) ?: continue

            // If item has a pending retry delay that has not elapsed yet, skip
            if (nextItem.nextRetryAt > now) {
                continue
            }

            // Strictly process item n: set to IN_FLIGHT
            outboxDao.updateStatus(nextItem.id, OutboxStatus.IN_FLIGHT.name)
            anyItemProcessed = true

            // Read crop file if attached
            val cropBytes = nextItem.cropFileId?.let { cropId ->
                val cropFile = outboxDao.getCropFileForCapture(nextItem.id)
                cropFile?.let { cropStorage.readDecryptedCrop(File(it.filePath)) }
            }

            val response = try {
                networkSender(nextItem, cropBytes)
            } catch (e: Exception) {
                SyncNetworkResponse(0, e.message, isNetworkFailure = true)
            }

            val decision = ConflictPolicy.evaluate(
                httpStatusCode = response.statusCode,
                responseBody = response.body,
                item = nextItem,
                isNetworkError = response.isNetworkFailure
            )

            when (decision) {
                is SyncDecision.Ack -> {
                    val finalStatus = if (decision.isDuplicate) {
                        OutboxStatus.DUPLICATE_ACKED
                    } else {
                        OutboxStatus.ACKED
                    }
                    outboxDao.updateStatus(nextItem.id, finalStatus.name)
                }
                is SyncDecision.Quarantine -> {
                    val updated = nextItem.copy(
                        status = OutboxStatus.QUARANTINED.name,
                        lastError = decision.reason,
                        updatedAt = System.currentTimeMillis()
                    )
                    outboxDao.updateItem(updated)
                }
                is SyncDecision.Reject -> {
                    val updated = nextItem.copy(
                        status = OutboxStatus.REJECTED.name,
                        lastError = decision.reason,
                        updatedAt = System.currentTimeMillis()
                    )
                    outboxDao.updateItem(updated)
                }
                is SyncDecision.PauseAll -> {
                    outboxDao.pauseAllPending()
                    return true // All paused, end round
                }
                is SyncDecision.RecompressAndRetry -> {
                    // Mark as recompressed and retry immediately in next pass
                    val updated = nextItem.copy(
                        status = OutboxStatus.QUEUED.name,
                        recompressed = true,
                        attempts = nextItem.attempts + 1,
                        updatedAt = System.currentTimeMillis()
                    )
                    outboxDao.updateItem(updated)
                }
                is SyncDecision.Retry -> {
                    val updated = nextItem.copy(
                        status = OutboxStatus.QUEUED.name,
                        attempts = nextItem.attempts + 1,
                        lastError = decision.reason,
                        nextRetryAt = System.currentTimeMillis() + decision.delayMs,
                        updatedAt = System.currentTimeMillis()
                    )
                    outboxDao.updateItem(updated)
                }
            }
        }
        return anyItemProcessed
    }
}

/**
 * Android WorkManager CoroutineWorker for background sync.
 */
class SyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    companion object {
        const val UNIQUE_WORK_NAME = "com.scmtips.field.outbox.sync"

        fun enqueue(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(constraints)
                .setBackoffCriteria(
                    androidx.work.BackoffPolicy.EXPONENTIAL,
                    30,
                    TimeUnit.SECONDS
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request
            )
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val db = OutboxDatabase.getInstance(applicationContext)
        val cropsDir = File(applicationContext.noBackupFilesDir, "crops")
        val cropStorage = CropEncryptedStorage(cropsDir) {
            OutboxDatabase.getOrCreatePassphrase(applicationContext)
        }
        val apiClient = FieldApiClient(baseUrl = "https://api.field.scmtips.internal")

        val engine = OutboxSyncEngine(
            outboxDao = db.outboxDao(),
            cropStorage = cropStorage,
            networkSender = { item, crop ->
                // Production network sender dispatches via FieldApiClient
                val resp = apiClient.postCaptureSync(item.id, item.payloadJson, crop)
                OutboxSyncEngine.SyncNetworkResponse(resp.first, resp.second)
            }
        )

        var rounds = 0
        while (rounds < 50 && engine.processOneRound()) {
            rounds++
        }

        Result.success()
    }
}
