# 03 - 依赖注入层 (Hilt DI)

## 架构

4 个 Module，全部 `@InstallIn(SingletonComponent::class)`，说明所有依赖都是全局单例。

## AppModule — 基础依赖

```
@Module @InstallIn(SingletonComponent::class)
object AppModule
```

| 提供方法 | 返回类型 | 说明 |
|----------|----------|------|
| provideApplicationContext | Context | 全局 Application Context |
| provideResources | Resources | 资源访问 |
| provideFusedLocationProviderClient | FusedLocationProviderClient | Google Play 定位服务 |

简洁，只提供无法通过构造注入的基础对象。

## DatabaseModule — Room 数据库

```
@Module @InstallIn(SingletonComponent::class)
object DatabaseModule
```

**特点**：
- 单一数据库 `AvelineDatabase`，包含5张表
- 使用 `fallbackToDestructiveMigration()` - 数据库版本升级时删除旧数据重建（v1，无迁移逻辑）
- 5个 DAO 分别通过独立 `@Provides` 暴露

| 提供方法 | 类型 | 对应表 |
|----------|------|--------|
| provideAvelineDatabase | AvelineDatabase | 数据库实例 |
| provideMessageDao | MessageDao | messages |
| provideSessionDao | SessionDao | sessions |
| provideMemoryDao | MemoryDao | memories |
| provideNotificationDao | NotificationDao | notifications |
| provideHealthDataDao | HealthDataDao | health_data |

**注意**：`NotificationDao` 和 `HealthDataDao` 包路径在 `db/` 而不是 `database/`，是两个独立子包。

## NetworkModule — 网络层

```
@Module @InstallIn(SingletonComponent::class)
object NetworkModule
```

**核心设计：动态域名拦截器**

Retrofit 的 `baseUrl` 是固定占位符 `"http://127.0.0.1/"`，真实请求地址由 `baseUrlInterceptor` 在运行时动态替换，实现**用户可随时切换后端服务器地址**而无需重建 Retrofit 实例。

**拦截器链**（按添加顺序）：
1. **BaseUrlInterceptor** — 替换请求 URL（scheme + host + port）
2. **AuthInterceptor** — 注入 `Authorization: Bearer` + `x-internal-token` 头
3. **HttpLoggingInterceptor** — Debug 模式输出完整 Body，Release 模式不输出

**JSON 配置**：
- `ignoreUnknownKeys = true` — 忽略未知字段
- `isLenient = true` — 宽松解析
- `encodeDefaults = true` — 编码默认值

**OkHttp 配置**：
- 连接/读/写超时：30s
- WebSocket Ping 间隔：15s
- 自动重试：开启

**关键方法**：
```
normalizeBackendUrl(raw) — URL 标准化：
  "" → ""（触发自动发现）
  "192.168.1.100:8000" → "http://192.168.1.100:8000"
  "https://..." → 保持不变
```

## RepositoryModule — 仓库绑定

```
@Module @InstallIn(SingletonComponent::class)
abstract class RepositoryModule
```

使用 `@Binds` 将接口绑定到实现，共 11 个绑定：

| 接口 | 实现 |
|------|------|
| ChatRepository | ChatRepositoryImpl |
| SessionRepository | SessionRepositoryImpl |
| StatusRepository | StatusRepositoryImpl |
| HealthRepository | HealthRepositoryImpl |
| ContextRepository | ContextRepositoryImpl |
| MemoryRepository | MemoryRepositoryImpl |
| StudyRepository | StudyRepositoryImpl |
| PersonaRepository | PersonaRepositoryImpl |
| PluginsRepository | PluginsRepositoryImpl |
| ShopRepository | ShopRepositoryImpl |
| ToolsRepository | ToolsRepositoryImpl |

全部 `@Singleton`，随 Application 生命周期。
