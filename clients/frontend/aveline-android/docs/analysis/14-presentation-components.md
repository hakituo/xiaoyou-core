# 14 - 表现层：可复用组件

## 组件清单（10个）

### BreathingBackground — 呼吸灯背景

**文件**: `components/BreathingBackground.kt`

Canvas 绘制的动态光斑背景，4个径向渐变圆形以不同速度缩放。

**动画参数**:
| 光斑 | 中心位置 | 初始缩放 | 动画周期 | 颜色索引 |
|------|----------|---------|----------|----------|
| Blob 1 | (20%, 30%) | 0.8x → 1.2x | 5000ms | color[0] |
| Blob 2 | (80%, 70%) | 1.1x → 0.9x | 5500ms | color[1] |
| Blob 3 | (55%, 45%) | 0.95x → 1.1x | 6000ms | color[2] |
| Top   | (50%, 2%)  | 固定 0.38×maxDim | — | color[3] |

**输入参数**:
- `emotion: String?` — 当前情绪，映射到 EmotionColorMapping 的色彩方案
- `emotionColors: List<String>` — 备用色彩（WebSocket 直接推送的颜色数组）
- `backgroundAlpha: Float` — 背景透明度

**视觉效果**: 各光斑使用 `FastOutSlowInEasing` 缓动，叠加形成流动的极光效果。

### DrawerContent — 侧边抽屉内容

**文件**: `components/DrawerContent.kt`

Material3 Drawer 内容组件：
- 顶部：连接状态指示器 + 当前情绪
- 导航菜单：11个路由入口（图标 + 文字）
- 会话列表：支持重命名、删除、置顶操作
- 新建会话按钮

### InputArea — 聊天输入区域

**文件**: `components/InputArea.kt`

底部输入栏：
- 文本输入框（圆角、Material3 风格）
- 图片选择按钮（ActivityResult launcher）
- 语音输入按钮（长按录音）
- 发送按钮（输入非空时激活）

### MessageBubble — 消息气泡

**文件**: `components/MessageBubble.kt`

聊天气泡组件：
- 用户消息：右对齐，深色背景
- AI 消息：左对齐，透明/浅色背景
- 支持消息类型：text / system / retraction / image_result
- 撤回消息：特殊样式（灰色斜体）
- 图片消息：Coil 加载
- 长按复制（文字消息）
- TTS 播放按钮（AI 消息）

### TypingIndicator — 打字指示器

**文件**: `components/TypingIndicator.kt`

三个点动画，表示 AI 正在输入：
- 渐变出现/消失动画
- 位置：聊天列表底部

### TimeSeparator — 时间分隔符

**文件**: `components/TimeSeparator.kt`

消息间的时间标签：
- 两条相邻消息时间差 ≥ 阈值（如5分钟）时显示
- 居中文本，半透明样式

### ModuleHeader — 模块标题

**文件**: `components/ModuleHeader.kt`

各页面顶部的标准化标题栏：
- 标题文字 + 返回按钮（可选）

### SessionDialogs — 会话对话框

**文件**: `components/SessionDialogs.kt`

会话管理弹窗集合：
- 重命名对话框（文本输入）
- 删除确认对话框
- 新建会话对话框

### TTSComponents — TTS 播放组件

**文件**: `components/TTSComponents.kt`

TTS 播放控制 UI：
- 播放/暂停按钮
- 进度条
- 与 TTSEngine 状态联动

### VoiceInputComponents — 语音输入组件

**文件**: `components/VoiceInputComponents.kt`

语音输入 UI：
- 录音状态指示（麦克风图标动画）
- 波形振幅可视化
- 部分识别文字实时显示

## 共享类型

`ConnectionState`（在 DrawerContent 中定义，也在 MainActivity 使用）：
```
enum class ConnectionState { CONNECTED, CONNECTING, DISCONNECTED }
```

`MessageData` / `MessageType`（在 MessageBubble 中定义）：
聊天 UI 使用的消息数据类型，从 domain.Message 映射而来。
