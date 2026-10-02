package com.aveline.ai.mobile.services.assistant

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner

/**
 * 给「挂在 Service 里的 ComposeView」补上它需要的三个宿主角色。
 *
 * 为什么必须写这个：Compose 的 `setContent` 内部要拿 `LocalLifecycleOwner`、
 * `LocalViewModelStoreOwner`、`SavedStateRegistryOwner`，它们平时由
 * ComponentActivity / Fragment 提供。Service 不是这些，直接 `setContent` 会抛
 * `IllegalStateException: ViewTreeLifecycleOwner not found`，
 * `collectAsStateWithLifecycle()` 也会立刻崩。
 *
 * 同时把生命周期真实驱动起来（CREATE → START → RESUME，移除时 DESTROY），
 * 否则 `collectAsStateWithLifecycle` 因为一直停在 INITIALIZED 而永不收集，
 * 表现是「悬浮窗出来了，但状态永远不动」。
 *
 * 只实现三件套的最小契约，不接 `SavedStateHandle`（本场景没有需要恢复的 ViewModel 状态）。
 */
internal class AssistantOverlayLifecycleOwner :
    LifecycleOwner,
    ViewModelStoreOwner,
    SavedStateRegistryOwner {

    private val lifecycleRegistry = LifecycleRegistry(this)
    private val savedStateRegistryController = SavedStateRegistryController.create(this)
    private val store = ViewModelStore()

    override val lifecycle: Lifecycle
        get() = lifecycleRegistry

    override val viewModelStore: ViewModelStore
        get() = store

    override val savedStateRegistry: SavedStateRegistry
        get() = savedStateRegistryController.savedStateRegistry

    /** 对应窗口 addView 的那一刻。必须在 [setContent] 之前调用。 */
    fun onCreate() {
        // 没有需要恢复的 Bundle，传 null 表示「全新会话」
        savedStateRegistryController.performRestore(null)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
    }

    /** 窗口已可见。 */
    fun onStart() {
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
    }

    /** 窗口已进入交互。 */
    fun onResume() {
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
    }

    /** 对应 removeView：走完 STOP → DESTROY，让 Compose 正常释放，避免泄漏 ViewModel。 */
    fun onDestroy() {
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
        store.clear()
    }
}
