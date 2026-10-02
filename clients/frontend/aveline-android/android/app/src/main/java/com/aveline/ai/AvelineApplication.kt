package com.aveline.ai

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import coil.Coil
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.worker.DataSyncManager
import com.aveline.ai.mobile.services.A11yDiagnosis
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.CoilImageLoader
import com.aveline.ai.mobile.utils.CrashHandler
import com.aveline.ai.mobile.utils.PerformanceMonitor
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import javax.inject.Inject

@HiltAndroidApp
class AvelineApplication : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    @Inject
    lateinit var crashHandler: CrashHandler

    @Inject
    lateinit var notificationManager: AvelineNotificationManager

    @Inject
    lateinit var performanceMonitor: PerformanceMonitor

    @Inject
    lateinit var personaLocalMetaRepository: PersonaLocalMetaRepository

    @Inject
    lateinit var coilImageLoader: CoilImageLoader

    @Inject
    lateinit var okHttpClient: OkHttpClient

    @Inject
    lateinit var dataSyncManager: DataSyncManager

    @Inject
    lateinit var endpointResolver: EndpointResolver

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()

    override fun onCreate() {
        super.onCreate()

        // 最前置诊断: 确认 App 进程确实启动过, 以及诊断文件可写。
        // 若 a11y_diagnosis.log 里连这条都没有, 说明进程根本没起来或文件不可写。
        A11yDiagnosis.log(this, "App", "Application.onCreate 进程启动 pid=${android.os.Process.myPid()}")

        performanceMonitor.recordAppStart()

        // 配置 Coil 全局 ImageLoader，复用带鉴权和动态域名的 OkHttpClient，
        // 确保聊天中的网络图片（含 /output、/static 相对路径补全后的绝对地址）
        // 能正常加载，而不是直接显示破图占位（感叹号图标）。
        Coil.setImageLoader(coilImageLoader.createImageLoader(okHttpClient))

        // 注册进程级前后台监听,健康数据同步据此在前台提速
        AppForegroundTracker.init()

        crashHandler.init()

        // 后端通道裁决：进程一起来就注册网络变化监听并做一次初始探测。
        // 放在 Application 而不是只在 Activity 里，是为了兜住「界面还没打开」的场景
        // （开机自启、被推送唤醒、服务先于界面启动），否则那段时间会一直用着上次的旧通道。
        // registerDefaultNetworkCallback 会立刻回调一次当前默认网络，等效于一次启动探测。
        endpointResolver.startMonitoring()

        notificationManager.createNotificationChannels()

        // 三星健康后台同步: 无条件启动, 独立于"常驻模式",
        // 保证心率等生命体征在 App 后台/进程被杀时也能定时刷新 (WorkManager 周期任务)。
        dataSyncManager.startHealthSync()

        // 修复历史脏数据：旧版头像文件名算法会让同长度中文名的 persona
        // （如"Mian"和"Frost"）共用同一个本地头像文件，导致头像串号。
        appScope.launch {
            runCatching { personaLocalMetaRepository.repairDuplicatedAvatars() }
        }

        performanceMonitor.recordAppStartupComplete()
    }
}
