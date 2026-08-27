# Aveline Native Android Module

This module contains the native Android implementation of the Aveline AI Assistant app using Kotlin and Jetpack Compose.

## Package Structure

```
com.aveline.ai.native/
├── presentation/     # UI layer (Compose screens, ViewModels, UI components)
│   ├── chat/         # Chat screen and ViewModel
│   ├── components/   # Reusable UI components
│   ├── navigation/   # Navigation graph
│   ├── theme/        # Theme, colors, typography
│   ├── utils/        # UI utilities
│   └── MainActivity.kt  # Main entry point (LAUNCHER)
├── domain/           # Business logic layer (models, use cases, repository interfaces)
├── data/             # Data layer (API services, database, repository implementations)
├── services/         # Background services (TTS, voice input, file upload)
├── di/               # Dependency injection modules (Hilt)
├── legacy/           # Deprecated legacy code (will be removed)
└── README.md         # This file
```

## Architecture

The app follows MVVM (Model-View-ViewModel) architecture with:
- **Presentation Layer**: Jetpack Compose UI + ViewModels
- **Domain Layer**: Business logic and repository interfaces
- **Data Layer**: Network (Retrofit + OkHttp), Local storage (Room + SharedPreferences)
- **Dependency Injection**: Hilt

## Key Technologies

- **Language**: Kotlin 1.9.20
- **UI Framework**: Jetpack Compose (BOM 2023.10.01)
- **DI**: Hilt 2.48.1
- **Networking**: OkHttp 4.12.0 + Retrofit 2.9.0
- **Database**: Room 2.6.1
- **Serialization**: Kotlin Serialization 1.6.0
- **Async**: Kotlin Coroutines + Flow
- **Health**: Health Connect SDK
- **Image Loading**: Coil
- **Min SDK**: 26 (Android 8.0)
- **Target SDK**: 34 (Android 14)

## Entry Points

| Activity | Package | Purpose |
|----------|---------|---------|
| `MainActivity` | `com.aveline.ai.native.presentation` | **Main LAUNCHER entry** - Full architecture version |
| `MainActivity` | `com.aveline.ai` (root) | Capacitor WebView entry (legacy) |
| `NativeMobileActivity` | `com.aveline.ai.native.legacy` | Deprecated transition version |

## Separation from Capacitor

This native implementation is completely separate from the existing Capacitor-based WebView implementation:

| Layer | Capacitor (Root Package) | Native (native/ Package) |
|-------|--------------------------|--------------------------|
| Entry | `com.aveline.ai.MainActivity` | `com.aveline.ai.native.presentation.MainActivity` |
| UI | WebView + HTML/CSS/JS | Jetpack Compose |
| DI | None | Hilt |
| Architecture | Hybrid | MVVM + Clean Architecture |

## Development Status

Currently implementing Phase 2: Core Features
- [x] Project structure setup
- [x] Build configuration
- [x] Dependency injection
- [x] Network layer
- [x] Local storage
- [x] Repository layer
- [x] Chat UI
- [x] WebSocket integration
- [x] TTS/STT support
- [x] File upload
- [ ] Health Connect integration
- [ ] Settings screen
