import java.util.Base64

plugins {
    id("com.android.application")
}

// Release signing: a keystore given by environment variables (see build.sh). Without them the
// release build is signed with the debug key so it still installs for local tests.
val keystoreB64: String? = System.getenv("HARNESS_LINK_KEYSTORE_B64")?.takeIf { it.isNotBlank() }
val keystoreFile = layout.buildDirectory.file("signing/release.keystore").get().asFile

android {
    namespace = "com.harnessmaxxing.link"
    compileSdk = 37
    buildToolsVersion = "37.0.0"

    defaultConfig {
        applicationId = "com.harnessmaxxing.link"
        minSdk = 30
        targetSdk = 37
        versionCode = 2
        versionName = "0.1.1"
    }

    signingConfigs {
        if (keystoreB64 != null) {
            create("release") {
                keystoreFile.parentFile.mkdirs()
                keystoreFile.writeBytes(Base64.getMimeDecoder().decode(keystoreB64))
                storeFile = keystoreFile
                storePassword = System.getenv("HARNESS_LINK_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("HARNESS_LINK_KEY_ALIAS")
                keyPassword = System.getenv("HARNESS_LINK_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (keystoreB64 != null) signingConfigs.getByName("release")
            else signingConfigs.getByName("debug")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf("META-INF/*.version", "META-INF/*.kotlin_module", "kotlin/**", "DebugProbesKt.bin")
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("com.google.android.material:material:1.13.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.1")

    testImplementation("junit:junit:4.13.2")
    // android.jar only has stubs of org.json: the unit tests use the real implementation.
    testImplementation("org.json:json:20260814")
}
