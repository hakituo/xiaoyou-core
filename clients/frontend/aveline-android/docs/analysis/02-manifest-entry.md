# 02 - AndroidManifest & 应用入口

## AndroidManifest.xml

### 权限体系（27+ 权限）

**基础权限（6项）**
```
INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE,
WAKE_LOCK, VIBRATE, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE
```

**通知权限（2项）**
```
POST_NOTIFICATIONS, BIND_NOTIFICATION_LISTENER_SERVICE
```

**音频权限（2项）**
```
RECORD_AUDIO, MODIFY_AUDIO_SETTINGS
```

**系统权限（4项）**
```
REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, RECEIVE_BOOT_COMPLETED,
PACKAGE_USAGE_STATS (protected), ACTIVITY_RECOGNITION
```

**电话/SMS/日历/位置（6项）**
```
WRITE_CALENDAR, READ_CALENDAR, CALL_PHONE, SEND_SMS,
ACCESS_NOTIFICATION_POLICY, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION
```

**Health Connect（16项）**
```
READ_STEPS, READ_HEART_RATE, READ_SLEEP, READ_TOTAL_CALORIES_BURNED,
READ_EXERCISE, READ_WEIGHT, READ_HEIGHT, READ_BODY_FAT,
READ_BODY_WATER_MASS, READ_BONE_MASS, READ_BASAL_METABOLIC_RATE,
READ_BLOOD_PRESSURE, READ_BLOOD_GLUCOSE, READ_OXYGEN_SATURATION,
READ_BODY_TEMPERATURE, READ_BODY_MASS_INDEX
```

### 组件注册

| 组件 | 类型 | 说明 |
|------|------|------|
| `MainActivity` | Activity | 主入口，launchMode=singleTask，支持 deep link (`aveline://`) |
| `ViewPermissionUsageActivity` | Activity-Alias | Health Connect 权限查看入口 |
| `AvelineForegroundServiceV2` | Service | 前台服务，foregroundServiceType=specialUse |
| `AvelineNotificationService` | Service | NotificationListenerService（监听通知） |
| `AvelineFirebaseMessagingService` | Service | FCM 推送接收 |
| `BootCompletedReceiver` | Receiver | 开机自启动 |
| `FileProvider` | Provider | 文件共享（拍照/文件选择） |
| `WorkManagerInitializer` | Provider | 禁用默认 WorkManager init，改用 Hilt |

### 安全配置

- `allowBackup=false`, `fullBackupContent=false` - 禁止备份
- `usesCleartextTraffic=false` - 禁止明文 HTTP
- `networkSecurityConfig` - 自定义网络安全配置

## AvelineApplication

```
@HiltAndroidApp
class AvelineApplication : Application(), Configuration.Provider
```

**启动流程**：
1. `performanceMonitor.recordAppStart()` - 记录启动时间
2. `crashHandler.init()` - 初始化崩溃处理
3. `notificationManager.createNotificationChannels()` - 创建通知渠道（3个：消息/警告/系统）
4. `performanceMonitor.recordAppStartupComplete()` - 记录启动完成

**WorkManager 集成**: 实现 `Configuration.Provider`，注入 HiltWorkerFactory

## HealthManager

非 DI 注入的独立类（用于老旧 WebView 入口），通过 `HealthConnectClient` 读写健康数据：

**关键方法**:
- `checkAvailability()` - SDK 可用性检查（available/unavailable/update_required）
- `readVitalSigns()` - 读取生命体征（步数、心率、血氧）
- `readBodyMetrics()` - 读取身体指标（体重、身高、睡眠）
- `readHealthData()` - 合并读取（legacy）
- `getPermissions()` - 获取所需权限集合（14种健康数据类型）
- `getRequestPermissionResultContract()` - 返回权限请求 Contract

**数据读取策略**:
- 生命体征：最近1小时（心率、血氧取最新1条）
- 身体指标：最近30天（体重、身高取最新1条，睡眠取最后一段）
- 步数：当日累计

## Deep Link 路由

| URI Pattern | 目标 | 说明 |
|-------------|------|------|
| `aveline://chat` | 聊天页 | 可选 `?text=` 参数预填消息 |
| `aveline://circle` | 圈子页 | 社交互动 |
| `aveline://status` | 状态页 | AI 生命状态 |
| `aveline://daily` | 每日数据 | 健康/设备上下文 |
| `aveline://memory` | 记忆管理 | AI 记忆 |
| `aveline://study` | 学习模块 | 文件/复习 |
| `aveline://persona` | 人格管理 | 切换人格 |
| `aveline://shop` | 商店 | 物品购买 |
| `aveline://plugins` | 插件 | 模型/情绪设置 |
| `aveline://tools` | 工具 | 图片生成/视觉/系统 |
| `aveline://settings` | 设置 | 应用配置 |
