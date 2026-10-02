# 01 - 项目结构与构建配置

## 概览

- **项目名称**: Aveline Android
- **语言**: Kotlin 1.9.20 + Java (legacy)
- **UI 框架**: Jetpack Compose (BOM 2024.02.02)
- **构建系统**: Gradle Kotlin DSL
- **最低 SDK**: 26 (Android 8.0)
- **目标 SDK**: 35
- **JVM 目标**: 17
- **源文件总数**: 177 (120+ .kt + Java + XML)

## 目录结构

```
aveline-android/
├── android/                        # Android 项目根目录
│   ├── app/
│   │   ├── build.gradle.kts        # 应用级构建配置
│   │   └── src/
│   │       └── main/java/com/aveline/ai/
│   │           ├── AvelineApplication.kt    # Application 类
│   │           ├── HealthManager.kt         # Health Connect 管理器
│   │           ├── MainActivity.java        # Capacitor WebView 入口 (legacy)
│   │           └── mobile/                  # 主代码
│   │               ├── data/               # 数据层
│   │               ├── di/                 # 依赖注入
│   │               ├── domain/             # 领域层
│   │               ├── presentation/       # UI 层
│   │               ├── services/           # 服务层
│   │               └── utils/              # 工具类
│   ├── build.gradle.kts            # 项目级构建配置
│   ├── gradle.properties
│   ├── settings.gradle.kts
│   └── local.properties
└── README.md
```

## 架构: MVVM + Clean Architecture

```
Presentation Layer (UI)
    ├── Jetpack Compose Screens (10 routes)
    ├── ViewModels (Hilt-injected)
    └── Components (reusable UI pieces)

Domain Layer (Business Logic)
    ├── Models (纯 Kotlin data classes)
    └── Repository Interfaces (abstractions)

Data Layer (Implementation)
    ├── Remote: Retrofit + OkHttp + WebSocket
    ├── Local: Room Database + SharedPreferences
    └── Repository Implementations
```

## 核心依赖

| 类别 | 依赖 | 版本 | 用途 |
|------|------|------|------|
| UI | Jetpack Compose BOM | 2024.02.02 | UI 框架 |
| DI | Hilt | 2.48.1 | 依赖注入 |
| 数据库 | Room | 2.6.1 | 本地存储 |
| 网络 | Retrofit + OkHttp | 2.9.0 / 4.12.0 | REST API |
| 序列化 | kotlinx-serialization | 1.6.0 | JSON |
| 安全 | security-crypto | 1.1.0-alpha06 | 加密偏好 |
| 图片 | Coil | 2.5.0 | 图片加载 |
| 健康 | Health Connect | 1.1.0-alpha07 | 健康数据 |
| 推送 | Firebase Messaging | BOM 33.1.2 | FCM |
| 后台 | WorkManager | 2.9.0 | 周期同步 |
| 位置 | Play Services Location | 21.2.0 | GPS 定位 |
| 测试 | JUnit + MockK + Kotest | - | 单元测试 |

## 构建特性

- **Debug**: minify=false, applicationId 后缀 `.debug`
- **Release**: minify=true, shrinkResources=true
- **Compose Compiler**: 1.5.8
- **资源语言**: 仅 zh + en
- **打包排除**: META-INF 冲突文件, dependenciesInfo

## 构建优化点

1. **ProGuard 已配置**: Release 包开启混淆和资源压缩
2. **dependenciesInfo 排除**: APK/Bundle 不含依赖元数据，减小体积
3. **资源语言限制**: 只保留中文和英文，减少 APK 体积
4. **动态域名拦截器**: Retrofit 使用占位 base URL，真实地址通过 Interceptor 动态注入（见 NetworkModule）
