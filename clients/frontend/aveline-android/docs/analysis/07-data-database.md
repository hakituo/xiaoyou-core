# 07 - 数据层：本地存储

## Room 数据库 — AvelineDatabase

### Schema（version=1, exportSchema=false）

5张表，统一数据库：

| 表名 | Entity | 主键 | 说明 |
|------|--------|------|------|
| messages | MessageEntity | id (String) | 聊天消息 |
| sessions | SessionEntity | id (String) | 会话元数据 |
| memories | MemoryEntity | id (String) | AI 记忆 |
| notifications | NotificationEntity | id (Long, auto) | 通知记录 |
| health_data | HealthDataEntity | id (Long, auto) | 健康数据快照 |

### Entity 详情

**MessageEntity**（messages 表）
```
id: String (PK)
text: String
isUser: Boolean
timestamp: Long
messageType: String = "text"    // text/system/retraction/image_result
audioBase64: String?            // 语音消息
imageUrl: String?               // 图片引用
sessionId: String?              // 所属会话
```

**SessionEntity**（sessions 表）
```
id: String (PK)
title: String
createdAt: Long
updatedAt: Long
isPinned: Boolean = false
```

**MemoryEntity**（memories 表）
```
id: String (PK)
content: String
type: String              // fact/preference/event/relationship
importance: Float
timestamp: Long
tags: String              // 逗号分隔标签
```

**NotificationEntity**（notifications 表）
```
id: Long (PK, autoGenerate)
packageName: String
title: String
content: String
timestamp: Long
isSent: Boolean = false   // 是否已同步到后端
```

**HealthDataEntity**（health_data 表）
```
id: Long (PK, autoGenerate)
type: String              // vital_signs / body_metrics
jsonData: String          // 原始 JSON 存储
timestamp: Long
isSent: Boolean = false   // 是否已同步
```

### 设计特点

1. **fallbackToDestructiveMigration()**: 版本升级直接删除重建，适用于开发阶段
2. **双主键策略**: 聊天相关表用 String ID（UUID/timestamp），离线缓存表用 Long 自增
3. **isSent 标记**: notification 和 health_data 表带 `isSent` 字段，支持离线缓存 + 延迟同步模式
4. **原始 JSON 存储**: health_data 使用 `jsonData: String` 存储，不建固定 schema，适应 Health Connect 多变的数据类型

## AppPreferences — 加密 SharedPreferences

`@Singleton` 注入，管理 18 个应用配置项。

### 存储分层

- **明文 Prefs** (`aveline_preferences`): 15 个常规配置
- **加密 Prefs** (`aveline_encrypted_preferences`, AES256-GCM + AES256-SIV): 1 个敏感配置

### 配置项清单

| 属性 | 类型 | 加密 | 默认值 | 用途 |
|------|------|------|--------|------|
| backendUrl | String | 否 | "" | 后端地址（空触发自动发现） |
| userId | String | 否 | "mobile_user" | 用户 ID |
| userName | String | 否 | "Mobile User" | 用户名称 |
| accessToken | String | **是** | "" | 访问令牌 |
| selectedVoiceId | String | 否 | "" | TTS 语音 |
| selectedModelId | String | 否 | "" | AI 模型 |
| responseLength | ResponseLength | 否 | NORMAL | 回复长度 |
| breathingRate | Float | 否 | 1.0 | 呼吸动画速率 |
| manualEmotion | EmotionType? | 否 | null | 手动情绪（null=自动） |
| autoEmotion | Boolean | 否 | true | 自动情绪开关 |
| currentSessionId | String? | 否 | null | 当前会话 |
| autoTtsEnabled | Boolean | 否 | false | 自动朗读 |
| residentModeEnabled | Boolean | 否 | false | 常驻模式 |
| lastSyncTimestamp | Long | 否 | 0 | 上次同步时间 |
| isContextSyncEnabled | Boolean | 否 | true | 上下文同步开关 |
| hapticFeedbackEnabled | Boolean | 否 | true | 触觉反馈 |
| languageCode | String | 否 | "" | 语言（空=跟随系统） |

### 设计特点

1. **加密方案**: `accessToken` 使用 Jetpack Security Crypto 库（AES256-GCM 主密钥 + AES256-SIV 密钥加密 + AES256-GCM 值加密）
2. **双清除策略**: `clear()` 仅清明文，`clearAll()` 清全部（用于登出/重置）
3. **提交策略**: 关键配置（backendUrl, userId, accessToken, currentSessionId）使用 `.commit()` 同步写入，其余使用 `.apply()` 异步
4. **自动发现**: `backendUrl` 默认为空字符串，触发 `ServerDiscoveryManager` 的 UDP 广播 + 网段扫描流程
