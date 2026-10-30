package com.scmtips.field.app

import android.app.Application
import android.os.Build
import android.util.Log
import com.meta.wearable.dat.core.Wearables
import java.io.File

/** Holds the single [FieldController] for the process (no DI framework needed). */
class FieldApplication : Application() {
    val crashLog: CrashLog by lazy { CrashLog(File(filesDir, "last-crash.txt")) }

    /** Null until [onCreate] tried; the message when the glasses toolkit could not start. */
    @Volatile var datInitError: String? = null
        private set

    val controller: FieldController by lazy { FieldController(this) { datInitError } }

    override fun onCreate() {
        super.onCreate()
        CrashLog.install(crashLog, BuildConfig.VERSION_NAME, "${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}")
        // Meta DAT: initialize once, before ANY other SDK call (handleIntent, registrationState, ...).
        // It used to run only after the Bluetooth permission dialog, while MainActivity.onCreate had
        // already called Wearables.handleIntent - the app closed immediately on first launch.
        runCatching {
            Wearables.initialize(this).onFailure { e, _ -> datInitError = e.description }
        }.onFailure { e ->
            datInitError = e.message ?: e.javaClass.simpleName
            Log.e("SCMTipsField", "Wearables.initialize failed", e)
        }
    }
}
