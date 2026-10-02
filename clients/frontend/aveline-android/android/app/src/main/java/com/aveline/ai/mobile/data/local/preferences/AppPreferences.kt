package com.aveline.ai.mobile.data.local.preferences

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.utils.BackendAddressRules
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Wrapper class for SharedPreferences to manage app-level settings and preferences.
 * 
 * This class provides type-safe access to stored preferences with default values.
 * Uses EncryptedSharedPreferences for sensitive data (access token).
 * 
 * Requirements: 17.2, 23.1, 24.2
 */
@Singleton
class AppPreferences @Inject constructor(
    @ApplicationContext context: Context
) {
    private val prefs: SharedPreferences = context.getSharedPreferences(
        PREFS_NAME,
        Context.MODE_PRIVATE
    )
    
    // Encrypted preferences for sensitive data
    private val encryptedPrefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        
        EncryptedSharedPreferences.create(
            context,
            ENCRYPTED_PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }
    
    /**
     * [effectiveBackendUrl] 的响应式视图。
     *
     * SharedPreferences 本身不可观察，Compose 里直接读 effectiveBackendUrl 不会在通道切换时
     * 触发重组 —— 表现就是「从局域网切到公网后，聊天里已有的图片仍然去连那个已经不存在的
     * 局域网地址」。媒体 URL 解析必须观察这个 Flow，把它作为重新解析的触发条件。
     */
    private val _effectiveBackendUrlFlow = MutableStateFlow("")

    val effectiveBackendUrlFlow: StateFlow<String> = _effectiveBackendUrlFlow.asStateFlow()

    /** 四个地址槽位任一变化后同步一次响应式视图。 */
    private fun refreshEndpointFlow() {
        _effectiveBackendUrlFlow.value = effectiveBackendUrl
    }

    init {
        // 把「单一 backendUrl + 手动切换 Tunnel」迁移成「局域网/组网/公网多槽位 + 运行时裁决」。
        // 必须在读取 backendUrl 的任何逻辑之前执行，否则老用户升级后会因为槽位为空而连不上。
        migrateToDualEndpointIfNeeded()
        // V3 读的是 V2 刚写好的 activeUrl，顺序不能反
        promoteVpnSlotIfNeeded()
        refreshEndpointFlow()
    }

    /**
     * 手动锁定的后端地址（优先级最高，非空时不做任何探测，直接用）。
     *
     * 留空 = 自动模式，由 EndpointResolver 在 [lanUrl] / [tunnelUrl] 之间裁决。
     * 注意语义与旧版不同：旧版这里是「当前正在用的地址」，现在它只表达「用户强制指定」。
     */
    var backendUrl: String
        get() = prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL) ?: DEFAULT_BACKEND_URL
        // 异步落盘,避免主线程同步 IO 卡顿
        set(value) {
            prefs.edit().putString(KEY_BACKEND_URL, value).apply()
            refreshEndpointFlow()
        }

    /**
     * 局域网后端地址（首选通道）。
     *
     * 由自动发现（UDP 广播 / 网段扫描）或用户在设置页手填；留空表示没有局域网候选。
     * 默认值预填家中后端地址（含端口 8000），新装免配置；用户可清空（清空后保存的
     * 空串会显式落盘，不会回弹成默认值）。
     * 例: http://192.0.2.1:8000
     */
    var lanUrl: String
        get() = prefs.getString(KEY_LAN_URL, DEFAULT_LAN_URL) ?: DEFAULT_LAN_URL
        set(value) {
            prefs.edit().putString(KEY_LAN_URL, value).apply()
            refreshEndpointFlow()
        }

    /**
     * 当前生效的后端地址（EndpointResolver 的裁决结果，持久化以支撑冷启动）。
     *
     * 不要直接读它 —— 冷启动尚未探测时它可能为空或过期，消费方一律读
     * [effectiveBackendUrl]，由后者兜底。
     */
    var activeUrl: String
        get() = prefs.getString(KEY_ACTIVE_URL, "") ?: ""
        set(value) {
            prefs.edit().putString(KEY_ACTIVE_URL, value).apply()
            refreshEndpointFlow()
        }

    /**
     * 所有网络消费方（REST 拦截器 / WebSocket / 媒体 URL / 上传）读取的唯一入口。
     *
     * 优先级：手动锁定 > 裁决结果 > 局域网 > 组网 > 公网。
     * 后四级是为了「探测还没跑完」的窗口期也能连上：进程刚起来时 activeUrl 可能是空
     * 或上次的旧值，用槽位兜底总比拿空地址直接失败好。
     * 组网排在公网之前：两条都是远程通道，但组网是点对点直连，比绕公网隧道更稳。
     */
    val effectiveBackendUrl: String
        get() = backendUrl.trim()
            .ifEmpty { activeUrl.trim() }
            .ifEmpty { lanUrl.trim() }
            .ifEmpty { vpnUrl.trim() }
            .ifEmpty { tunnelUrl.trim() }

    /**
     * Cloudflare Tunnel 备用域名 (公网入口, 外出时用)。
     * 例: https://ai.example.icu
     * 留空表示未配置。
     */
    var tunnelUrl: String
        get() = prefs.getString(KEY_TUNNEL_URL, DEFAULT_TUNNEL_URL) ?: DEFAULT_TUNNEL_URL
        set(value) {
            prefs.edit().putString(KEY_TUNNEL_URL, value).apply()
            refreshEndpointFlow()
        }

    /**
     * 组网通道地址（Tailscale / WireGuard 等点对点 VPN 的后端入口）。
     *
     * 与 [tunnelUrl] 是**并存的两条远程通道**，不是互斥的开关：
     * - 本槽位是点对点直连（手机开 Tailscale 后直达电脑的 100.x 地址），不经公网边缘，
     *   延迟低且不受 Cloudflare 隧道抖动影响；
     * - [tunnelUrl] 是公网域名兜底，手机端没开组网 / 组网被系统杀掉时仍然可用。
     *
     * 裁决顺序见 EndpointResolver：出门时本槽位优先于 [tunnelUrl]，两者都探不通才降级。
     * 例: http://100.64.0.1:8000
     * 留空表示未启用组网通道（此时行为与加这个槽位之前完全一致）。
     */
    var vpnUrl: String
        get() = prefs.getString(KEY_VPN_URL, DEFAULT_VPN_URL) ?: DEFAULT_VPN_URL
        set(value) {
            prefs.edit().putString(KEY_VPN_URL, value).apply()
            refreshEndpointFlow()
        }

    /**
     * [已废弃] 旧版「是否正在走 Tunnel」标记。
     *
     * 旧实现靠它 + [lanUrlBackup] 手动互斥切换；现在由 EndpointResolver 自动裁决，
     * 不再读写。保留键值仅为了迁移和回滚安全。
     */
    @Deprecated("改用 EndpointResolver 自动裁决")
    var isUsingTunnel: Boolean
        get() = prefs.getBoolean(KEY_IS_USING_TUNNEL, DEFAULT_IS_USING_TUNNEL)
        set(value) { prefs.edit().putBoolean(KEY_IS_USING_TUNNEL, value).apply() }

    /**
     * [已废弃] 旧版内网地址备份（切到 tunnel 时保存，切回时恢复）。
     *
     * 只在 [migrateToDualEndpointIfNeeded] 里读一次，把备份还原进 [lanUrl]；
     * 新代码不要再读写它。
     */
    @Deprecated("改用 lanUrl 槽位")
    var lanUrlBackup: String
        get() = prefs.getString(KEY_LAN_URL_BACKUP, "") ?: ""
        set(value) { prefs.edit().putString(KEY_LAN_URL_BACKUP, value).apply() }

    var userId: String
        get() = prefs.getString(KEY_USER_ID, DEFAULT_USER_ID) ?: DEFAULT_USER_ID
        set(value) { prefs.edit().putString(KEY_USER_ID, value).apply() }

    var userName: String
        get() = prefs.getString(KEY_USER_NAME, DEFAULT_USER_NAME) ?: DEFAULT_USER_NAME
        set(value) { prefs.edit().putString(KEY_USER_NAME, value).apply() }

    var accessToken: String
        get() = encryptedPrefs.getString(KEY_ACCESS_TOKEN, "") ?: ""
        set(value) { encryptedPrefs.edit().putString(KEY_ACCESS_TOKEN, value).apply() }
    
    /**
     * Selected voice ID for TTS engine.
     * Default: empty string (use backend default)
     */
    var selectedVoiceId: String
        get() = prefs.getString(KEY_SELECTED_VOICE_ID, DEFAULT_VOICE_ID) ?: DEFAULT_VOICE_ID
        set(value) = prefs.edit().putString(KEY_SELECTED_VOICE_ID, value).apply()
    
    /**
     * Selected AI model ID.
     * Default: empty string (use backend default)
     */
    var selectedModelId: String
        get() = prefs.getString(KEY_SELECTED_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        set(value) = prefs.edit().putString(KEY_SELECTED_MODEL_ID, value).apply()

    /** 保存完整调用路由，聊天请求不能把展示名称当作模型路由。 */
    var selectedModelRoute: String
        get() = prefs.getString("selected_model_route", "").orEmpty()
        set(value) = prefs.edit().putString("selected_model_route", value).apply()

    /**
     * 当前 persona 的默认模型路由，来自后端 persona API 的 default_model
     * （权威配置 model_routing.chat_models，与 QQ 端同源）。
     *
     * 只在用户没有手动选模型时生效；切换 persona 时会被重写，
     * 目标 persona 没配默认模型时清空（避免沿用上一个 persona 的模型导致串模型）。
     */
    var personaDefaultModelRoute: String
        get() = prefs.getString("persona_default_model_route", "").orEmpty()
        set(value) = prefs.edit().putString("persona_default_model_route", value).apply()

    /** 每个角色独立记住用户确认选择的人设版本。 */
    fun getSelectedPersona(role: String): String? =
        prefs.getString("selected_persona:$role", null)?.takeIf { it.isNotBlank() }

    fun setSelectedPersona(role: String, filename: String) {
        if (role.isBlank() || filename.isBlank()) return
        prefs.edit().putString("selected_persona:$role", filename).apply()
    }

    /**
     * 每个角色独立记住用户手选的音色名（app.yaml voice_map 里的角色名，如 "Ye"）。
     *
     * 优先于后端下发的 persona 默认音色 [personaDefaultVoice]：用户一旦手选就不再被覆盖，
     * 没手选时返回 null，由 TTS 回退到角色默认音色。
     */
    fun getPersonaVoice(filename: String): String? =
        prefs.getString("persona_voice:$filename", null)?.takeIf { it.isNotBlank() }

    /** 保存/清空某角色的手选音色（传空串 = 清除覆盖，恢复跟随后端默认）。 */
    fun setPersonaVoice(filename: String, voiceName: String) {
        if (filename.isBlank()) return
        prefs.edit().putString("persona_voice:$filename", voiceName).apply()
    }
    
    /**
     * Response length preference.
     * Default: NORMAL
     */
    var responseLength: ResponseLength
        get() = try {
            ResponseLength.valueOf(
                prefs.getString(KEY_RESPONSE_LENGTH, DEFAULT_RESPONSE_LENGTH.name) ?: DEFAULT_RESPONSE_LENGTH.name
            )
        } catch (e: Exception) {
            DEFAULT_RESPONSE_LENGTH
        }
        set(value) = prefs.edit().putString(KEY_RESPONSE_LENGTH, value.name).apply()
    
    /**
     * Breathing animation rate multiplier (0.5x - 2.0x).
     * Default: 1.0
     */
    var breathingRate: Float
        get() = prefs.getFloat(KEY_BREATHING_RATE, DEFAULT_BREATHING_RATE)
        set(value) = prefs.edit().putFloat(KEY_BREATHING_RATE, value).apply()
    
    /**
     * Manual emotion setting.
     * Null means auto emotion is enabled.
     */
    var manualEmotion: EmotionType?
        get() = try {
            val value = prefs.getString(KEY_MANUAL_EMOTION, null)
            if (value != null) EmotionType.valueOf(value) else null
        } catch (e: Exception) {
            null
        }
        set(value) = prefs.edit().putString(KEY_MANUAL_EMOTION, value?.name).apply()
    
    /**
     * Auto emotion enabled flag.
     * When true, emotion is determined automatically by AI.
     * Default: true
     */
    var autoEmotion: Boolean
        get() = prefs.getBoolean(KEY_AUTO_EMOTION, DEFAULT_AUTO_EMOTION)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_EMOTION, value).apply()
    
    /**
     * 当前激活的 session ID（null 表示还没有会话）。
     *
     * 注意：写入时会同步推送到 [currentSessionIdFlow]，让依赖"当前会话"的
     * Flow 链（如聊天消息列表）能感知切换。历史实现里各处读取的是一次性快照，
     * 切换角色后消息列表不会重新加载，导致所有角色都显示同一份聊天记录。
     */
    var currentSessionId: String?
        get() = prefs.getString(KEY_CURRENT_SESSION_ID, null)
        set(value) {
            prefs.edit().putString(KEY_CURRENT_SESSION_ID, value).apply()
            _currentSessionIdFlow.value = value
        }

    /** 内部可变流，初值取自已落盘的值。 */
    private val _currentSessionIdFlow: MutableStateFlow<String?> =
        MutableStateFlow(prefs.getString(KEY_CURRENT_SESSION_ID, null))

    /**
     * 当前 session ID 的响应式视图，供仓储/ViewModel 监听会话切换。
     */
    val currentSessionIdFlow: StateFlow<String?> = _currentSessionIdFlow.asStateFlow()
    
    /**
     * Auto TTS enabled flag.
     * When true, AI responses are automatically read aloud.
     * Default: false
     */
    var autoTtsEnabled: Boolean
        get() = prefs.getBoolean(KEY_AUTO_TTS_ENABLED, DEFAULT_AUTO_TTS_ENABLED)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_TTS_ENABLED, value).apply()
    
    /**
     * Resident mode enabled flag.
     * When true, foreground service keeps app running in background.
     * Default: false
     */
    var residentModeEnabled: Boolean
        get() = prefs.getBoolean(KEY_RESIDENT_MODE_ENABLED, DEFAULT_RESIDENT_MODE_ENABLED)
        set(value) = prefs.edit().putBoolean(KEY_RESIDENT_MODE_ENABLED, value).apply()

    /**
     * ASR (语音识别) 提供方
     * - "auto": 优先 sherpa_ncnn 端侧, 不可用时降级 system (默认)
     * - "sherpa_ncnn": 强制用 sherpa-ncnn 端侧识别 (不依赖云/GMS)
     * - "system": 用 Android 系统 SpeechRecognizer (依赖 GMS, 国行不可用)
     * - "backend": 录音上传到后端 faster-whisper 识别 (需网络)
     */
    var asrProvider: String
        get() = prefs.getString(KEY_ASR_PROVIDER, DEFAULT_ASR_PROVIDER) ?: DEFAULT_ASR_PROVIDER
        set(value) = prefs.edit().putString(KEY_ASR_PROVIDER, value).apply()

    /**
     * 语音助手总开关（App 之外的悬浮入口）。
     *
     * **默认关闭**：悬浮窗整套链路（窗口 + 前台服务 + 权限引导）已经做完并保留在代码里，
     * 但后端对话还是回声桩、胶囊也只有语音入口没有文字输入，开着没什么用，
     * 所以默认不显示，让它静静躺着。
     *
     * 要启用只需把 [DEFAULT_ASSISTANT_CAPSULE_ENABLED] 改回 true，
     * 或者（推荐）在设置页加一个开关读这个字段 —— 开关一打开，
     * MainActivity 下次进前台就会拉起 AssistantOverlayService。
     *
     * 注意它控制的是**跨应用悬浮窗**：App 自己在前台时会自动隐藏
     * （见 AssistantOverlayService 对 AppForegroundTracker 的消费），
     * 所以即便打开也不会挡 App 内的视野。
     */
    var assistantCapsuleEnabled: Boolean
        get() = prefs.getBoolean(KEY_ASSISTANT_CAPSULE_ENABLED, DEFAULT_ASSISTANT_CAPSULE_ENABLED)
        set(value) = prefs.edit().putBoolean(KEY_ASSISTANT_CAPSULE_ENABLED, value).apply()

    /**
     * 助手悬浮窗左上角的屏幕坐标（像素，窗口 gravity = TOP|START）。
     *
     * 默认 -1 表示「还没摆过」，由 Service 用默认位置（屏幕底部居中）初始化。
     * 存绝对像素而不是比例：悬浮窗是系统窗口，LayoutParams 本来就用像素，
     * 换算成比例再算回来只会引入误差、还得处理转屏。
     */
    var assistantOverlayX: Int
        get() = prefs.getInt(KEY_ASSISTANT_OVERLAY_X, DEFAULT_ASSISTANT_OVERLAY_POSITION)
        set(value) = prefs.edit().putInt(KEY_ASSISTANT_OVERLAY_X, value).apply()

    var assistantOverlayY: Int
        get() = prefs.getInt(KEY_ASSISTANT_OVERLAY_Y, DEFAULT_ASSISTANT_OVERLAY_POSITION)
        set(value) = prefs.edit().putInt(KEY_ASSISTANT_OVERLAY_Y, value).apply()

    /**
     * 上次引导用户去开「显示在其他应用上层」的时间戳（0 = 从没引导过）。
     *
     * 这个权限没有应用内弹窗，只能跳系统设置页手动开；靠这个时间戳做去重，
     * 免得用户每次进 App 都被扔进设置页。
     */
    var assistantOverlayPromptedAt: Long
        get() = prefs.getLong(KEY_ASSISTANT_OVERLAY_PROMPTED_AT, DEFAULT_ASSISTANT_OVERLAY_PROMPTED_AT)
        set(value) = prefs.edit().putLong(KEY_ASSISTANT_OVERLAY_PROMPTED_AT, value).apply()
    
    /**
     * Last context synchronization timestamp.
     * Used to track when device context was last synced to backend.
     * Default: 0 (never synced)
     */
    var lastSyncTimestamp: Long
        get() = prefs.getLong(KEY_LAST_SYNC_TIMESTAMP, DEFAULT_LAST_SYNC_TIMESTAMP)
        set(value) = prefs.edit().putLong(KEY_LAST_SYNC_TIMESTAMP, value).apply()
    
    /**
     * Context sync enabled flag.
     * When true, device context is periodically synced to backend.
     * Default: true
     */
    var isContextSyncEnabled: Boolean
        get() = prefs.getBoolean(KEY_CONTEXT_SYNC_ENABLED, DEFAULT_CONTEXT_SYNC_ENABLED)
        set(value) = prefs.edit().putBoolean(KEY_CONTEXT_SYNC_ENABLED, value).apply()
    
    /**
     * Haptic feedback enabled flag.
     * When true, haptic feedback is triggered for UI interactions.
     * Default: true
     */
    var hapticFeedbackEnabled: Boolean
        get() = prefs.getBoolean(KEY_HAPTIC_FEEDBACK_ENABLED, DEFAULT_HAPTIC_FEEDBACK_ENABLED)
        set(value) = prefs.edit().putBoolean(KEY_HAPTIC_FEEDBACK_ENABLED, value).apply()
    
    /**
     * Language code for app localization.
     * Default: empty string (follow system)
     */
    var languageCode: String
        get() = prefs.getString(KEY_LANGUAGE_CODE, DEFAULT_LANGUAGE_CODE) ?: DEFAULT_LANGUAGE_CODE
        set(value) = prefs.edit().putString(KEY_LANGUAGE_CODE, value).apply()
    
    // ==================== 数字健康: 应用使用时长限额 ====================
    
    /**
     * [已废弃] 旧版每日限额: "package_name=limit_ms" 逗号拼接。
     * 仅用于一次性迁移到 [appLimitPolicies], 迁移完成后不再读写。
     */
    @Deprecated("改用 appLimitPolicies")
    private var legacyUsageLimits: String
        get() = prefs.getString(KEY_APP_USAGE_LIMITS, DEFAULT_APP_USAGE_LIMITS) ?: DEFAULT_APP_USAGE_LIMITS
        set(value) = prefs.edit().putString(KEY_APP_USAGE_LIMITS, value).apply()
    
    /**
     * 数字健康策略表, 格式: "pkg=每日ms:单次ms:间隔ms:冷却ms" 逗号拼接。
     *
     * 例: "com.ss.android.ugc.aweme=3600000:600000:120000:300000" 表示
     * 抖音每天 1 小时、单次 10 分钟、离开 2 分钟算作结束、超时休息 5 分钟。
     * 由 DataSyncWorker (sync_context 的 app_policies) 与数字健康页面写入,
     * SessionLimiter 读取并判定。
     */
    var appLimitPolicies: String
        get() = prefs.getString(KEY_APP_LIMIT_POLICIES, DEFAULT_APP_LIMIT_POLICIES)
            ?: DEFAULT_APP_LIMIT_POLICIES
        set(value) = prefs.edit().putString(KEY_APP_LIMIT_POLICIES, value).apply()

    /**
     * 各应用的会话状态机快照, 格式:
     * "pkg=day|startMs|baselineDailyMs|lastForegroundMs|blockedUntilMs|dailyBlockedDay" 逗号拼接。
     *
     * 跨进程持久化: 进程被回收或重启后仍能恢复"本次已用了多久""是否还在冷却"。
     */
    var appSessionStates: String
        get() = prefs.getString(KEY_APP_SESSION_STATES, DEFAULT_APP_SESSION_STATES)
            ?: DEFAULT_APP_SESSION_STATES
        set(value) = prefs.edit().putString(KEY_APP_SESSION_STATES, value).apply()

    /**
     * 限额通知的发送记录, 格式:
     * "pkg=day|count|lastAtMs|dailyNotified|dailyLimitMs|sessionKey" 逗号拼接。
     *
     * 用于抑制"同一应用同一天反复弹限额通知": 进程被回收或重启后依然记得
     * 今天已经提醒过 (见 LimitNoticeTracker)。跨天自动失效。
     */
    var appLimitNotices: String
        get() = prefs.getString(KEY_APP_LIMIT_NOTICES, DEFAULT_APP_LIMIT_NOTICES)
            ?: DEFAULT_APP_LIMIT_NOTICES
        set(value) = prefs.edit().putString(KEY_APP_LIMIT_NOTICES, value).apply()

    /**
     * [已废弃] 旧版一次性会话 cap: "package_name=session_ms" 逗号拼接。
     * 新版语义是"每次连续使用最多多久"而非"从配置时刻起累计", 迁移后不再读写。
     */
    @Deprecated("改用 appLimitPolicies 的 sessionLimitMs")
    private var legacySessionCaps: String
        get() = prefs.getString(KEY_APP_SESSION_CAPS, DEFAULT_APP_SESSION_CAPS) ?: DEFAULT_APP_SESSION_CAPS
        set(value) = prefs.edit().putString(KEY_APP_SESSION_CAPS, value).apply()

    /**
     * 把旧版"每日限额 + 一次性会话 cap"迁移到新版策略表。
     *
     * 仅在 [appLimitPolicies] 从未写入过时执行一次, 之后一律返回 false。
     * 目的是避免 App 升级后、下一次 15 分钟同步之前出现"限额真空期"。
     *
     * @return 本次是否真的迁移了数据
     */
    @Suppress("DEPRECATION")
    fun migrateLegacyUsageLimits(): Boolean {
        if (prefs.contains(KEY_APP_LIMIT_POLICIES)) return false
        val codec = com.aveline.ai.mobile.services.wellbeing.AppLimitPolicyCodec
        val migrated = codec.fromLegacy(
            dailyLimits = parseLimitPairs(legacyUsageLimits),
            sessionCaps = parseLimitPairs(legacySessionCaps),
        )
        if (migrated.isEmpty()) return false
        appLimitPolicies = codec.format(migrated)
        return true
    }

    /**
     * 一次性迁移：单一 [backendUrl] → 局域网 / 组网 / 公网多槽位。
     *
     * 迁移前的字段关系：
     * - 用户手填或自动发现的「当前地址」存在 backendUrl；
     * - 点过「切换 Tunnel」时，原内网地址被备份进 lanUrlBackup，backendUrl 变成 tunnel 域名；
     * - tunnelUrl 一直是独立字段，没被切换逻辑改过，所以直接沿用。
     *
     * 迁移规则：
     * 1. 局域网槽位：优先取 lanUrlBackup（说明用户切换过 Tunnel，备份的就是内网地址）；
     *    否则若 backendUrl 看起来是内网地址，就认它；凑不出候选时预填 [DEFAULT_LAN_URL]；
     * 2. 组网槽位：旧地址是组网点对点地址（CGNAT 段）就认它。不认的话这条通道等于没配 ——
     *    旧地址只落进 activeUrl，第一次裁决就被公网域名覆盖，而 [EndpointResolver] 不会去猜
     *    组网地址，用户明明一直靠它连、升级后却只会走公网；
     * 3. 公网槽位：tunnelUrl 原样保留；
     * 4. 手动锁定槽位：一律留空（= 自动）。局域网槽位有默认值兜底不会为空，
     *    旧地址也已写入 activeUrl 冷启动兜底；
     * 5. activeUrl 写入旧地址，让冷启动立刻按老行为连上，探测成功后再纠正。
     *
     * 只在第一次执行（由 KEY_ENDPOINT_SCHEMA_V2 标记），之后一律跳过。
     */
    @Suppress("DEPRECATION")
    private fun migrateToDualEndpointIfNeeded() {
        if (prefs.getBoolean(KEY_ENDPOINT_SCHEMA_V2, false)) return

        val legacyActive = backendUrl.trim()
        val legacyLanBackup = lanUrlBackup.trim()

        val lan = when {
            legacyLanBackup.isNotEmpty() -> legacyLanBackup
            isLikelyLanUrl(legacyActive) -> legacyActive
            // 迁移时凑不出局域网候选就预填默认地址。这里必须显式写入默认值：
            // 若落盘空串，后续 getString 会返回 "" 而不是回落 DEFAULT_LAN_URL。
            else -> DEFAULT_LAN_URL
        }
        val vpn = if (BackendAddressRules.isVpnHost(legacyActive)) legacyActive else ""
        // lan 已由 DEFAULT_LAN_URL 兜底恒非空，旧版「两槽位皆空才把地址锁进手动位」
        // 不再可能；旧地址已写入 activeUrl 冷启动兜底，手动锁定位一律留空（= 自动）。
        val manual = ""

        prefs.edit()
            .putString(KEY_LAN_URL, lan)
            .putString(KEY_VPN_URL, vpn)
            .putString(KEY_BACKEND_URL, manual)
            .putString(KEY_ACTIVE_URL, legacyActive)
            .putBoolean(KEY_ENDPOINT_SCHEMA_V2, true)
            .apply()
    }

    /**
     * 一次性迁移（V3）：把用户已经填过的组网地址升格进 [vpnUrl] 槽位。
     *
     * 背景：组网槽位是后加的，默认空串，而「留空 = 未启用这条通道」是刻意的语义 ——
     * [EndpointResolver] 不会去猜地址。但老用户里有一批人是把 Tailscale 的 100.x 直接填在
     * 「手动锁定」里用的，于是在自动模式下会出现「明明开着组网，却一直连公网域名」：
     * 组网槽位是空的，局域网又只在 WiFi 下才排在前面，一出门就只剩公网域名这一档。
     *
     * 这里把这类地址**复制**进组网槽位，但**不碰手动锁定本身** —— 用户明确锁定的行为不该被
     * 后台迁移悄悄改掉。他想进自动模式，自己清空「手动锁定」那格即可，清空后立刻就能用上组网。
     *
     * 只在第一次执行（由 KEY_ENDPOINT_SCHEMA_V3 标记）。
     */
    private fun promoteVpnSlotIfNeeded() {
        if (prefs.getBoolean(KEY_ENDPOINT_SCHEMA_V3, false)) return
        if (vpnUrl.trim().isNotEmpty()) {
            // 用户自己填过就别动
            prefs.edit().putBoolean(KEY_ENDPOINT_SCHEMA_V3, true).apply()
            return
        }
        // 手动锁定优先（那是用户实际在用的组网地址），其次是上次的裁决结果
        val candidate = listOf(backendUrl, activeUrl)
            .map { it.trim() }
            .firstOrNull { BackendAddressRules.isVpnHost(it) }
            .orEmpty()

        prefs.edit()
            .putString(KEY_VPN_URL, candidate)
            .putBoolean(KEY_ENDPOINT_SCHEMA_V3, true)
            .apply()
    }

    /**
     * 粗略判断地址是否指向局域网（私网 IPv4 / localhost / .local）。
     *
     * 只服务于上面那次性迁移（区分「原来存的是内网地址还是公网域名」），
     * 不参与运行时裁决 —— 运行时一律以真实探测结果为准，不靠地址长相猜。
     * 判据与运行时兜底共用 [BackendAddressRules]，避免两处判据分叉。
     */
    private fun isLikelyLanUrl(raw: String): Boolean = BackendAddressRules.isLanOnlyHost(raw)

    /** 解析 "pkg1=ms1,pkg2=ms2" 为 map (迁移旧配置用)。 */
    private fun parseLimitPairs(raw: String): Map<String, Long> = buildMap {
        raw.split(',').forEach { pair ->
            val separator = pair.indexOf('=')
            if (separator <= 0) return@forEach
            val packageName = pair.substring(0, separator).trim()
            val value = pair.substring(separator + 1).trim().toLongOrNull() ?: return@forEach
            if (packageName.isNotBlank() && value > 0) put(packageName, value)
        }
    }

    /**
     * 前台服务配额冷却截止时刻 (epoch 毫秒), 0 表示不在冷却中。
     *
     * Android 15 (targetSdk 35) 对 dataSync 前台服务施加"24 小时内累计 6 小时"配额,
     * 配额耗尽后系统会回调 Service.onTimeout()。守护服务会在此期间降级为普通后台服务
     * (保留常驻通知), 到点前不再重复尝试挂前台, 避免"超时 → 重启 → 再超时"的死循环。
     * 冷却跨进程保存, 进程被回收后也不会立刻把配额打满。
     */
    var fgsQuotaResumeAtMs: Long
        get() = prefs.getLong(KEY_FGS_QUOTA_RESUME_AT, DEFAULT_FGS_QUOTA_RESUME_AT)
        set(value) = prefs.edit().putLong(KEY_FGS_QUOTA_RESUME_AT, value).apply()
    
    /**
     * Clears all preferences (except encrypted ones for security).
     * Use with caution.
     */
    fun clear() {
        prefs.edit().clear().apply()
    }
    
    /**
     * Clears all preferences including encrypted ones.
     * Use for logout or data reset.
     */
    fun clearAll() {
        prefs.edit().clear().apply()
        encryptedPrefs.edit().clear().apply()
    }
    
    companion object {
        private const val PREFS_NAME = "aveline_preferences"
        private const val ENCRYPTED_PREFS_NAME = "aveline_encrypted_preferences"
        
        // Keys
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_LAN_URL = "lan_url"
        private const val KEY_ACTIVE_URL = "active_url"
        private const val KEY_ENDPOINT_SCHEMA_V2 = "endpoint_schema_v2"
        private const val KEY_ENDPOINT_SCHEMA_V3 = "endpoint_schema_v3"
        private const val KEY_TUNNEL_URL = "tunnel_url"
        private const val KEY_VPN_URL = "vpn_url"
        private const val KEY_IS_USING_TUNNEL = "is_using_tunnel"
        private const val KEY_LAN_URL_BACKUP = "lan_url_backup"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_USER_NAME = "user_name"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_SELECTED_VOICE_ID = "selected_voice_id"
        private const val KEY_SELECTED_MODEL_ID = "selected_model_id"
        private const val KEY_RESPONSE_LENGTH = "response_length"
        private const val KEY_BREATHING_RATE = "breathing_rate"
        private const val KEY_MANUAL_EMOTION = "manual_emotion"
        private const val KEY_AUTO_EMOTION = "auto_emotion"
        private const val KEY_CURRENT_SESSION_ID = "current_session_id"
        private const val KEY_AUTO_TTS_ENABLED = "auto_tts_enabled"
        private const val KEY_RESIDENT_MODE_ENABLED = "resident_mode_enabled"
        private const val KEY_ASR_PROVIDER = "asr_provider"
        private const val KEY_ASSISTANT_CAPSULE_ENABLED = "assistant_capsule_enabled"
        private const val KEY_ASSISTANT_OVERLAY_X = "assistant_overlay_x"
        private const val KEY_ASSISTANT_OVERLAY_Y = "assistant_overlay_y"
        private const val KEY_ASSISTANT_OVERLAY_PROMPTED_AT = "assistant_overlay_prompted_at"
        private const val KEY_LAST_SYNC_TIMESTAMP = "last_sync_timestamp"
        private const val KEY_CONTEXT_SYNC_ENABLED = "context_sync_enabled"
        private const val KEY_HAPTIC_FEEDBACK_ENABLED = "haptic_feedback_enabled"
        private const val KEY_LANGUAGE_CODE = "language_code"
        private const val KEY_APP_USAGE_LIMITS = "app_usage_limits"
        private const val KEY_APP_SESSION_CAPS = "app_session_caps"
        private const val KEY_APP_LIMIT_POLICIES = "app_limit_policies"
        private const val KEY_APP_SESSION_STATES = "app_session_states"
        private const val KEY_APP_LIMIT_NOTICES = "app_limit_notices"
        private const val KEY_FGS_QUOTA_RESUME_AT = "fgs_quota_resume_at"
        
        // Default values
        // 手动锁定 / 公网槽位默认空：留空 = 自动裁决或未配置。
        // 局域网槽位默认预填家中后端地址（含端口），新装免手动配置。
        private const val DEFAULT_BACKEND_URL = ""
        private const val DEFAULT_LAN_URL = "http://192.0.2.1:8000"
        private const val DEFAULT_TUNNEL_URL = ""
        private const val DEFAULT_VPN_URL = ""
        private const val DEFAULT_IS_USING_TUNNEL = false
        private const val DEFAULT_USER_ID = "mobile_user"
        private const val DEFAULT_USER_NAME = "Mobile User"
        private const val DEFAULT_VOICE_ID = ""
        private const val DEFAULT_MODEL_ID = ""
        private val DEFAULT_RESPONSE_LENGTH = ResponseLength.NORMAL
        private const val DEFAULT_BREATHING_RATE = 1.0f
        private const val DEFAULT_AUTO_EMOTION = true
        private const val DEFAULT_AUTO_TTS_ENABLED = false
        private const val DEFAULT_RESIDENT_MODE_ENABLED = false
        private const val DEFAULT_ASR_PROVIDER = "auto"
        /**
         * 悬浮助手默认关闭。
         *
         * 后端对话尚未接入（还是回声桩）、胶囊也还没有文字输入入口，
         * 开着只会白占一个前排服务与一条常驻通知；功能代码全部保留，
         * 改回 true（或加设置页开关）即可启用。
         */
        private const val DEFAULT_ASSISTANT_CAPSULE_ENABLED = false

        /** -1 = 尚未设置过坐标，由 Service 用默认位置（底部居中）初始化。 */
        private const val DEFAULT_ASSISTANT_OVERLAY_POSITION = -1
        private const val DEFAULT_ASSISTANT_OVERLAY_PROMPTED_AT = 0L
        private const val DEFAULT_LAST_SYNC_TIMESTAMP = 0L
        private const val DEFAULT_CONTEXT_SYNC_ENABLED = true
        private const val DEFAULT_HAPTIC_FEEDBACK_ENABLED = true
        private const val DEFAULT_LANGUAGE_CODE = ""
        private const val DEFAULT_APP_USAGE_LIMITS = ""
        private const val DEFAULT_APP_SESSION_CAPS = ""
        private const val DEFAULT_APP_LIMIT_POLICIES = ""
        private const val DEFAULT_APP_SESSION_STATES = ""
        private const val DEFAULT_APP_LIMIT_NOTICES = ""
        private const val DEFAULT_FGS_QUOTA_RESUME_AT = 0L
    }
}
