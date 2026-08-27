package com.aveline.ai.mobile.utils

import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 全局前后台状态追踪器。
 *
 * 用途:健康数据分档同步需要知道 app 整体是否可见,以便动态调整刷新频率。
 * 注意这里判断的是**整个 app 进程**是否在前台,和当前停留在哪个页面无关 ——
 * 用户在聊天页/设置页时同样算前台,不需要打开 Life 页面才刷新。
 *
 * 实现基于 [ProcessLifecycleOwner],它会合并所有 Activity 的生命周期:
 * - 任意 Activity 处于 STARTED 及以上 -> 前台
 * - 全部 Activity 都 STOPPED -> 后台(有约 700ms 去抖,屏幕旋转等重建不会误判)
 *
 * 需在 Application.onCreate 中调用 [init] 完成注册。
 */
object AppForegroundTracker : DefaultLifecycleObserver {

    private val _isForegroundFlow = MutableStateFlow(false)

    /** 前台状态流,供需要响应式监听的场景使用 */
    val isForegroundFlow: StateFlow<Boolean> = _isForegroundFlow.asStateFlow()

    /**
     * 当前 app 是否在前台。
     *
     * 用 @Volatile 保证 Service 的后台协程能立刻读到主线程写入的最新值,
     * 否则可能一直读缓存导致前后台切换后刷新频率不生效。
     */
    @Volatile
    var isForeground: Boolean = false
        private set

    private var initialized = false

    /** 在 Application.onCreate 中调用,注册进程级生命周期监听 */
    fun init() {
        if (initialized) return
        initialized = true
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) {
        isForeground = true
        _isForegroundFlow.value = true
    }

    override fun onStop(owner: LifecycleOwner) {
        isForeground = false
        _isForegroundFlow.value = false
    }
}
