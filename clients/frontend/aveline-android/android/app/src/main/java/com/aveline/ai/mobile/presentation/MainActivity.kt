package com.aveline.ai.mobile.presentation

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.State
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.NavGraph.Companion.findStartDestination
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.discovery.ServerDiscoveryManager
import com.aveline.ai.mobile.services.worker.DataSyncManager
import com.aveline.ai.mobile.presentation.components.BreathingBackground
import com.aveline.ai.mobile.presentation.components.ConnectionState
import com.aveline.ai.mobile.presentation.components.DrawerContent
import com.aveline.ai.mobile.presentation.components.PullableNavigationDrawer
import com.aveline.ai.mobile.presentation.components.rememberPullableDrawerState
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.avelineNavGraph
import com.aveline.ai.mobile.presentation.theme.AvelineTheme
import com.google.firebase.messaging.FirebaseMessaging
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : AppCompatActivity() {

    @Inject
    lateinit var appPreferences: AppPreferences

    @Inject
    lateinit var dataSyncManager: DataSyncManager

    @Inject
    lateinit var apiService: AvelineApiService

    @Inject
    lateinit var serverDiscoveryManager: ServerDiscoveryManager

    @Inject
    lateinit var notificationManager: AvelineNotificationManager

    // 修复 P0-26:原实现用 companion object 的 static AtomicReference 传递 DeepLink,
    // 进程被杀后静态变量丢失,DeepLink 也丢失。
    // 改为成员变量 + savedInstanceState 持久化 + Compose State 观察,
    // 进程被杀后能从 savedInstanceState 恢复,且 onNewIntent 设置新值时 AvelineApp 能观察到变化。
    private val deepLinkState = mutableStateOf<Uri?>(null)

    // 申请 Android 13+ 的 POST_NOTIFICATIONS 权限。前台保活通知必须依赖该权限才能在状态栏显示;
    // 未授予时, 通知会被系统静默隐藏(13)或导致 startForeground 抛异常(14) 进而服务被强杀, 后台维持直接失效。
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            Log.i(TAG, "已授予通知权限, 拉起前台保活服务")
        } else {
            Log.w(TAG, "未授予通知权限, 前台保活通知将无法显示, 后台进程易被系统回收")
            Toast.makeText(
                this,
                "未授予通知权限：后台常驻通知不会显示，App 可能很快被系统回收。请在系统设置中开启通知。",
                Toast.LENGTH_LONG
            ).show()
        }
        // 无论授权结果都尝试拉起: 已授权则通知正常显示; 未授权时部分机型(Android 13)服务仍可维持。
        startKeepAliveServiceIfNeeded()
    }

    private val TAG = "MainActivity"

    /**
     * 先确认通知权限, 再拉起前台保活服务。
     * Android 13 以下无需该权限, 直接拉起。
     */
    private fun ensureKeepAliveWithNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            startKeepAliveServiceIfNeeded()
            return
        }
        if (notificationManager.hasNotificationPermission()) {
            startKeepAliveServiceIfNeeded()
            return
        }
        if (shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS)) {
            Toast.makeText(
                this,
                "后台保活需要通知权限来显示常驻通知，否则 App 会被系统回收。",
                Toast.LENGTH_LONG
            ).show()
        }
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun startKeepAliveServiceIfNeeded() {
        // 进入软件即拉起前台保活服务, 挂出常驻通知维持后台运行。
        // 不再依赖"无障碍已开启"或"常驻模式已开启"等任何开关, 用户只要打开 app 就应有常驻通知。
        Log.i(TAG, "拉起前台保活服务 (进入软件即常驻)")
        AvelineForegroundServiceV2.start(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 从 savedInstanceState 恢复 deepLink,解决进程被杀后 deepLink 丢失问题
        savedInstanceState?.getString(KEY_DEEP_LINK_URI)?.let { uriString ->
            deepLinkState.value = Uri.parse(uriString)
        }

        lifecycleScope.launch {
            val discovered = serverDiscoveryManager.discoverServer()
            if (discovered != null) {
                Log.i("MainActivity", "自动发现服务器: $discovered")
                // 发现新服务器后通知前台服务重连
                AvelineForegroundServiceV2.updateBackendUrl(discovered)
            } else {
                Log.w("MainActivity", "未自动发现服务器，使用配置: ${appPreferences.backendUrl}")
            }
        }

        // 进入软件即拉起前台保活服务 (挂出常驻通知维持后台运行), 不依赖任何开关。
        // 拉起前会先确认 POST_NOTIFICATIONS 权限(Android 13+), 未授予则先弹权限申请, 授权后再拉起;
        // 否则通知会被系统静默隐藏(13)或 startForeground 抛异常导致服务被强杀(14), 后台直接失效。
        ensureKeepAliveWithNotificationPermission()
        if (appPreferences.residentModeEnabled) {
            dataSyncManager.startPeriodicSync()
        } else {
            dataSyncManager.stopPeriodicSync()
        }

        syncMobilePushToken()

        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }

        handleDeepLink(intent)

        setContent {
            AvelineTheme {
                AvelineApp(
                    deepLinkState = deepLinkState,
                    onDeepLinkConsumed = { deepLinkState.value = null }
                )
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        // 持久化 deepLink,进程被杀后能恢复
        deepLinkState.value?.let { uri ->
            outState.putString(KEY_DEEP_LINK_URI, uri.toString())
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleDeepLink(intent)
    }

    private fun syncMobilePushToken() {
        try {
            if (com.google.firebase.FirebaseApp.getApps(this).isEmpty()) return

            FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                if (token.isNullOrBlank()) {
                    return@addOnSuccessListener
                }
                lifecycleScope.launch {
                    val payload = buildJsonObject {
                        put("token", token)
                        put("platform", "android")
                        put("user_id", appPreferences.userId)
                        put("user_name", appPreferences.userName)
                    }
                    runCatching {
                        apiService.registerMobilePushToken(payload)
                    }.onFailure { error ->
                        Log.w("MainActivity", "Failed to register FCM token: ${error.message}")
                    }
                }
            }
            .addOnFailureListener { error ->
                Log.w("MainActivity", "Failed to fetch FCM token: ${error.message}")
            }
        } catch (e: Exception) {
            Log.w("MainActivity", "FCM 初始化失败: ${e.message}")
        }
    }

    private fun handleDeepLink(intent: Intent?) {
        intent?.data?.let { uri ->
            if (uri.scheme == "aveline") {
                deepLinkState.value = uri
            }
        }
    }

    companion object {
        private const val KEY_DEEP_LINK_URI = "deepLinkUri"
    }
}

@Composable
fun AvelineApp(
    deepLinkState: State<Uri?>,
    onDeepLinkConsumed: () -> Unit,
    mainViewModel: MainViewModel = hiltViewModel()
) {
    val navController = rememberNavController()
    val drawerState = rememberPullableDrawerState()
    val scope = rememberCoroutineScope()

    val mainUiState by mainViewModel.uiState.collectAsStateWithLifecycle()

    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route ?: Routes.CONVERSATIONS

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                mainViewModel.reconnect()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    val connectionState = when (mainUiState.connectionState) {
        WebSocketManager.ConnectionState.CONNECTED -> ConnectionState.CONNECTED
        WebSocketManager.ConnectionState.CONNECTING -> ConnectionState.CONNECTING
        WebSocketManager.ConnectionState.DISCONNECTED -> ConnectionState.DISCONNECTED
    }

    // 呼吸灯实际情绪:关闭自动情绪时用手动选择,否则用后端推送。
    // 用 let 局部持有非空值,避免对 delegate 二次读取的竞态。
    val manualEmotion = mainUiState.manualEmotion
    val effectiveEmotion = if (!mainUiState.autoEmotion && manualEmotion != null) {
        manualEmotion.name.lowercase()
    } else {
        mainUiState.currentEmotion
    }

    val onNavigate: (String) -> Unit = { route ->
        scope.launch {
            drawerState.close()
            val startDestId = navController.graph.startDestinationId
            val isStartDestination = navController.graph.findStartDestination().route == route
            navController.navigate(route) {
                launchSingleTop = true
                // 目标是 startDestination（如"消息"）：popUpTo 回到栈底，
                // 把 CHAT 等子页面弹掉，确保从聊天页点"消息"能真正回到会话列表，
                // 而不是在 CHAT 之上再叠一层（原逻辑会导致点了"没反应"）。
                // 非 startDestination 目标同样 popUpTo 栈底并 saveState，保留返回态。
                popUpTo(startDestId) {
                    saveState = true
                    // startDestination 自身不要 inclusive，否则会把它自己也弹掉再重建
                    inclusive = false
                }
                restoreState = !isStartDestination
            }
        }
    }

    val onMenuClick: () -> Unit = {
        scope.launch {
            drawerState.open()
        }
    }

    val onSessionClick: (String) -> Unit = { sessionId ->
        scope.launch {
            drawerState.close()
            mainViewModel.switchSession(sessionId)
        }
    }

    val onNewSession: () -> Unit = {
        mainViewModel.createSession()
    }

    val onSessionRename: (String, String) -> Unit = { sessionId, newTitle ->
        mainViewModel.renameSession(sessionId, newTitle)
    }

    val onSessionDelete: (String) -> Unit = { sessionId ->
        mainViewModel.deleteSession(sessionId)
    }

    val onSessionPin: (String, Boolean) -> Unit = { sessionId, isPinned ->
        mainViewModel.toggleSessionPin(sessionId, isPinned)
    }

    PullableNavigationDrawer(
        state = drawerState,
        scrimColor = Color(0xCC020617),
        onDismissRequest = {
            scope.launch { drawerState.close() }
        },
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = Color.Transparent,
                drawerContentColor = Color.White,
                modifier = Modifier.fillMaxSize(),
                windowInsets = WindowInsets(0, 0, 0, 0)
            ) {
                DrawerContent(
                    currentRoute = currentRoute,
                    currentEmotion = effectiveEmotion,
                    connectionState = connectionState,
                    sessions = mainUiState.sessions,
                    currentSessionId = mainUiState.currentSessionId,
                    onNavigate = onNavigate,
                    onSessionClick = onSessionClick,
                    onNewSession = onNewSession,
                    onSessionRename = onSessionRename,
                    onSessionDelete = onSessionDelete,
                    onSessionPin = onSessionPin
                )
            }
        }
    ) {
        Box(
            modifier = Modifier.fillMaxSize()
        ) {
            BreathingBackground(
                modifier = Modifier.fillMaxSize(),
                emotion = effectiveEmotion,
                emotionColors = mainUiState.emotionColors,
                backgroundAlpha = 1f
            )
            NavHost(
                navController = navController,
                startDestination = Routes.CONVERSATIONS
            ) {
                avelineNavGraph(
                    navController = navController,
                    onMenuClick = onMenuClick
                )
            }

        }
    }

    // 侧边栏打开时拦截系统返回键：收起侧边栏，而不是让 NavHost 弹出返回栈退出当前页面。
    //
    // 不能依赖 BackHandler 组合顺序，也不能用 NavController.enableOnBackPressed(false)：
    // - Compose NavHost（navigation-compose 2.7.6）的返回处理是它自己内部的
    //   BackHandler(currentBackStack.size > 1) { navController.popBackStack() }，
    //   注册在 NavHost 的组合作用域内；OnBackPressedDispatcher 是 LIFO（后注册者优先），
    //   只要 NavHost 的回调比抽屉回调更晚注册/重新注册，返回键就会被它抢先消费。
    // - NavController.enableOnBackPressed 控制的 onBackPressedCallback 是给 Fragment/View
    //   NavHost 用的，Compose NavHost 从不调用 setOnBackPressedDispatcher，该回调根本没注册，
    //   调用 enableOnBackPressed 毫无作用。
    // 因此这里改为：抽屉打开时把返回回调动态注册到 dispatcher 末尾（此刻注册必然晚于 NavHost
    // 内部所有返回回调），返回键必先走到收起侧边栏的逻辑；抽屉关闭后移除回调，放行 NavHost。
    val backDispatcher = checkNotNull(LocalOnBackPressedDispatcherOwner.current) {
        "缺少 LocalOnBackPressedDispatcherOwner，无法拦截返回键收起侧边栏"
    }.onBackPressedDispatcher
    val drawerBackCallback = remember {
        object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() {
                scope.launch { drawerState.close() }
            }
        }
    }
    LaunchedEffect(drawerState.isVisible) {
        if (drawerState.isVisible) {
            // 先移除再添加，确保排到 dispatcher 末尾（后注册者优先消费）
            drawerBackCallback.remove()
            drawerBackCallback.isEnabled = true
            backDispatcher.addCallback(lifecycleOwner, drawerBackCallback)
        } else {
            drawerBackCallback.remove()
        }
    }
    DisposableEffect(lifecycleOwner) {
        onDispose { drawerBackCallback.remove() }
    }

    // 用 deepLinkState.value 作为 key,deepLink 变化时重新触发导航
    // 修复 P0-26:原 LaunchedEffect(Unit) 只在首次组合时触发,
    // onNewIntent 设置新 deepLink 后 AvelineApp 无法感知;改为观察 State 后能响应变化
    val deepLink = deepLinkState.value
    LaunchedEffect(deepLink) {
        deepLink?.let { uri ->
            // 跳转到指定角色/会话的聊天页: 先切换会话, 再进入聊天页
            if (uri.scheme == "aveline" && uri.host == "chat") {
                val sessionId = uri.getQueryParameter("session_id")
                if (!sessionId.isNullOrBlank()) {
                    mainViewModel.switchSession(sessionId)
                }
            }
            val route = parseDeepLink(uri)
            navController.navigate(route)
            onDeepLinkConsumed()
        }
    }
}

