package com.scmtips.field.core.outbox

import com.scmtips.field.core.outbox.crypto.CropEncryptedStorage
import com.scmtips.field.core.outbox.db.CropFileEntity
import com.scmtips.field.core.outbox.db.OutboxDao
import com.scmtips.field.core.outbox.db.OutboxItemEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.util.UUID

/**
 * OutboxWriter against FR2.039 (UUIDv7 key at shutter), FR2.044 (crop fsynced before the row; crash
 * leaves a complete item or none) and FR2.042 (refusal leaves the queue unchanged).
 *
 * Uses an in-memory OutboxDao test double; it runs under Gradle (needs androidx.room on the compile
 * classpath) and is excluded from the local kotlin-jvm job. Room's real transaction and SQLCipher are
 * not exercised here (instrumented test still to write).
 */
class OutboxPropertyTest {

    private class MemoryDao : OutboxDao {
        val items = linkedMapOf<String, OutboxItemEntity>()
        val crops = linkedMapOf<String, CropFileEntity>()
        override suspend fun insertItem(item: OutboxItemEntity) {
            check(items.values.none { it.taskId == item.taskId && it.clientSeq == item.clientSeq }) { "unique (task_id, client_seq)" }
            check(items.putIfAbsent(item.id, item) == null) { "duplicate id" }
        }
        override suspend fun insertCropFile(cropFile: CropFileEntity) { crops[cropFile.id] = cropFile }
        override suspend fun getItemById(id: String) = items[id]
        override suspend fun getMaxClientSeqForTask(taskId: String) = items.values.filter { it.taskId == taskId }.maxOfOrNull { it.clientSeq }
        override suspend fun getActiveTaskIds() = items.values.map { it.taskId }.distinct()
        override suspend fun getNextPendingItemForTask(taskId: String) = items.values.filter { it.taskId == taskId }.minByOrNull { it.clientSeq }
        override suspend fun getItemsForTask(taskId: String) = items.values.filter { it.taskId == taskId }.sortedBy { it.clientSeq }
        override fun observeAllItems(): Flow<List<OutboxItemEntity>> = flowOf(items.values.toList())
        override suspend fun getPendingCount() = items.size
        override suspend fun getTotalItemCount() = items.size
        override suspend fun getTotalCropSizeBytes() = crops.values.sumOf { it.fileSizeBytes }
        override suspend fun updateItem(item: OutboxItemEntity) { items[item.id] = item }
        override suspend fun updateStatus(id: String, status: String, updatedAt: Long) { items[id] = items.getValue(id).copy(status = status) }
        override suspend fun pauseAllPending(updatedAt: Long) {}
        override suspend fun resumeAllPaused(updatedAt: Long) {}
        override suspend fun getCropFileForCapture(captureId: String) = crops.values.firstOrNull { it.captureId == captureId }
        override suspend fun getAllCropFiles() = crops.values.toList()
        override suspend fun deleteCropFile(id: String) { crops.remove(id) }
        override suspend fun deleteItem(id: String) { items.remove(id) }
    }

    private val dir = Files.createTempDirectory("outbox").toFile()
    private val storage = CropEncryptedStorage(dir) { ByteArray(32) { 3 } }

    @Test
    fun fr2_039_eachCaptureGetsAUuidV7KeyAndAPerTaskSeq() = runBlocking {
        val dao = MemoryDao()
        val w = OutboxWriter(dao, storage, dir)
        val a1 = w.commitCapture("A", "CAPTURE", "{}", null)
        val b1 = w.commitCapture("B", "CAPTURE", "{}", null)
        val a2 = w.commitCapture("A", "CAPTURE", "{}", byteArrayOf(1, 2, 3))
        assertEquals(listOf(1L, 1L, 2L), listOf(a1.clientSeq, b1.clientSeq, a2.clientSeq))
        listOf(a1, b1, a2).forEach { assertEquals(7, UUID.fromString(it.id).version()) }
        assertEquals(dao.items.keys.toList(), dao.items.keys.sorted())
        val crop = dao.getCropFileForCapture(a2.id)!!
        assertArrayEquals(byteArrayOf(1, 2, 3), storage.readDecryptedCrop(java.io.File(crop.filePath)))
    }

    @Test
    fun fr2_044_crashBeforeCommitLeavesNoRowAndTheOrphanCropIsSweptAfter10Min() = runBlocking {
        val dao = MemoryDao()
        val w = OutboxWriter(dao, storage, dir)
        runCatching {
            w.commitCapture("A", "CAPTURE", "{}", byteArrayOf(9), faultInjectionPoint = { if (it == "BEFORE_DB_TRANSACTION") error("killed") })
        }
        assertTrue(dao.items.isEmpty())
        assertEquals(1, dir.listFiles()!!.size)
        assertEquals(0, w.sweepOrphanCrops(now = System.currentTimeMillis() + 5 * 60_000))
        assertEquals(1, w.sweepOrphanCrops(now = System.currentTimeMillis() + 11 * 60_000))
        w.commitCapture("A", "CAPTURE", "{}", byteArrayOf(8))
        assertEquals("a committed crop is never swept", 0, w.sweepOrphanCrops(now = System.currentTimeMillis() + 60 * 60_000))
    }

    @Test
    fun tc2_053_fullOutboxRefusesWithoutTouchingQueuedItems() = runBlocking {
        val dao = MemoryDao()
        val w = OutboxWriter(dao, storage, dir, QueueCapacityGovernor(dao.capacityStats(), maxItems = 3))
        repeat(3) { w.commitCapture("A", "CAPTURE", "{}", null) }
        val before = dao.items.toMap()
        val err = runCatching { w.commitCapture("A", "CAPTURE", "{}", null) }.exceptionOrNull()
        assertEquals(QueueCapacityGovernor.REFUSAL_MSG, err?.message)
        assertEquals(before, dao.items.toMap())
    }
}
