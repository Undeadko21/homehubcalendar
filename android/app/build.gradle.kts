import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // Снимки макетов без телефона: ./gradlew recordPaparazziDebug → app/src/test/snapshots
    id("app.cash.paparazzi")
}

// Версия приложения — в android/version.properties (увеличивать при каждом выпуске).
val versionProps = Properties().apply { load(rootProject.file("version.properties").inputStream()) }

android {
    namespace = "ru.homehub.calendar"
    compileSdk = 35

    defaultConfig {
        applicationId = "ru.homehub.calendar"
        minSdk = 26
        targetSdk = 35
        versionCode = versionProps.getProperty("versionCode").toInt()
        versionName = versionProps.getProperty("versionName")
    }

    // Постоянный ключ подписи лежит в репозитории, чтобы обновления ставились поверх
    // старой версии из любой сборки. Приложение семейное и ставится вручную, поэтому так допустимо.
    signingConfigs {
        create("release") {
            storeFile = rootProject.file("keystore/homehub-release.jks")
            storePassword = "homehub-calendar"
            keyAlias = "homehub"
            keyPassword = "homehub-calendar"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { buildConfig = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    testImplementation("junit:junit:4.13.2")
}
