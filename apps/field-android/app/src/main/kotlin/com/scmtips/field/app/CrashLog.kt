package com.scmtips.field.app

import java.io.File
import java.io.PrintWriter
import java.io.StringWriter

/**
 * Last-crash record (field test without adb): the uncaught-exception handler writes the stack trace to
 * a file, and the next launch shows it on screen with a Copy button instead of starting normally.
 * Pure file logic so it is unit-tested on the JVM; [install] wires it into the process.
 */
class CrashLog(private val file: File) {

    fun record(thread: String, error: Throwable, appVersion: String, device: String) {
        val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
        runCatching {
            file.parentFile?.mkdirs()
            file.writeText("SCMTips Field $appVersion on $device\nthread: $thread\n\n$trace")
        }
    }

    /** The recorded crash, or null. */
    fun read(): String? = if (file.isFile) runCatching { file.readText() }.getOrNull()?.takeIf { it.isNotBlank() } else null

    fun clear() {
        runCatching { file.delete() }
    }

    companion object {
        /** Record any uncaught exception, then let the platform handler end the process as usual. */
        fun install(log: CrashLog, appVersion: String, device: String) {
            val previous = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { t, e ->
                log.record(t.name, e, appVersion, device)
                previous?.uncaughtException(t, e)
            }
        }
    }
}
