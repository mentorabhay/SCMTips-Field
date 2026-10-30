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
    }
}

rootProject.name = "field-android"

include(":app")
include(":core-common")
include(":core-capture")
include(":core-voice")
include(":core-outbox")
include(":core-wearables")
include(":core-wearables-testing")
include(":core-positioning-stub")
include(":feature-tasks")
include(":core-safety")
include(":core-ocr")
include(":core-sitepack")
include(":feature-tower-audit")
include(":feature-exploded")
include(":feature-swap")
