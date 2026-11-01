package com.scmtips.field.app.signin

import com.scmtips.field.app.BuildConfig
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * M5-H02: each build type's sign-in defaults, as app/build.gradle.kts generates them into BuildConfig. Gradle runs this
 * once per variant (testDebugUnitTest, testHostedUnitTest in CI), each against its own BuildConfig. Not in the
 * kotlin_jvm job (jvm-unit.json): BuildConfig exists only in an AGP build.
 */
class BuildVariantDefaultsTest {
    private data class Want(val core: String, val field: String, val hostedVersion: Boolean)

    private val dev = Want("http://127.0.0.1:8011", "http://127.0.0.1:8020", hostedVersion = false)
    private val byBuildType = mapOf(
        "debug" to dev,
        "release" to dev,
        "hosted" to Want("https://api.scmtips.com", "https://field.scmtips.com", hostedVersion = true),
    )

    @Test
    fun thisBuildTypesDefaultsAreItsServers_m5h02() {
        val want = byBuildType[BuildConfig.BUILD_TYPE] ?: throw AssertionError("no expected defaults for build type ${BuildConfig.BUILD_TYPE}")
        assertEquals(want.core, BuildConfig.DEFAULT_CORE_URL)
        assertEquals(want.field, BuildConfig.DEFAULT_FIELD_URL)
        assertEquals(want.hostedVersion, BuildConfig.VERSION_NAME.endsWith("-hosted"))
        // A fresh install's sign-in screen (nothing typed, no QR pairing) offers exactly these two addresses.
        val servers = ServerDefaults(BuildConfig.DEFAULT_CORE_URL, BuildConfig.DEFAULT_FIELD_URL)
        val field = SignInDefaults.fieldUrl(null, null, servers)
        assertEquals(want.field, field)
        assertEquals(want.core, SignInDefaults.coreUrl(null, field, servers))
    }
}
