# Aveline iOS

Aveline AI Assistant 的 iOS 原生应用，使用 Swift 和 SwiftUI 构建。

## 技术栈

- **语言**: Swift 5.9+
- **UI 框架**: SwiftUI
- **最低支持**: iOS 17.0
- **架构**: MVVM (Model-View-ViewModel)
- **网络**: URLSession + async/await
- **数据序列化**: Codable
- **本地存储**: UserDefaults

## 项目结构

```
Aveline/
├── App/                    # 应用入口
│   └── AvelineApp.swift
├── Core/                   # 核心服务层
│   ├── Network/           # 网络层
│   │   ├── AvelineAPIService.swift
│   │   └── WebSocketManager.swift
│   ├── Storage/           # 数据存储
│   │   └── AppPreferences.swift
│   └── DI/                # 依赖注入
│       └── DependencyContainer.swift
├── Models/                 # 数据模型
│   ├── MessageModels.swift
│   ├── SessionModels.swift
│   ├── MemoryModels.swift
│   ├── PersonaModels.swift
│   ├── ShopModels.swift
│   ├── StudyModels.swift
│   └── LifeStatusModels.swift
├── ViewModels/            # 视图模型
│   ├── MainViewModel.swift
│   ├── ChatViewModel.swift
│   ├── MemoryViewModel.swift
│   └── SettingsViewModel.swift
├── Views/                 # 视图层
│   ├── Main/
│   │   └── NavigationDrawer.swift
│   ├── Chat/
│   │   └── ChatView.swift
│   ├── Memory/
│   │   └── MemoryView.swift
│   ├── Study/
│   │   └── StudyView.swift
│   ├── Shop/
│   │   └── ShopView.swift
│   ├── Persona/
│   │   └── PersonaView.swift
│   ├── Settings/
│   │   └── SettingsView.swift
│   └── Components/
│       ├── BreathingBackground.swift
│       └── ConnectionStateBadge.swift
├── Theme/                 # 主题系统
│   ├── AppColors.swift
│   └── EmotionColors.swift
└── Utilities/             # 工具类
    ├── Extensions/
    └── Helpers/
```

## 功能特性

### 已实现

- ✅ 聊天功能（发送/接收消息）
- ✅ 会话管理（创建/切换/删除）
- ✅ 记忆浏览和管理
- ✅ WebSocket 实时通信
- ✅ 情感颜色主题系统
- ✅ 呼吸背景动画
- ✅ 侧边抽屉导航
- ✅ 设置页面（后端 URL、Token）
- ✅ 依赖注入容器

### 待完善

- ⏳ 学习模式完整功能
- ⏳ 商店完整功能
- ⏳ 角色管理完整功能
- ⏳ 文件上传功能
- ⏳ TTS 语音播放
- ⏳ 图片生成和视觉分析
- ⏳ 本地数据库（CoreData）
- ⏳ 推送通知

## 如何在 Xcode 中打开

1. **创建 Xcode 项目**
   ```bash
   # 在 Xcode 中创建新项目
   - 选择 "iOS" -> "App"
   - Interface: SwiftUI
   - Language: Swift
   - Bundle Identifier: com.aveline.ai
   - Minimum Deployment: iOS 17.0
   ```

2. **添加源文件**
   - 将 `Aveline/` 目录拖入 Xcode 项目
   - 选择 "Create folder references"
   - 确保所有文件都添加到 target

3. **配置签名**
   - 在 Xcode 中选择你的开发团队
   - 配置签名证书

4. **运行项目**
   - 选择模拟器或连接的 iOS 设备
   - 点击 Run (⌘R)

## 配置后端

在应用中打开 Settings 页面，配置：

- **Backend URL**: 你的 Aveline 后端地址（例如：`http://localhost:8000`）
- **Access Token**: 认证令牌（如果需要）

## 与 Android 端的对应关系

| iOS 文件 | Android 对应文件 |
|---------|----------------|
| `AvelineAPIService.swift` | `AvelineApiService.kt` |
| `WebSocketManager.swift` | `WebSocketManager.kt` |
| `AppPreferences.swift` | `AppPreferences.kt` |
| `DependencyContainer.swift` | Hilt DI Modules |
| `MainViewModel.swift` | `MainViewModel.kt` |
| `ChatViewModel.swift` | `ChatViewModel.kt` |
| `NavigationDrawer.swift` | `ModalNavigationDrawer` (Compose) |
| `BreathingBackground.swift` | `BreathingBackground.kt` |

## API 端点

所有 API 端点与 Android 端完全一致，详见后端 API 文档。

## 开发注意事项

1. **线程安全**: 所有 ViewModel 使用 `@MainActor` 确保在主线程更新 UI
2. **错误处理**: 使用 Swift 的 `async/throws` 进行异步错误处理
3. **状态管理**: 使用 `@Published` 和 `ObservableObject` 实现响应式状态
4. **内存管理**: 使用 `[weak self]` 避免循环引用

## 构建要求

- Xcode 15.0+
- Swift 5.9+
- macOS 14.0+ (Sonoma)
- iOS 17.0+ (运行时)

## 许可证

与主项目保持一致
