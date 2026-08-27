# 13 - 表现层：全部页面详情

## CircleScreen — 社交圈子

页面路径: `Routes.CIRCLE`

功能：
- 社交互动系统页面
- 切换群聊模式（`toggleGroupMode`）
- 仅展示 UI 框架（与后端圈子功能对接）

## StatusScreen — AI 生命状态

页面路径: `Routes.STATUS`

功能：
- 显示 AI 的生命状态（health, hunger, happiness, energy）
- 支持刷新按钮（`refreshStatus`）
- 实时更新通过 WebSocket `LifeStatusUpdate` 推送

## DailyDataScreen — 每日数据

页面路径: `Routes.DAILY`

功能：
- **Tab 切换**: 健康数据 / 设备上下文 / 学习记录
- **快捷操作**: 记录饮水（`recordDrink`）、开始学习（`startStudy`）、完成学习（`finishStudy`）
- **数据来源**: `/api/v1/daily-data/portrait/today` + `/api/v1/daily-data/recent`
- **权限请求**: Health Connect 权限（`onRequestPermissions`）

DailyDataViewModel:
- `setActiveTab(tab)` — 切换标签页
- `refreshData()` — 刷新全部数据
- `recordDrink()` — POST 记录饮水
- `startStudy()` / `finishStudy()` — 学习计时

## MemoryScreen — 记忆管理

页面路径: `Routes.MEMORY`

功能：
- **搜索栏**: 关键词搜索记忆
- **过滤器**: 按类型筛选（fact/preference/event/relationship）、仅重要记忆
- **排序**: 按重要性 / 时间排序
- **操作**: 标记重要、删除记忆（带确认弹窗）
- **清除**: 一键清除所有筛选

MemoryViewModel:
- `search(query)` — 搜索
- `setTypeFilter(type)` — 类型过滤
- `toggleImportantOnly()` — 切换仅重要
- `setSortOrder(order)` — 排序切换
- `deleteMemory(id)` / `confirmDelete()` — 删除流程
- `toggleImportant(id)` — 标记星标
- `getMemoryStats()` — 统计信息

## StudyScreen — 学习模块

页面路径: `Routes.STUDY`

功能：
- **文件管理 Tab**: 上传/删除学习文件
- **学习记录 Tab**: 记录学习进度（主题、内容、时长）
- **复习模式**: 开始复习 → 显示题目 → 查看答案 → 提交评分 → 结束会话
- **学习模式切换**: `toggleStudyMode()`
- **会话管理**: `startStudySession()` / `finishStudySession()`

StudyViewModel — 最多回调的 ViewModel（20+ 个回调）：
- 文件操作：uploadFile, deleteFile, toggleFileActive
- 记录操作：recordStudyProgress, setRecordTopic, setRecordContent, setRecordDuration
- 复习操作：startReview, submitReview, finishSession, setShowAnswer, setIsReviewMode
- 学习追踪：startStudySession, finishStudySession

## PersonaScreen — 人格管理

页面路径: `Routes.PERSONA`

功能：
- 展示可用人格列表
- 切换当前激活人格（`switchPersona(personaId)`）
- 显示人格详情（名称、描述、特性标签）

## ShopScreen — 商店

页面路径: `Routes.SHOP`

功能：
- **分类筛选**: 按类别筛选商品
- **商品列表**: 名称、价格、描述、图标
- **购买流程**: 点击 → 确认弹窗（支持数量调整）→ 确认购买 → 显示结果
- **余额显示**: 金币数量

ShopViewModel:
- `selectCategory(category)` — 分类切换
- `showPurchaseConfirm(item)` / `hidePurchaseConfirm()` — 购买确认流程
- `increaseQuantity()` / `decreaseQuantity()` — 数量调整
- `confirmPurchase()` — POST 购买请求
- `hidePurchaseResult()` — 关闭结果弹窗

## PluginsScreen — 插件/模型设置

页面路径: `Routes.PLUGINS`

功能：
- **情绪控制**: 手动选择情绪 / 自动情绪切换
- **回复长度**: 短/正常/长
- **学习模式**: 开启/关闭
- **敏感内容**: 查看状态 / 切换过滤

PluginsViewModel:
- `setManualEmotion(emotion)` — 手动设置情绪
- `toggleAutoEmotion()` — 自动/手动切换
- `setResponseLength(length)` — 回复长度
- `toggleStudyMode()` — 学习模式
- `refreshSensitive()` / `toggleSensitive()` — 敏感内容管理

## ToolsScreen — 工具集

页面路径: `Routes.TOOLS`

功能涵盖 7 个子系统：

1. **图片生成**: 选择模型 → 输入 prompt/negative prompt → 生成
2. **视觉描述**: 输入图片 URL + prompt → AI 描述
3. **食物系统**: 加载菜单/库存 → 购买/食用
4. **通知管理**: 加载通知列表
5. **意图分类**: 输入文字 → 运行意图分析
6. **系统资源**: 查看 CPU/内存/磁盘
7. **系统偏好**: 模式/回复长度/对话风格/灵敏度/ActiveCare/Debug

ToolsViewModel — 最多功能（30+ 回调）：
- 图片：loadImageModels, generateImage, setImagePrompt, setImageModelId, setImageNegativePrompt
- 视觉：setVisionInput, setVisionPrompt, describeVision
- 食物：loadFoodMenu, loadFoodInventory, buyFood, eatFood
- 通知：loadNotifications
- 意图：setIntentText, runIntent
- 系统：loadSystemResources, loadSystemStats, loadPreferences, savePreferences

## SettingsScreen — 应用设置

页面路径: `Routes.SETTINGS`

功能：
- **后端配置**: 输入后端 URL + Token → 保存 → 测试连接
- **模型选择**: 从可用模型列表选择
- **TTS 设置**: 选择语音 + 自动朗读开关
- **回复长度**: 短/正常/长
- **Health Connect**: 打开权限设置
- **使用统计**: 打开 Usage Stats 权限设置
- **通知监听**: 打开 Notification Listener 设置
- **上下文同步**: 开关控制
- **常驻模式**: 前台服务常驻开关
- **清除历史**: 确认弹窗 → 清除全部聊天记录

SettingsViewModel:
- `setBackendUrl(url)` / `setAccessToken(token)` — 配置后端
- `saveBackendUrl()` — 保存配置
- `testConnection()` — 测试 /health 端点
- `selectModel(id)` / `setVoiceId(id)` — 模型/语音选择
- `toggleAutoTts()` / `toggleResidentMode()` / `toggleContextSync()` — 开关
- `clearHistory()` — 清除聊天历史
- `openHealthConnectSettings()` / `openUsageStatsSettings()` / `openNotificationSettings()` — 系统设置跳转
