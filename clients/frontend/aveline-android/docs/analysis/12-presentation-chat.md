# 12 - 表现层：聊天模块 (Chat)

## ChatViewModel

`@HiltViewModel`，最复杂的 ViewModel，依赖 **8 个组件**：

```
ChatRepository        — 消息收发
SessionRepository     — 会话管理
WebSocketManager      — 实时消息流
FileUploadManager     — 文件/图片上传
TTSEngine             — 语音播放
VoiceInputManager     — 语音输入
AppPreferences        — 用户配置
Context (Application) — 剪贴板等
```

### ChatUiState（16个字段）

```
messages: List<Message>          — 当前消息列表
currentSession: Session?         — 当前会话
isTyping: Boolean                — AI 正在打字
showTypingIndicator: Boolean     — 显示打字动画
isLoading: Boolean               — 正在加载历史
error: String?                   — 错误信息
inputText: String                — 输入框文字
currentEmotion: Emotion?         — 当前情绪
connectionState: ConnectionState — WebSocket 连接状态
playingMessageId: String?        — 正在播放 TTS 的消息
voiceInputState: VoiceInputState — 语音输入状态
voiceAmplitude: Float            — 语音振幅（0-1）
voicePartialText: String         — 语音部分识别结果
isRecording: Boolean             — 是否录音中
uploadState: UploadState         — 文件上传状态
lastUploadedImageUrl: String?    — 最后上传的图片 URL
loadingState: LoadingState       — 历史消息加载状态
```

### 消息流管道

```
WebSocketManager.messages (SharedFlow)
  → 过滤：只取 TextMessage + ResponseChunk
  → 响应块拼接：ResponseChunk 累积到完整消息
  → 去重：同 ID 消息不重复添加
  → 更新 messages 列表
```

### 核心功能

**发送消息**：
1. `chatRepository.sendMessage()` → REST API
2. 同时通过 WebSocket 接收流式响应（ResponseChunk）

**打字指示器**：
- 发送消息后 → `isTyping=true`, `showTypingIndicator=true`
- 收到 `ResponseDone` → `isTyping=false`
- 3秒延迟后 → `showTypingIndicator=false`

**消息持久化**：
- 加载历史：`sessionRepository.getSessionHistory()`
- 本地缓存：Room DAO 的 `observeMessages()` → Flow 实时更新

**TTS 播放**：
- `playMessage(messageId)` — 播放指定消息
- `stopTts()` — 停止播放
- 状态跟踪：`playingMessageId` + TTS state 观察

**语音输入**：
- `startVoiceInput()` / `stopVoiceInput()` — 控制录音
- 部分识别结果 → `voicePartialText`
- 振幅 → `voiceAmplitude`（用于波形动画）
- 最终结果 → 填入 inputText

**文件上传**：
- 图片选择器 → `FileUploadManager.uploadImage()`
- 进度跟踪 → `uploadState`
- 完成后 → 填入 `lastUploadedImageUrl`

**剪贴板**：
- 复制消息文字到系统剪贴板

### LoadingState

```
sealed class LoadingState
  NotLoaded — 未加载
  Loading  — 加载中
  Loaded(data) — 加载完成
```

## ChatScreen Composable

主聊天界面，组件结构：

```
Scaffold
├── TopBar（可选标题）
├── LazyColumn（消息列表）
│   ├── TimeSeparator（时间分隔符）
│   └── MessageBubble（消息气泡）
├── TypingIndicator（打字动画）
├── InputArea（输入区域）
│   ├── 文本输入框
│   ├── 语音按钮
│   ├── 图片/文件按钮
│   └── 发送按钮
└── SnackbarHost（错误/提示）
```

**特性**：
- 自动滚动到最新消息
- 时间分隔符（相邻消息超过一定间隔显示）
- 图片预览支持
- 输入框 IME 适配
