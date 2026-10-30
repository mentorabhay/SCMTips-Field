package com.scmtips.field.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

/** Field test without adb: a crash is kept for the next launch, and cleared once dismissed. */
class CrashLogTest {
    @Test
    fun recordedCrashIsReadBackWithTraceAndDevice() {
        val dir = Files.createTempDirectory("crash").toFile()
        val log = CrashLog(dir.resolve("sub/last-crash.txt"))
        assertNull(log.read())
        log.record("main", IllegalStateException("Wearables not initialised"), "0.1.0", "Pixel 8, Android 16")
        val text = log.read()!!
        assertTrue(text.startsWith("SCMTips Field 0.1.0 on Pixel 8, Android 16\nthread: main\n"))
        assertTrue(text.contains("java.lang.IllegalStateException: Wearables not initialised"))
        assertTrue(text.contains("at com.scmtips.field.app.CrashLogTest"))
        log.clear()
        assertNull(log.read())
    }

    @Test
    fun installedHandlerRecordsThenDelegates() {
        val dir = Files.createTempDirectory("crash").toFile()
        val log = CrashLog(dir.resolve("last-crash.txt"))
        val original = Thread.getDefaultUncaughtExceptionHandler()
        var delegated: Throwable? = null
        try {
            Thread.setDefaultUncaughtExceptionHandler { _, e -> delegated = e }
            CrashLog.install(log, "0.1.0", "test")
            val boom = RuntimeException("boom")
            Thread.getDefaultUncaughtExceptionHandler()!!.uncaughtException(Thread.currentThread(), boom)
            assertEquals(boom, delegated)
            assertTrue(log.read()!!.contains("java.lang.RuntimeException: boom"))
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(original)
        }
    }
}
