pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven { url = java.net.URI("https://jitpack.io") }
    }
}

rootProject.name = "field-android"

include(":app")
include(":core-capture")
include(":core-voice")
include(":core-outbox")
include(":core-wearables")
include(":core-positioning-stub")
include(":feature-tasks")
