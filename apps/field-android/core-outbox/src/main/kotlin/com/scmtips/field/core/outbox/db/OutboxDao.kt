package com.scmtips.field.core.outbox.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface OutboxDao {

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertItem(item: OutboxItemEntity)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertCropFile(cropFile: CropFileEntity)

    @Transaction
    suspend fun insertCaptureAtomic(item: OutboxItemEntity, cropFile: CropFileEntity?) {
        cropFile?.let { insertCropFile(it) }
        insertItem(item)
    }

    /** Assigns the next per-task client_seq and inserts item and crop in the same transaction (FR2.044). */
    @Transaction
    suspend fun insertCaptureWithNextSeq(item: OutboxItemEntity, cropFile: CropFileEntity?): OutboxItemEntity {
        val seq = (getMaxClientSeqForTask(item.taskId) ?: 0L) + 1L
        val withSeq = item.copy(clientSeq = seq)
        insertCaptureAtomic(withSeq, cropFile)
        return withSeq
    }

    @Query("SELECT * FROM outbox_item WHERE id = :id LIMIT 1")
    suspend fun getItemById(id: String): OutboxItemEntity?

    @Query("SELECT MAX(client_seq) FROM outbox_item WHERE task_id = :taskId")
    suspend fun getMaxClientSeqForTask(taskId: String): Long?

    @Query("SELECT DISTINCT task_id FROM outbox_item WHERE status IN ('QUEUED', 'IN_FLIGHT') ORDER BY created_at ASC")
    suspend fun getActiveTaskIds(): List<String>

    @Query("SELECT * FROM outbox_item WHERE task_id = :taskId AND status IN ('QUEUED', 'IN_FLIGHT') ORDER BY client_seq ASC LIMIT 1")
    suspend fun getNextPendingItemForTask(taskId: String): OutboxItemEntity?

    @Query("SELECT * FROM outbox_item WHERE task_id = :taskId ORDER BY client_seq ASC")
    suspend fun getItemsForTask(taskId: String): List<OutboxItemEntity>

    @Query("SELECT * FROM outbox_item ORDER BY created_at DESC")
    fun observeAllItems(): Flow<List<OutboxItemEntity>>

    @Query("SELECT COUNT(*) FROM outbox_item WHERE status IN ('QUEUED', 'IN_FLIGHT')")
    suspend fun getPendingCount(): Int

    @Query("SELECT COUNT(*) FROM outbox_item")
    suspend fun getTotalItemCount(): Int

    @Query("SELECT COALESCE(SUM(file_size_bytes), 0) FROM crop_file")
    suspend fun getTotalCropSizeBytes(): Long

    @Update
    suspend fun updateItem(item: OutboxItemEntity)

    @Query("UPDATE outbox_item SET status = :status, updated_at = :updatedAt WHERE id = :id")
    suspend fun updateStatus(id: String, status: String, updatedAt: Long = System.currentTimeMillis())

    @Query("UPDATE outbox_item SET status = 'PAUSED', updated_at = :updatedAt WHERE status IN ('QUEUED', 'IN_FLIGHT')")
    suspend fun pauseAllPending(updatedAt: Long = System.currentTimeMillis())

    @Query("UPDATE outbox_item SET status = 'QUEUED', updated_at = :updatedAt WHERE status = 'PAUSED'")
    suspend fun resumeAllPaused(updatedAt: Long = System.currentTimeMillis())

    @Query("SELECT * FROM crop_file WHERE capture_id = :captureId LIMIT 1")
    suspend fun getCropFileForCapture(captureId: String): CropFileEntity?

    @Query("SELECT * FROM crop_file")
    suspend fun getAllCropFiles(): List<CropFileEntity>

    @Query("DELETE FROM crop_file WHERE id = :id")
    suspend fun deleteCropFile(id: String)

    @Query("DELETE FROM outbox_item WHERE id = :id")
    suspend fun deleteItem(id: String)
}