private fun parseDeepLink(uri: Uri): String {
    return when (uri.host) {
        "chat" -> {
            val text = uri.getQueryParameter("text")
            if (text != null) {
                "${Routes.CHAT}?text=${java.net.URLEncoder.encode(text, "UTF-8")}"
            } else {
                Routes.CHAT
            }
        }
        "conversations" -> Routes.CONVERSATIONS
        // 新 7 单元路由
        "companion" -> Routes.COMPANION
        "life" -> Routes.LIFE
        // 兼容旧版圈子深链；圈子页面已移除，旧链接回到消息主页。
        "circle" -> Routes.CONVERSATIONS
        "food" -> Routes.FOOD
        "settings" -> Routes.SETTINGS
        "wellbeing" -> Routes.WELLBEING
        "study" -> Routes.STUDY
        // 旧深链兼容映射(已合并的单元重定向到新路由)
        "status" -> Routes.COMPANION   // 状态 -> Companion
        "memory" -> Routes.COMPANION   // 记忆 -> Companion
        "persona" -> Routes.COMPANION  // 人设 -> Companion
        "daily" -> Routes.LIFE         // 日常 -> Life
        "shop" -> Routes.FOOD          // 商店 -> Food
        "plugins" -> Routes.SETTINGS   // 插件 -> Settings
        "tools" -> Routes.SETTINGS     // 工具 -> Settings
        else -> Routes.CONVERSATIONS   // 默认进会话列表（主页）
    }
}
