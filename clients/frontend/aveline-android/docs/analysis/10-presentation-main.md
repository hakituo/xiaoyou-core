# 10 - 表现层：MainActivity & MainViewModel

## MainActivity

`@AndroidEntryPoint`，继承 `AppCompatActivity`，是**唯一入口 Activity**。

### onCreate 流程

```
1. ServerDiscoveryManager.discoverServer()
   → UDP 广播发现（5s超时）→ 网段扫描兜底
   → 发现后自动保存到 AppPreferences.backendUrl
   → 通知 ForegroundService 更新后端地址

2. 常驻模式检查
   → residentModeEnabled=true → start ForegroundService + startPeriodicSync
   → false → stopPeriodicSync

3. FCM Token 注册
   → FirebaseMessaging.token → POST /api/v1/system/mobile-push-token
      {token, platform:"android", user_id, user_name}

4. Deep Link 处理
   → intent.data → AtomicReference 存储 → Compose 内 LaunchedEffect 消费

5. 系统栏配置
   → setDecorFitsSystemWindows(false) — 全屏沉浸
   → 状态栏/导航栏暗色图标关闭

6. setContent → AvelineTheme → AvelineApp()
```

### Deep Link 解析

```
aveline://chat?text=xxx       → chat route with text param
aveline://status              → status route
aveline://settings            → settings route
... (共11条路由)
```

### 生命周期管理

- `onResume` 时触发 `mainViewModel.reconnect()`
- `onNewIntent` 时处理新的 deep link

## AvelineApp Composable

主 Composable 函数，包含：
- **ModalNavigationDrawer** — 侧边抽屉导航
- **BreathingBackground** — 情绪驱动的动态光斑背景
- **NavHost** — 路由容器
- **DrawerContent** — 侧边栏内容（会话列表 + 导航菜单）

### 连接状态映射

```
WebSocket ConnectionState → ConnectionState（UI用）
  CONNECTED → CONNECTED（绿色）
  CONNECTING → CONNECTING（黄色旋转）
  DISCONNECTED → DISCONNECTED（红色）
```

## MainViewModel

`@HiltViewModel`，依赖 `SessionRepository + WebSocketManager`。

### MainUiState

```
sessions: List<Session>
currentSessionId: String?
connectionState: ConnectionState
currentEmotion: String           // 当前情绪（默认 "calm"）
emotionColors: List<String>      // 情绪对应颜色
isLoading: Boolean
error: String?
```

### 功能

**会话管理**:
- `loadSessions()` — 从后端/本地加载会话列表
- `createSession()` — 创建新会话
- `switchSession(sessionId)` — 切换当前会话（保存到 AppPreferences）
- `renameSession(id, title)` — 重命名
- `deleteSession(id)` — 删除
- `toggleSessionPin(id, isPinned)` — 置顶/取消置顶

**连接观察**:
- `observeConnectionState()` — WebSocket 状态 → UI 状态
- `observeEmotionState()` — 收集 WebSocket 的 EmotionUpdate 消息，更新情绪和颜色

**重连**: `reconnect()` — 调用 `webSocketManager.connect(forceReconnect=true)`

### Drawer 交互

侧边栏的导航逻辑全部在 AvelineApp Composable 中通过回调处理：
- `onNavigate(route)` → 关闭抽屉 + 导航到目标路由（launchSingleTop + restoreState + saveState）
- `onSessionClick(sessionId)` → 关闭抽屉 + 切换会话
- `onNewSession()` → 创建新会话
- `onSettingsClick()` → 关闭抽屉 + 导航到设置页
