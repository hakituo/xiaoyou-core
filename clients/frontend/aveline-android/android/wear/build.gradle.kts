plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.aveline.ai.wear"
    compileSdk = 35

    // Wear OS 4+ (API 33+) 内置 Health Connect,不需要在设备上单独安装
    // compileSdk 35 确保 Health Connect API 可用

    defaultConfig {
        // Wear OS 应用通常与手机端共用同一个 applicationId,
        // 这样系统才会将其识别为同一套应用的 Wear 组件,Data Layer 才能互通。
        applicationId = "com.aveline.ai"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.7.3")

    // Wearable Data Layer: 手表与手机通信
    implementation("com.google.android.gms:play-services-wearable:18.2.0")

    // Health Services: 统一读取 Wear OS 传感器数据(心率/步数等)
    implementation("androidx.health:health-services-client:1.0.0-rc02")

    // Health Connect: 读取睡眠/体重/身体成分等历史数据(纯 IO)
    implementation("androidx.health.connect:connect-client:1.1.0-alpha02")

    // Guava: Health Services 返回 ListenableFuture,需要显式引入
    implementation("com.google.guava:guava:32.1.3-android")

    // 生命周期支持
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-service:2.7.0")
}
