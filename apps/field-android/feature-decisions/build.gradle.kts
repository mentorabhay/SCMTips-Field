plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

// M4 stream B (A-04): the executive approver flow, ported from the SCMTIPS core's wearable app onto
// Field's own modules: speech out through core-wearables' AudioOut, speech in as core-voice candidates.
android {
    namespace = "com.scmtips.field.feature.decisions"
    compileSdk = libs.versions.compileSdk.get().toInt()
    defaultConfig { minSdk = libs.versions.minSdk.get().toInt() }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    api(project(":core-wearables"))
    api(project(":core-voice"))
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    testImplementation(libs.junit4)
    testImplementation(libs.kotlinx.coroutines.android)
}
