import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Owner-only values (A-02): apps/field-android/local.properties is git-ignored.
val localProperties = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.isFile) f.inputStream().use { load(it) }
}

android {
    namespace = "com.scmtips.field.app"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "com.scmtips.field"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        versionCode = 7
        versionName = "0.6.0-m5"
        // Meta Wearables DAT, as Meta's CameraAccess sample: in Developer Mode attestation is off and the
        // values may be empty; a released app needs its Wearables Developer Center ids in local.properties.
        // (Was the literal "0": Android stores a numeric meta-data value as an Integer, and DAT logged
        // "Failed to read metadata from manifest: ...APPLICATION_ID, the app might be misconfigured".)
        manifestPlaceholders["mwdat_application_id"] = localProperties.getProperty("mwdat_application_id", "")
        manifestPlaceholders["mwdat_client_token"] = localProperties.getProperty("mwdat_client_token", "")
        // The sign-in screen's server addresses on a fresh install (M5-H02; SignInDefaults, ServerDefaults): the dev
        // stack on the owner's PC (stand-in core 8011, field-api 8020, through `adb reverse`). Editable on the screen.
        buildConfigField("String", "DEFAULT_CORE_URL", "\"http://127.0.0.1:8011\"")
        buildConfigField("String", "DEFAULT_FIELD_URL", "\"http://127.0.0.1:8020\"")
    }

    // One fixed DEBUG key for every build (CI and PCs alike), so a newer debug APK installs over the
    // older one. Without it each CI runner signed with its own fresh debug key and Android refused the
    // update ("App not installed"). Like Android's own debug.keystore this key is deliberately public
    // (password "android"); it signs only debug builds and guards nothing. Release signing stays out of git (A-02).
    signingConfigs {
        getByName("debug") {
            storeFile = file("debug-signing.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            signingConfig = signingConfigs.getByName("debug")
        }
        // M5-H02: the debug build pointed at the hosted deployment (the SCMTIPS core at api.scmtips.com, field-api at
        // field.scmtips.com). Same application id, signing key and debug manifest as debug, so it installs over the
        // debug APK and behaves the same; only the sign-in screen's default addresses and the version name differ.
        create("hosted") {
            initWith(getByName("debug"))
            signingConfig = signingConfigs.getByName("debug")
            versionNameSuffix = "-hosted"
            matchingFallbacks += listOf("debug") // the library modules have debug and release only
            buildConfigField("String", "DEFAULT_CORE_URL", "\"https://api.scmtips.com\"")
            buildConfigField("String", "DEFAULT_FIELD_URL", "\"https://field.scmtips.com\"")
        }
        release {
            isMinifyEnabled = false
        }
    }
    // The hosted build type shares the debug manifest (plain http only to private LAN addresses, as debug).
    sourceSets.maybeCreate("hosted").manifest.srcFile("src/debug/AndroidManifest.xml")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
    lint {
        // The DAT speech/inputs/photo capabilities are experimental; lint must still pass on our code.
        abortOnError = true
        checkReleaseBuilds = false
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(project(":core-common"))
    implementation(project(":core-voice"))
    implementation(project(":core-wearables"))
    implementation(project(":core-safety")) // HarnessCheck: phrase + tap within 10 s before climb-safe prompts (FR4.041)
    implementation(project(":core-outbox")) // legacy phase-2 managers (auth, consent, pairing) still compile against it
    implementation(project(":feature-decisions")) // M4: core sign-in wire and the approver flow (A-04)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.security.crypto)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.mlkit.barcode.scanning)
    implementation(libs.play.services.code.scanner)

    implementation(libs.mwdat.core)
    implementation(libs.mwdat.camera)
    implementation(libs.mwdat.speech)
    implementation(libs.mwdat.inputs)

    testImplementation(libs.junit4)
    testImplementation(libs.kotlinx.coroutines.android)
}
