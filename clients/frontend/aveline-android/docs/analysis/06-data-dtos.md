# 06 - 数据层：DTOs（数据传输对象）

## 概览

21个 DTO 文件，位于 `data/remote/dto/`，使用 `kotlinx.serialization` + `@SerialName` 注解实现 snake_case ↔ camelCase 映射。

所有 DTO 与 domain model 之间有明确的 `fromDomain()` / `toDomainModel()` 转换方法，严格遵守 Clean Architecture 分层。

## 核心 DTO 详情

### MessageRequest / MessageResponse
```
MessageRequest:
  text: String, session_id: String?, model: String

MessageResponse:  // 多字段兼容设计
  status, message, data, response, reply — 5个可能的响应字段
  emotion, emotion_internal, request_id, message_id, conversation_id
  → 兼容后端不同版本的响应格式

MessageDto:  // 消息体，支持多模态
  text, isUser, timestamp, messageType（text/system/retraction/image_result）
  audioBase64?, imageUrl?, imageBase64?, emotion?
```

### SessionResponse（会话管理）
```
SessionDto: id, title, created_at, updated_at, isPinned
SessionsResponse: sessions[] / data[] — 双字段兼容
CreateSessionRequest: title="New Chat"
HistoryResponse: messages[] / data[]
```

### MemoryDto（记忆系统）
```
MemoryDto:  // 丰富的元数据
  id, content, type, importance, access_count,
  last_accessed_at, created_at, updated_at, source, tags, is_important

MemoryListResponse: status, data[], timestamp
MemoryStatsData: total_count, fact/preference/event/relationship_count, important_count
TagsResponse: TagItem[] (name + weight)
```

### PersonaDto（人格系统）
```
PersonaDto: id, name, description, system_prompt, avatar_url,
            traits[], is_default, is_custom, created_at, updated_at
PersonaRequest: name, description, system_prompt, avatar_url?, traits[]
SelectPersonaRequest: filename → personaId
ActivePersonaResponse: status, filename, data
```

### ContextSyncRequest（上下文同步）
```
ContextSyncRequest:  // 完整的设备状态快照
  DeviceContextDto: battery_level, is_charging, battery_status, network_type,
                    is_network_available, light_level?, screen_brightness?,
                    is_screen_on, volume_level?, ringer_mode, timezone, locale
  AppUsageDto[]: package_name, app_name, usage_time_ms, last_used_time, launch_count
  NotificationDto[]: package_name, app_name, title?, text?, timestamp, category?
  HealthDataDto[]: type, json_data, timestamp

所有子 DTO 的 companion object 实现了 fromDomain() 转换
```

### ShopDto（商店系统，含废弃内容）
```
ShopItemDto: id, name, price, category, icon, effects{}, is_available
UserBalanceDto: coins, gems, total_earned, total_spent
PurchaseResponse: status, new_balance, effects_applied, balance
  → toDomainModel() 转换为 PurchaseResult
```

### StudyFileDto（学习系统）
```
StudyFileDto: id, filename, file_type, file_size, upload_time, is_active
StudyFilesResponse: files[]
SetActiveFilesRequest: file_ids[]
```

### 其他 DTO

| 文件 | 内容 | 用途 |
|------|------|------|
| ModelDto | ModelsResponse: models[]（id, name, provider, type）| AI 模型选择 |
| TTSRequest | text, voice_id, speed | 语音合成请求 |
| VoicesResponse | voices[]（id, name, language）| 可用语音列表 |
| UploadResponse | url, file_id, file_name | 文件上传结果 |
| ImageDtos | ImageModelsResponse, ImageGenerateResponse | 图片生成 |
| VisionDtos | VisionDescribeResponse | 视觉描述 |
| IntentDtos | IntentClassifyResponse | 意图分类 |
| NotificationDtos | NotificationsResponse | 通知列表 |
| SystemDtos | SystemPreferencesResponse, SystemResourcesResponse, SystemStatsResponse, SensitiveStatusResponse, SensitiveToggleResponse | 系统管理 |
| FoodDtos | FoodItemDto, FoodInventoryResponse, FoodActionResponse | 食物系统 |
| LifeStatusResponse | health, hunger, happiness, energy, timestamp | AI 生命状态 |

## 设计特点

1. **蛇形/驼峰映射**: 全部使用 `@SerialName` 精确映射
2. **向前兼容**: 响应 DTO 常有多字段（如 `message`/`data`/`response`/`reply`）同时存在
3. **分层转换**: DTO → Domain Model 的转换在 DTO 自身（`toDomainModel()`）或 companion object（`fromDomain()`）中完成
4. **JSON 灵活性**: 部分端点返回 `JsonObject` 原样，适应动态 schema
