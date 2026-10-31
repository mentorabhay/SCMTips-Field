package com.scmtips.field.app.session

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.scmtips.field.app.FieldApplication
import com.scmtips.field.app.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * The work session's foreground service (M3 contract §5). It only keeps the app allowed to use the
 * microphone and the glasses link with the phone in a pocket and shows what the session is doing; the
 * session itself lives in FieldController. Types (Android 14+): microphone, plus connectedDevice when
 * Bluetooth access is granted. The notification's Stop ends the session (and the microphone).
 */
class WorkSessionService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(NotificationChannel(CHANNEL, "Work session", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Shows while the work session listens through the glasses"
        })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val controller = (application as FieldApplication).controller
        if (intent?.action == ACTION_STOP) {
            controller.stopWork()
            stopSelf()
            return START_NOT_STICKY
        }
        if (!granted(Manifest.permission.RECORD_AUDIO)) {
            controller.workServiceFailed("Microphone access is off. Allow it for SCMTips Field, then start work again.")
            stopSelf()
            return START_NOT_STICKY
        }
        // The microphone type exists from Android 11; connectedDevice needs Bluetooth access on Android 14+.
        var types = 0
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        if (granted(Manifest.permission.BLUETOOTH_CONNECT)) types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
        try {
            val n = notification(controller.ui.value.work.stateText)
            if (types == 0) startForeground(NOTIFICATION_ID, n) else startForeground(NOTIFICATION_ID, n, types)
        } catch (e: RuntimeException) { // ForegroundServiceStartNotAllowedException, SecurityException
            controller.workServiceFailed("The phone did not allow the work session: ${e.message ?: e.javaClass.simpleName}")
            stopSelf()
            return START_NOT_STICKY
        }
        scope.launch {
            controller.ui.map { it.work.active to it.work.stateText }.distinctUntilChanged().collect { (active, text) ->
                if (!active) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                } else getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION_ID, notification(text))
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun granted(p: String) = ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED

    private fun notification(text: String): Notification {
        val stop = PendingIntent.getService(this, 1, Intent(this, WorkSessionService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("SCMTips Field · work session")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_media_pause, "Stop work", stop)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val CHANNEL = "work_session"
        private const val NOTIFICATION_ID = 3001
        private const val ACTION_STOP = "com.scmtips.field.work.STOP"

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, WorkSessionService::class.java))
        }
    }
}
