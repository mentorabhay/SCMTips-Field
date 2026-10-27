package com.scmtips.field.core.outbox.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Outbox item status lifecycle states per FR2.040, FR2.041, BR2.11.
 */
enum class OutboxStatus {
    QUEUED,
    IN_FLIGHT,
    ACKED,
    DUPLICATE_ACKED,
    QUARANTINED,
    REJECTED,
    PAUSED
}

/**
 * Room entity representing an outbox item queued for upload.
 * Persisted in SQLCipher encrypted Room database.
 */
@Entity(
    tableName = "outbox_item",
    indices = [
        Index(value = ["task_id", "client_seq"], unique = true),
        Index(value = ["status"]),
        Index(value = ["created_at"])
    ]
)
data class OutboxItemEntity(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String, // UUIDv7 idempotency key

    @ColumnInfo(name = "task_id")
    val taskId: String,

    @ColumnInfo(name = "client_seq")
    val clientSeq: Long,

    @ColumnInfo(name = "shutter_timestamp")
    val shutterTimestamp: Long,

    @ColumnInfo(name = "payload_type")
    val payloadType: String, // CAPTURE, VOICE_EVENT, COUNT_RECORD, POST_REQUEST

    @ColumnInfo(name = "payload_json")
    val payloadJson: String,

    @ColumnInfo(name = "crop_file_id")
    val cropFileId: String? = null,

    @ColumnInfo(name = "status")
    val status: String = OutboxStatus.QUEUED.name,

    @ColumnInfo(name = "attempts")
    val attempts: Int = 0,

    @ColumnInfo(name = "last_error")
    val lastError: String? = null,

    @ColumnInfo(name = "next_retry_at")
    val nextRetryAt: Long = 0L,

    @ColumnInfo(name = "recompressed")
    val recompressed: Boolean = false,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis()
)

/**
 * Room entity tracking local crop files stored under noBackupFilesDir
 * and encrypted using AES-256-GCM.
 */
@Entity(
    tableName = "crop_file",
    indices = [
        Index(value = ["capture_id"]),
        Index(value = ["created_at"])
    ]
)
data class CropFileEntity(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String,

    @ColumnInfo(name = "capture_id")
    val captureId: String,

    @ColumnInfo(name = "file_path")
    val filePath: String,

    @ColumnInfo(name = "file_size_bytes")
    val fileSizeBytes: Long,

    @ColumnInfo(name = "sha256_hash")
    val sha256Hash: String,

    @ColumnInfo(name = "is_encrypted")
    val isEncrypted: Boolean = true,

    @ColumnInfo(name = "is_fsynced")
    val isFsynced: Boolean = true,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis()
)
