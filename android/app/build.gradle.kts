plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val signingInputs = listOf(
    "ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD",
).associateWith { providers.environmentVariable(it) }
val releaseVersion = providers.environmentVariable("ANDROID_RELEASE_VERSION")

android {
    namespace = "com.dojo.aisomedo"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.dojo.aisomedo"
        minSdk = 29
        targetSdk = 35
        versionCode = 4
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            storeFile = signingInputs.getValue("ANDROID_KEYSTORE_PATH").orNull?.let { file(it) }
            storePassword = signingInputs.getValue("ANDROID_KEYSTORE_PASSWORD").orNull
            keyAlias = signingInputs.getValue("ANDROID_KEY_ALIAS").orNull
            keyPassword = signingInputs.getValue("ANDROID_KEY_PASSWORD").orNull
        }
    }
    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

val validateReleaseInputs = tasks.register("validateReleaseInputs") {
    doLast {
        val missing = signingInputs.filterValues { it.orNull.isNullOrBlank() }.keys
        check(missing.isEmpty()) { "Missing release signing inputs: ${missing.joinToString()}" }
        check(file(signingInputs.getValue("ANDROID_KEYSTORE_PATH").get()).isFile) {
            "Release keystore file does not exist"
        }
        check(!releaseVersion.isPresent || releaseVersion.get() == android.defaultConfig.versionName) {
            "Release tag must match versionName"
        }
    }
}
tasks.configureEach {
    if (name.contains("Release") && name != "validateReleaseInputs") {
        dependsOn(validateReleaseInputs)
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    testImplementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-savedstate:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
