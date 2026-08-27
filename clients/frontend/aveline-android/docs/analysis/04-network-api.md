# 04 - 网络 API 层 (Retrofit)

## AvelineApiService — 50+ REST 端点

接口定义 `com.aveline.ai.mobile.data.remote.api.AvelineApiService`，使用 Retrofit + kotlinx.serialization，总计 50+ 个 API 端点。

### 端点分类

#### 消息 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/message` | 发送消息 |

#### 会话管理 (5)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/sessions` | 获取会话列表 |
| POST | `/api/v1/sessions` | 创建新会话 |
| GET | `/api/v1/sessions/{id}/history` | 获取会话历史 |
| DELETE | `/api/v1/sessions/{id}` | 删除会话 |
| PUT | `/api/v1/sessions/{id}` | 更新会话（重命名等） |

#### 状态 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/status/life` | 获取 AI 生命状态 |

#### 上下文同步 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/context/sync` | 同步设备上下文 |

#### TTS (2)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tts` | 文字转语音 |
| GET | `/api/v1/voices` | 获取可用语音列表 |

#### 文件上传 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/upload` | 上传文件（Multipart） |

#### 记忆系统 (9)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/memory/weighted` | 获取加权记忆（支持查询/过滤/分页） |
| GET | `/api/v1/memory/{id}` | 获取单条记忆 |
| GET | `/api/v1/memory/search?q=` | 关键词搜索记忆 |
| DELETE | `/api/v1/memory/{id}` | 删除记忆 |
| PATCH | `/api/v1/memory/{id}/important` | 标记/取消重要 |
| GET | `/api/v1/memory/stats` | 记忆统计 |
| GET | `/api/v1/memory/tags` | 记忆标签列表 |

#### 学习系统 (6)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/study/files` | 学习文件列表 |
| POST | `/api/v1/study/upload` | 上传学习文件 |
| DELETE | `/api/v1/study/files/{id}` | 删除学习文件 |
| GET | `/api/v1/study/mode` | 学习模式状态 |
| POST | `/api/v1/study/mode` | 设置学习模式 |
| POST | `/api/v1/study/files/active` | 设置活跃文件 |

#### 人格系统 (6)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/personas` | 人格列表（含原始 JSON 变体） |
| GET | `/api/personas/active` | 当前激活人格 |
| POST | `/api/personas/switch` | 切换人格 |
| POST | `/api/personas` | 创建自定义人格 |
| PUT | `/api/personas/{id}` | 更新人格 |
| DELETE | `/api/personas/{id}` | 删除人格 |

#### 模型 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/models` | 可用模型列表 |

#### 食物/商店 (5+4)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/food/menu?type=` | 食物菜单 |
| GET | `/api/v1/food/inventory` | 食物库存 |
| POST | `/api/v1/food/buy/{food_id}?quantity=` | 购买食物 |
| POST | `/api/v1/food/eat/{food_id}?from_inventory=` | 吃食物 |
| GET/POST | `/api/v1/shop/*` | 旧商店 API (deprecated) |

#### 图片/视觉 (4)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/image/models` | 图片生成模型列表 |
| POST | `/api/v1/image/generate` | 生成图片 |
| POST | `/api/v1/vision/describe` | 视觉描述 |
| POST | `/api/v1/analyze_screen` | 屏幕分析 |

#### 通知/系统 (6)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/notifications` | 获取通知 |
| GET | `/api/v1/system/preferences` | 获取系统偏好 |
| POST | `/api/v1/system/preferences` | 更新系统偏好 |
| POST | `/api/v1/system/mobile-push-token` | 注册 FCM Token |
| GET | `/api/v1/system/resources` | 系统资源监控 |
| GET | `/api/v1/system/stats` | 系统统计 |

#### 每日数据 (3)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/daily-data/portrait/today` | 今日画像 |
| GET | `/api/v1/daily-data/recent?limit=` | 最近数据 |
| POST | `/api/v1/daily-data/record/drink` | 记录饮水 |
| POST | `/api/v1/daily-data/record/study` | 记录学习 |
| POST | `/api/v1/daily-data/study/finish` | 完成学习 |

#### 工作区/意图/插件 (6)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/v1/workspace/study/*` | 学习面板 |
| GET | `/api/v1/study/daily` | 每日词汇 |
| POST | `/api/v1/study/session/start` | 开始学习会话 |
| POST | `/api/v1/study/review` | 提交复习 |
| POST | `/api/v1/study/session/end` | 结束会话 |
| GET | `/api/v1/study/session/stats` | 会话统计 |
| GET | `/api/v1/study/dict/stats` | 词典统计 |
| GET | `/api/v1/study/memory/curve` | 记忆曲线 |
| GET | `/api/v1/study/mistakes` | 错题本 |
| POST | `/api/v1/intent/classify` | 意图分类 |
| GET | `/api/plugins/sensitive/status` | 敏感内容状态 |
| POST | `/api/plugins/sensitive/toggle` | 切换敏感内容过滤 |

#### 健康检查 (1)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 连接测试 |

## 设计特点

1. **双认证头**: `Authorization: Bearer` + `x-internal-token` 同时发送
2. **JSON 优先**: 全部端点使用 kotlinx.serialization，部分端点直接返回 `JsonObject`（如 daily-data）以保持灵活性
3. **兼容性设计**: `MessageResponse` 同时支持 `message`、`data`、`response`、`reply` 四个字段，兼容后端不同版本
4. **Shop API 废弃标注**: `/api/v1/shop/*` 已标记 deprecated，迁移至 `/api/v1/food/*`
5. **代码组织**: 按功能域分组注释（Message / Session / Status / Context / TTS / Upload / Memory / Study / Persona / Model / Food / Shop / Health / Image / Vision / Notification / System）
