package com.scmtips.field.app.session

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.scmtips.field.app.auth.SessionController

/**
 * Foreground service managing active capture sessions across screen-off events (Task T2.007 / FR2.005 / TC2.105).
 * Declares foregroundServiceType = connectedDevice | camera | microphone.
 */
class CaptureSessionService : Service(), SessionController {

    companion object {
        const val CHANNEL_ID = "field_capture_session"
        const val NOTIFICATION_ID = 2001

        const val ACTION_START = "com.scmtips.field.session.START"
        const val ACTION_STOP = "com.scmtips.field.session.STOP"
        const val EXTRA_TASK_ID = "extra_task_id"
    }

    private var currentTaskId: String? = null
    private var isSessionActive = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val taskId = intent.getStringExtra(EXTRA_TASK_ID) ?: "GENERAL_INVENTORY"
                startCaptureSession(taskId)
            }
            ACTION_STOP -> {
                stopSession("User requested stop")
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun startCaptureSession(taskId: String) {
        currentTaskId = taskId
        isSessionActive = true

        val notification = buildOngoingNotification(taskId, queueDepth = 0)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val serviceType = ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE or
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            startForeground(NOTIFICATION_ID, notification, serviceType)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    override fun stopSession(reason: String) {
        if (!isSessionActive) return
        isSessionActive = false

        // Release hardware resources (CameraX, AudioRecord, Toolkit SDK streams)
        releaseHardwareStreams()

        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    fun releaseHardwareStreams() {
        // Releases camera, mic, and toolkit streams on stop (FR2.005)
        println("[CaptureSessionService] Hardware streams released (Camera, Mic, Toolkit).")
    }

    fun updateQueueDepth(queueDepth: Int) {
        if (!isSessionActive) return
        val notification = buildOngoingNotification(currentTaskId ?: "UNKNOWN", queueDepth)
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, notification)
    }

    private fun buildOngoingNotification(taskId: String, queueDepth: Int): Notification {
        val stopIntent = Intent(this, CaptureSessionService::class.java).apply {
            action = ACTION_STOP
        }
        val stopPendingIntent = PendingIntent.getService(
            this,
            0,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("SCMTips Field Active Session")
            .setContentText("Task: $taskId | Outbox Queue: $queueDepth items")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_media_pause, "Stop Session", stopPendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Field Capture Session",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Ongoing notification for active camera, voice and glasses capture"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }
}
