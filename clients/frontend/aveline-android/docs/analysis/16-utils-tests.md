# 16 - 工具类与测试

## 工具类（15个）

### 系统级工具

**CrashHandler** (`utils/CrashHandler.kt`, 205行)
- 全局异常捕获 `Thread.setDefaultUncaughtExceptionHandler`
- 崩溃日志记录（时间、堆栈、设备信息）
- 可选崩溃报告上报

**PerformanceMonitor** (`utils/PerformanceMonitor.kt`, 213行)
- 应用启动耗时记录（`recordAppStart` / `recordAppStartupComplete`）
- 页面加载耗时追踪
- 内存使用监控

**SecurityManager** (`utils/SecurityManager.kt`, 211行)
- Token 安全存储（EncryptedSharedPreferences）
- 数据传输加密验证
- SSL Pinning 支持（预留）

### 设备交互工具

**HapticFeedbackManager** (`utils/HapticFeedbackManager.kt`, 265行)
- 触觉反馈管理
- 不同强度等级
- 开关控制（AppPreferences.hapticFeedbackEnabled）

**AccessibilityManager** (`utils/AccessibilityManager.kt`, 234行)
- 无障碍服务管理
- 屏幕阅读器检测
- AccessibilityExtensions（300行）：Compose 扩展函数

**VoiceInputManager** 已在服务层介绍

### 数据处理工具

**InputValidator** (`utils/InputValidator.kt`, 294行)
- 后端 URL 格式验证
- Token 格式验证
- 文本长度限制
- 文件类型/大小验证

**DataExportManager** (`utils/DataExportManager.kt`, 269行)
- 聊天记录导出（JSON/文本格式）
- 记忆数据导出
- Share Intent 分享

**StateManager** (`utils/StateManager.kt`, 182行)
- UI 状态持久化
- 恢复上次状态（如最后打开的页面）

**ShareUtils** (`utils/ShareUtils.kt`, 142行)
- 通用分享封装
- 文本/图片分享 Intent 构建

### 网络与连接工具

**RetryUtils** (`utils/RetryUtils.kt`, 234行)
- 指数退避算法 `calculateExponentialBackoff(attempt, initialDelay, multiplier, maxDelay)`
- Jitter 随机化
- 重试策略配置

**DeepLinkHandler** (`utils/DeepLinkHandler.kt`, 190行)
- Deep link URI 解析
- 参数提取
- 路由映射

### 资源加载工具

**CoilImageLoader** (`utils/CoilImageLoader.kt`, 151行)
- Coil 图片加载配置
- 缓存策略
- 占位图/错误图处理

**LanguageManager** (`utils/LanguageManager.kt`, 165行)
- 语言切换（中文/英文）
- Locale 切换 → Activity 重启
- AppPreferences 语言持久化

### 错误处理

**ErrorHandler** (`utils/ErrorHandler.kt`, 181行)
- 统一错误处理
- 错误分类（网络/权限/数据/未知）
- 用户友好错误消息映射
- 错误日志记录

## 测试体系

### 测试框架

| 框架 | 用途 |
|------|------|
| JUnit 4.13.2 | 基础单元测试 |
| MockK 1.13.8 | Kotlin Mock 框架 |
| Kotest 5.8.0 | Property-based testing + 断言 |
| Coroutines Test 1.7.3 | 协程测试 |
| AndroidX Test | UI 测试 + Compose 测试 |
| Espresso 3.5.1 | UI 自动化测试 |

### 测试文件（14个）

**单元测试**:
```
- InputValidatorTest.kt          — 输入验证逻辑
- SecurityManagerTest.kt         — 安全功能
- FileUploadManagerTest.kt       — 文件上传
- FileUploadManagerPropertyTest.kt — Property-based 测试
- EmotionColorMappingTest.kt     — 情绪色彩映射
```

**Bug Condition 测试**:
```
- ChatViewModelBugConditionTest.kt    — 聊天 ViewModel 边界条件
- BreathingLightBugConditionTest.kt   — 呼吸灯动画边界
- ModelSelectionBugConditionTest.kt   — 模型选择边界
- PreservationPropertyTest.kt         — 数据持久化
```

**消息解析测试**:
```
- ExtractMessageContentTest.kt   — 消息内容提取
```

**规则/工具**:
```
- MainDispatcherRule.kt          — 测试用的 Main Dispatcher 规则
```

### 测试覆盖重点

1. **Property-based testing**: 使用 Kotest 进行随机输入测试（FileUploadManager）
2. **Bug condition testing**: 专门针对曾出现的 bug 场景编写回归测试
3. **Compose testing**: 使用 Compose Test 框架测试 UI 组件
4. **协程测试**: 使用 `StandardTestDispatcher` 控制协程执行

## 总结

### 项目规模
- **177 个源文件**（120+ Kotlin + Java + XML）
- **11 个 Repository** + **50+ API 端点**
- **15 种 WebSocket 消息类型**
- **11 个页面路由** + **10 个可复用组件**
- **7 个后台服务** + **3 个管理器**
- **15 个工具类** + **14 个测试文件**

### 架构亮点
1. **Clean Architecture 三层分离**：Presentation → Domain → Data，依赖方向明确
2. **动态域名设计**：Interceptor 方案实现运行时切换后端，无需重建 Retrofit
3. **零配置发现**：UDP 广播 + 网段扫描双路径，WiFi 多播锁处理 Android 限制
4. **离线优先**：Room 本地缓存 + isSent 标记 + 周期同步
5. **安全性**：EncryptedSharedPreferences 存储 Token，allowBackup=false
6. **完整的 WebSocket 协议**：重连、心跳、状态同步、流式响应、手机操控
7. **情绪可视化**：9种情绪 × 4色渐变 = 精确匹配 Web 端

### 可优化项
1. **DatabaseModule**: `fallbackToDestructiveMigration()` 在生产环境应改为正常 Migration
2. **Shop API**: 旧 `/api/v1/shop/*` 端点已标记 deprecated，应完全迁移到 `/api/v1/food/*`
3. **HealthManager**: 未接入 DI（通过构造函数手动创建），建议改为 Hilt 注入
4. **ContextRepositoryImpl**: `getRecentNotifications()` 返回空列表，需完善 NotificationService 集成
5. **测试覆盖率**: 当前仅覆盖核心模块，页面/Screen 级别缺少 UI 测试
6. **工具类膨胀**: `utils/` 目录 15 个文件，部分功能重叠（如 ErrorHandler + CrashHandler）
