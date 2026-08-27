# Aveline iOS 项目设置指南

## 在 Xcode 中创建项目

### 步骤 1: 创建新项目

1. 打开 Xcode
2. 选择 **File** > **New** > **Project...**
3. 选择 **iOS** > **App**
4. 点击 **Next**

### 步骤 2: 配置项目

填写以下信息：

- **Product Name**: `Aveline`
- **Team**: 选择你的开发团队（或个人）
- **Organization Identifier**: `com.aveline`
- **Interface**: `SwiftUI`
- **Language**: `Swift`
- **Minimum Deployment**: `iOS 17.0`

取消勾选：
- ☐ Use Core Data
- ☐ Include Tests（可选，如果需要测试则勾选）

### 步骤 3: 保存项目

选择保存位置为：
```
d:\AI\xiaoyou-core\clients\frontend\aveline-ios\
```

项目名称会自动创建 `Aveline.xcodeproj` 文件。

### 步骤 4: 添加源文件

1. 在 Finder 中打开 `Aveline/` 文件夹
2. 将整个 `Aveline/` 文件夹拖入 Xcode 的项目导航器
3. 在弹出的对话框中：
   - 勾选 **Copy items if needed**
   - 选择 **Create folder references**（重要！）
   - 确保勾选你的 target

### 步骤 5: 配置项目设置

在 Xcode 中选择项目根节点，然后：

#### General 标签

- **Display Name**: `Aveline`
- **Bundle Identifier**: `com.aveline.ai`
- **Version**: `1.0`
- **Build**: `1`
- **Deployment Info**: 
  - iPhone: ✓
  - iPad: ✓（可选）
  - Minimum Deployments: iOS 17.0

#### Signing & Capabilities 标签

- 勾选 **Automatically manage signing**
- 选择你的 Team
- Bundle Identifier 会自动更新

#### Build Settings 标签

搜索并设置：

- **Swift Compiler - Language**:
  - Swift Language Version: `Swift 5.9`
  
- **Deployment**:
  - iOS Deployment Target: `iOS 17.0`

### 步骤 6: 清理默认文件

Xcode 会自动生成一些文件，你可以删除或替换：

- `ContentView.swift` - 已被我们的视图替代
- `AvelineApp.swift` - 已被我们的应用入口替代

### 步骤 7: 构建和运行

1. 选择目标设备（模拟器或真机）
2. 点击 **Run** 按钮或按 `⌘R`
3. 等待构建完成

## 常见问题

### Q: 编译错误 "No such module"

**A**: 确保所有文件都已正确添加到 target 中：
1. 选择文件
2. 打开 File Inspector（右侧面板）
3. 在 **Target Membership** 中勾选你的 target

### Q: 运行后显示空白屏幕

**A**: 检查：
1. `AvelineApp.swift` 是否正确设置为 `@main`
2. 所有视图文件是否都已添加
3. 是否有编译错误

### Q: 无法连接后端

**A**: 
1. 在应用中打开 Settings
2. 设置正确的 Backend URL
3. 确保后端服务正在运行

## 可选配置

### 添加应用图标

1. 准备图标文件（1024x1024 PNG）
2. 在 Xcode 中打开 `Assets.xcassets`
3. 找到 `AppIcon`
4. 拖入图标文件

### 添加启动屏幕

1. 打开 `Assets.xcassets`
2. 添加启动屏幕图片
3. 在 General > App Icons and Launch Screen 中配置

### 配置深色模式

项目已支持深色模式，颜色会在 `Assets.xcassets` 中配置。

## 下一步

项目已经可以运行，你可以：

1. 完善占位视图（Study, Shop, Persona）
2. 添加更多功能（TTS、文件上传等）
3. 实现本地数据库（CoreData）
4. 添加单元测试
5. 配置 CI/CD

## 技术支持

如有问题，请参考：
- [SwiftUI 官方文档](https://developer.apple.com/xcode/swiftui/)
- [Swift Concurrency 指南](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/)
- 项目 README.md
