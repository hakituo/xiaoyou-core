# 08 - 数据层：Repository 实现

## 概览

11 个 Repository 实现，位于 `data/repository/`，全部 `@Singleton`。每个实现对应一个 domain 层的 Repository 接口。

## ChatRepositoryImpl

```
依赖: AvelineApiService, MessageDao
核心方法:
  sendMessage(text, sessionId, model) → Result<Message>
  observeMessages(sessionId) → Flow<List<Message>>
  getMessages(sessionId) → List<Message>
  trimMessages(sessionId) → Unit
```

**消息分段策略** (`smartSegmentText`):
- 解析后端返回的回复文本，提取撤回标记
- 生成带 index 后缀的子消息 ID（`msgId-0`, `msgId-1`...）
- 支持 `messageType="retraction"` 的撤回消息类型

**消息上限控制**: 每会话最多 200 条，超出自动清理

**发送流程**:
1. 先插入用户消息到本地 DB
2. 发 REST 请求到后端
3. 接收响应后分段插入 AI 回复
4. 触发 enforceMessageLimit

## ContextRepositoryImpl

```
依赖: 8个 Android 系统服务
  BatteryManager, ConnectivityManager, SensorManager,
  UsageStatsManager, NotificationManager, PowerManager,
  TelephonyManager, AudioManager

核心能力:
  getDeviceContext()      → DeviceContext（16个字段）
  getAppUsage(hours)      → List<AppUsageInfo>（Top 20）
  getRecentNotifications() → List<NotificationInfo>（暂空）
  getFullContext()        → FullContext（合并）
  observeDeviceContext()  → Flow<DeviceContext>（光线传感器驱动）
  syncToBackend(context)  → Result<Unit>
```

**设备上下文采集细节**:
- 电池: `BatteryManager.BATTERY_PROPERTY_CAPACITY`
- 网络: `ConnectivityManager.activeNetwork` → 识别 WiFi/Ethernet/Bluetooth/Cellular(2G-5G)
- 光线: `Sensor.TYPE_LIGHT` → callbackFlow 持续监听
- 屏幕亮度: `Settings.System.SCREEN_BRIGHTNESS`
- 音量: `AudioManager.getStreamVolume(STREAM_MUSIC)` 百分比
- 铃声模式: `AudioManager.ringerMode` → Silent/Vibrate/Normal

**权限检查**:
- `hasUsageStatsPermission()` — 通过查询最近1秒使用统计来判断
- `hasNotificationListenerPermission()` — 检查 NotificationListenerService 是否启用

## MemoryRepositoryImpl
```
依赖: MemoryDao, AvelineApiService
核心方法:
  getMemories(query, types, importantOnly, ...) → Result<List<Memory>>
  searchMemories(query) → Result<List<Memory>>
  deleteMemory(id) → Result<Unit>
  markImportant(id, isImportant) → Result<Unit>
  getMemoryStats() → Result<MemoryStatsData>
  getMemoryTags() → Result<List<TagItem>>
```

## SessionRepositoryImpl
```
依赖: SessionDao, AppPreferences, AvelineApiService
核心方法:
  getSessions() → Result<List<Session>>
  observeSessions() → Flow<List<Session>>
  createSession(title) → Result<Session>
  deleteSession(id) → Result<Unit>
  renameSession(id, title) → Result<Unit>
  togglePin(id, isPinned) → Result<Unit>
  getSessionHistory(id) → Result<List<Message>>
```

**当前会话持久化**: 通过 `AppPreferences.currentSessionId` 跟踪

## 其余 Repository

| Repository | 依赖 | 关键特性 |
|------------|------|----------|
| StatusRepositoryImpl | AvelineApiService | 获取 AI 生命状态、健康数据 |
| HealthRepositoryImpl | 系统服务 + Health Connect | 读取健康数据、设备上下文 |
| PersonaRepositoryImpl | AvelineApiService | 人格 CRUD、切换、原始 JSON 访问 |
| PluginsRepositoryImpl | AvelineApiService, AppPreferences | 模型设置、情绪设置、敏感内容 |
| ShopRepositoryImpl | AvelineApiService | 商店物品、购买、余额管理 |
| StudyRepositoryImpl | AvelineApiService | 文件管理、学习模式、复习系统 |
| ToolsRepositoryImpl | AvelineApiService | 图片生成、视觉描述、食物/通知/系统 |

## 设计模式

1. **离线优先**: Chat 和 Session Repository 先写本地 DB，再调 API
2. **Result 返回**: 全部使用 `kotlin.Result`，统一成功/失败处理
3. **Flow 支持**: `observeMessages()` 和 `observeDeviceContext()` 使用 Flow 提供响应式数据
4. **DAO + API 双源**: Chat/Memory/Session Repository 同时操作本地 Room 和远端 REST
