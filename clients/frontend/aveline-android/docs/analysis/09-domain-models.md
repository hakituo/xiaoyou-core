# 09 - Domain 层：领域模型与接口

## Domain Models（`domain/models/`）

15 个领域模型文件，纯 Kotlin data class，无 Android 依赖，可独立测试。

### 核心模型

**Message** — 聊天消息
```
id, text, isUser, timestamp, messageType, audioBase64?, imageUrl?, imageBase64?, emotion?, sessionId?
支持：文本、语音（base64）、图片（URL/base64）、撤回消息类型
```

**Session** — 会话
```
id, title, createdAt, updatedAt, isPinned
```

**Emotion** — 情绪状态
```
primary: String       // neutral/happy/calm/excited/sad 等
intensity: Float      // 0.0-1.0
colors: List<String>  // 情绪对应颜色
companion 预定义：NEUTRAL, HAPPY, CALM, EXCITED, SAD
```

**LifeStatus** — AI 生命状态
```
health, hunger, happiness, energy: Float  // 0.0-1.0
方法：hasLowStatus() — 检查是否低于20%；getLowestStatus() — 最低值
```

**DeviceContext** — 设备上下文
```
batteryLevel, isCharging, batteryStatus: BatteryStatus
networkType: NetworkType, isNetworkAvailable
lightLevel?, screenBrightness?, isScreenOn, volumeLevel?
ringerMode: RingerMode, timezone, locale
计算属性：batteryPercentage, formattedLightLevel
```

**枚举类型**：
- `BatteryStatus`: UNKNOWN/CHARGING/DISCHARGING/NOT_CHARGING/FULL
- `NetworkType`: UNKNOWN/OFFLINE/WIFI/CELLULAR_2G~5G/ETHERNET/BLUETOOTH
- `RingerMode`: UNKNOWN/SILENT/VIBRATE/NORMAL

**AppUsageInfo** — 应用使用统计
```
packageName, appName, usageTimeMs, lastUsedTime, launchCount
计算属性：usageTimeMinutes, usageTimeHours, formattedUsageTime
```

**NotificationInfo** — 通知信息
```
id, packageName, appName, title?, text?, timestamp, category?
```

**FullContext** — 完整上下文聚合
```
device: DeviceContext
appUsage: List<AppUsageInfo>
notifications: List<NotificationInfo>
healthData: HealthData?
collectedAt: Instant
```

### 业务模型

| 模型 | 字段 | 用途 |
|------|------|------|
| FoodModels | FoodItem, FoodCategory(MEAL/SNACK/DRINK/DESSERT/SPECIAL), NutritionInfo | 食物系统 |
| HealthData | 健康数据聚合 | 健康模块 |
| IntentModels | IntentType, IntentResult | 意图分类 |
| Memory | 记忆条目 | 记忆系统 |
| Persona | 人格配置 | 人格管理 |
| PersonaSwitchResult | 切换结果 | - |
| PhoneAction | 14种操作（sealed class） | AI 操控手机 |
| PhoneActionResult | actionId, success, resultType, data, error | 操作结果 |
| PluginSettings | 插件配置 | 插件管理 |
| ShopItem | 商店物品 | 商店 |
| StudyFile | 学习文件 | 学习模块 |
| SystemModels | 系统偏好/资源/统计 | 系统管理 |

### PhoneAction（sealed class，14种操作）

```
CreateCalendarEvent  — 创建日历事件（title, startTime, endTime, reminder）
SetAlarm            — 设置闹钟（hour, minute, message, vibrate, skipUi）
SetTimer            — 设置计时器（seconds, message, skipUi）
OpenApp             — 打开应用（packageName, query）
MakePhoneCall       — 拨打电话（phoneNumber）
SendSms             — 发送短信（phoneNumber, message）
OpenNavigation      — 导航（destination, mode: driving/walking/bicycling/transit）
SetDndMode          — 勿扰模式（enable）
MediaControl        — 媒体控制（command: play/pause/next/previous/stop）
OpenSettings        — 打开设置（settingsType: wifi/bluetooth/location/display/...）
ShareContent        — 分享内容（text, title）
SetVolume           — 设置音量（streamType, level）
GetLocation         — 获取位置
Unknown             — 未知操作（rawType, rawParams）
```

## Domain Repository Interfaces（`domain/repository/`）

11 个接口，定义业务逻辑层的契约：

```
ChatRepository      — 发送消息、观察消息、加载历史
SessionRepository   — 会话 CRUD + 历史
StatusRepository    — 生命状态查询
HealthRepository    — 健康数据
ContextRepository   — 设备上下文 + 应用使用 + 权限检查 + 同步
MemoryRepository    — 记忆 CRUD + 搜索 + 统计 + 标签
StudyRepository     — 学习文件 + 模式 + 复习 + 会话
PersonaRepository   — 人格 CRUD + 切换
PluginsRepository   — 模型/情绪/敏感内容设置
ShopRepository      — 商品 + 购买 + 余额
ToolsRepository     — 图片生成 + 视觉 + 食物 + 通知 + 系统
```

所有接口方法返回 `Result<T>` 或 `Flow<T>`。
