# 小友移动端 (Xiaoyou Android) 技术架构与开发参考手册

**版本**: 1.0.0
**最后更新**: 2025-12-08
**状态**: 规划中

---

## 1. 项目概述 (Project Overview)

**Xiaoyou Android** 是小友智能 Agent 的移动端触点，作为一个“伴随式”应用运行在 Android 设备上。它不仅提供传统的对话界面，还通过 Android 无障碍服务 (AccessibilityService) 和 悬浮窗 (Overlay) 技术，实现对用户当前屏幕内容的实时感知与主动关怀。

### 1.1 核心特性
*   **全系统伴随**: 通过悬浮窗实时显示 Agent 状态 (Idle/Analyzing/Danger)。
*   **主动感知**: 利用无障碍服务监听物理按键 (如长按音量下键) 触发屏幕分析。
*   **隐私安全**: 屏幕截图仅在用户主动触发或特定高危场景下进行，并在本地或加密通道处理。
*   **多模态交互**: 支持文本对话、语音播报 (TTS) 和视觉反馈。

### 1.2 技术栈
*   **开发语言**: Kotlin
*   **最低版本**: Android 8.0 (API 26)
*   **核心组件**: AccessibilityService, WindowManager, MediaProjection
*   **网络通信**: OkHttp (REST API) + Kotlin Coroutines (异步并发)
*   **UI 架构**: View-based (逐步迁移至 Jetpack Compose)

---

## 2. 系统架构 (System Architecture)

参照核心后端架构，Android 端采用分层架构设计，确保 UI、业务逻辑与底层能力的解耦。

### 2.1 架构分层

```mermaid
graph TD
    User[用户] -->|交互| AccessLayer
    
    subgraph AccessLayer [接入层 (UI/Interaction)]
        MainActivity[MainActivity (对话窗口)]
        Overlay[AvelineOverlay (状态悬浮窗)]
        PermActivity[CapturePermissionActivity (权限申请)]
    end

    subgraph ServiceLayer [服务层 (Orchestration)]
        AccessService[AvelineAccessibilityService]
    end

    subgraph InfrastructureLayer [基础设施层 (Capabilities)]
        Net[HttpClient (网络通信)]
        Capture[AvelineCaptureManager (屏幕截取)]
        Audio[AudioPlayer (音频播放)]
    end

    AccessLayer -->|指令/状态| ServiceLayer
    ServiceLayer -->|调用能力| InfrastructureLayer
    
    AccessService -->|监听按键| User
    AccessService -->|更新UI| Overlay
    AccessService -->|请求截图| Capture
    AccessService -->|发送分析| Net
    AccessService -->|播放回复| Audio
```

### 2.2 模块职责

#### 接入层 (Access Layer)
负责与用户的直接交互，包括可视化的界面和悬浮控件。
*   **MainActivity**: 主聊天界面，负责服务器配置、消息展示和发送。
*   **AvelineOverlay**: 全局悬浮窗，跨应用显示 Agent 的当前情绪状态或警告信息。

#### 服务层 (Service Layer)
核心业务的大脑，作为后台常驻服务运行。
*   **AvelineAccessibilityService**:
    *   **事件监听**: 监听系统级事件（如按键、窗口变化）。
    *   **流程编排**: 协调截图、网络请求和反馈播放的整个链路。
    *   **保活机制**: 确保 Agent 在后台不被轻易杀除。

#### 基础设施层 (Infrastructure Layer)
提供底层的设备能力和网络支持。
*   **HttpClient**: 封装对 Core 后端的 REST API 调用 (分析、对话)。
*   **AvelineCaptureManager**: 封装 `MediaProjection` API，处理屏幕截取、压缩与 Base64 编码。
*   **AudioPlayer**: 处理来自后端的语音数据播放。

---

## 3. 目录结构优化方案 (Directory Refactoring)

为了提高代码的可维护性，建议对 `com.aveline.core` 包进行以下结构调整：

```text
com.aveline.core
├── ui              # 接入层：界面相关
│   ├── MainActivity.kt
│   ├── ChatAdapter.kt
│   ├── AvelineOverlay.kt
│   └── CapturePermissionActivity.kt
├── service         # 服务层：后台服务
│   └── AvelineAccessibilityService.kt
├── infra           # 基础设施层：底层能力
│   ├── HttpClient.kt
│   ├── AvelineCaptureManager.kt
│   └── AudioPlayer.kt
└── App.kt          # (可选) 全局 Application
```

---

## 4. 核心流程详解 (Core Flows)

### 4.1 屏幕分析流程
1.  **触发**: 用户长按音量下键 (在 `AvelineAccessibilityService` 中捕获)。
2.  **反馈**: 悬浮窗状态变更为 "Analyzing" (橙色)。
3.  **截图**: 调用 `AvelineCaptureManager` 获取当前帧。
4.  **上传**: 通过 `HttpClient` POST 发送至 `/api/v1/analyze_screen`。
5.  **响应**: 后端返回分析结果 (Label) 和 语音 (Audio)。
6.  **执行**:
    *   若 Label 为 "fraud" (诈骗)，悬浮窗变红 ("Danger")。
    *   调用 `AudioPlayer` 播放分析语音。

### 4.2 权限获取流程
1.  首次截图时，`AvelineCaptureManager` 检测到无 `MediaProjection` 实例。
2.  启动 `CapturePermissionActivity` (透明 Activity)。
3.  系统弹窗请求录屏权限。
4.  用户授权后，Activity 将结果传递回 Manager 并关闭自身。

## 5. 性能与并发优化 (Performance & Concurrency)

系统已全面引入 **Kotlin Coroutines** 以解决主线程阻塞和回调地狱问题：

*   **异步 I/O**: `HttpClient` 和 `AudioPlayer` 的文件读写/网络请求均在 `Dispatchers.IO` 线程池中执行。
*   **图像处理**: `AvelineCaptureManager` 的 Bitmap 压缩与 Base64 编码操作已移至后台线程，避免阻塞 UI 或无障碍服务。
*   **结构化并发**: `AvelineAccessibilityService` 实现了 `CoroutineScope`，确保在服务销毁时自动取消所有未完成的任务，防止内存泄漏。
*   **线程安全**: UI 更新操作 (如 `AvelineOverlay.setStatus`) 严格限制在主线程执行。
