package com.scmtips.field.feature.tasks

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.core.outbox.QueueCapacityGovernor
import com.scmtips.field.core.outbox.db.OutboxItemEntity
import com.scmtips.field.core.outbox.db.OutboxStatus

data class OutboxScreenUiState(
    val items: List<OutboxItemEntity> = emptyList(),
    val totalCropSizeBytes: Long = 0L,
    val capacityStatus: QueueCapacityGovernor.CapacityStatus = QueueCapacityGovernor.CapacityStatus.Normal,
    val isSyncing: Boolean = false
)

/**
 * SCR2.06: Outbox queue inspector and manual sync trigger (Task T2.043 / FR2.042).
 * Displays queued, in-flight, acked, and failed captures per task with retry actions.
 */
@Composable
fun OutboxScreen(
    state: OutboxScreenUiState,
    onSyncNow: () -> Unit,
    onResumePaused: () -> Unit,
    modifier: Modifier = Modifier
) {
    val pendingCount = state.items.count {
        it.status == OutboxStatus.QUEUED.name || it.status == OutboxStatus.IN_FLIGHT.name
    }
    val groupedByTask = state.items.groupBy { it.taskId }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Color(0xFF121417))
            .padding(16.dp)
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "Outbox Queue",
                    color = Color.White,
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "$pendingCount pending · ${(state.totalCropSizeBytes / 1024) / 1024} MB / 200 MB",
                    color = Color(0xFF9E9E9E),
                    fontSize = 13.sp
                )
            }

            Row {
                OutlinedButton(
                    onClick = onResumePaused,
                    modifier = Modifier.padding(end = 8.dp)
                ) {
                    Text("Resume All", color = Color.White, fontSize = 12.sp)
                }
                Button(
                    onClick = onSyncNow,
                    enabled = !state.isSyncing,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2563EB))
                ) {
                    Text(if (state.isSyncing) "Syncing..." else "Sync Now", fontSize = 12.sp)
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Capacity Warnings / Banners
        when (val cap = state.capacityStatus) {
            is QueueCapacityGovernor.CapacityStatus.Warning -> {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF3E2723)),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
                ) {
                    Text(
                        text = cap.message,
                        color = Color(0xFFFFB74D),
                        fontSize = 13.sp,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }
            is QueueCapacityGovernor.CapacityStatus.Refused -> {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF4A148C)),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
                ) {
                    Text(
                        text = cap.message,
                        color = Color(0xFFEF5350),
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }
            QueueCapacityGovernor.CapacityStatus.Normal -> Unit
        }

        if (state.items.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Text("Outbox is empty. All captures are uploaded.", color = Color(0xFF757575))
            }
        } else {
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize()
            ) {
                groupedByTask.forEach { (taskId, taskItems) ->
                    item {
                        Text(
                            text = "Task: $taskId (${taskItems.size} items)",
                            color = Color(0xFF64B5F6),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
                        )
                    }

                    items(taskItems, key = { it.id }) { item ->
                        OutboxItemCard(item)
                    }
                }
            }
        }
    }
}

@Composable
fun OutboxItemCard(item: OutboxItemEntity) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E2228)),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "#${item.clientSeq} · ${item.payloadType}",
                    color = Color.White,
                    fontWeight = FontWeight.Medium,
                    fontSize = 14.sp
                )
                StatusBadge(item.status)
            }

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "Key: ${item.id}",
                color = Color(0xFF888888),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )

            if (item.attempts > 0) {
                Text(
                    text = "Attempts: ${item.attempts}",
                    color = Color(0xFFB0BEC5),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(top = 2.dp)
                )
            }

            if (!item.lastError.isNullOrBlank()) {
                Text(
                    text = "Error: ${item.lastError}",
                    color = Color(0xFFE57373),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
        }
    }
}

@Composable
fun StatusBadge(status: String) {
    val (bg, fg) = when (status) {
        OutboxStatus.ACKED.name -> Pair(Color(0xFF1B5E20), Color(0xFF81C784))
        OutboxStatus.DUPLICATE_ACKED.name -> Pair(Color(0xFF004D40), Color(0xFF80CBC4))
        OutboxStatus.IN_FLIGHT.name -> Pair(Color(0xFF0D47A1), Color(0xFF64B5F6))
        OutboxStatus.QUEUED.name -> Pair(Color(0xFF37474F), Color(0xFFECEFF1))
        OutboxStatus.PAUSED.name -> Pair(Color(0xFF4A148C), Color(0xFFCE93D8))
        OutboxStatus.QUARANTINED.name -> Pair(Color(0xFFBF360C), Color(0xFFFFAB91))
        OutboxStatus.REJECTED.name -> Pair(Color(0xFFB71C1C), Color(0xFFEF9A9A))
        else -> Pair(Color.DarkGray, Color.White)
    }

    Box(
        modifier = Modifier
            .background(bg, shape = RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp)
    ) {
        Text(text = status, color = fg, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}
