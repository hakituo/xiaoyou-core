package com.aveline.ai.mobile.presentation.components

import android.content.Context
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.utils.MediaUrlResolver
import dagger.hilt.android.EntryPointAccessors

/**
 * 拿到 AppPreferences 单例（读后端地址用）。
 * 复用 MessageBubble 里已声明的 [AppPreferencesEntryPoint]，避免重复声明两套注入点。
 */
private fun Context.videoAppPreferences(): AppPreferences =
    EntryPointAccessors.fromApplication(this, AppPreferencesEntryPoint::class.java)
        .appPreferences()

/** 视频消息最大显示尺寸（dp），与图片消息的最大显示框保持一致。 */
private val VideoMaxWidth = 260.dp
private val VideoMaxHeight = 320.dp

/**
 * 视频/动图（webm、mp4 等）消息气泡。
 *
 * 用途：Coil 图片管线无法渲染视频类媒体（QQ 也不支持 webm），
 * 但自建 App 端需要支持，把 QQ 上做不到的体验补回来——
 * 用户转移阵地后，webm 动图、AI 生成的短视频都应有地方显示。
 *
 * 行为：
 * - 按视频原始宽高比在 max 框内等比显示（与图片消息观感一致，不出现黑边）；
 * - [muted] 为 true 时静音自动循环播放（表情类短视频习惯），
 *   为 false 时保留原声并展示控制条（用户拍摄/相册里发出的普通视频）；
 * - 无控制条时（[showController] 为 false）点击画面即暂停/继续，
 *   否则静音自动播的视频没有任何可交互入口；有控制条时交给控制条自己处理点击；
 * - 跟随页面生命周期暂停/恢复：切后台立即停，回前台只在"离开前正在播"时恢复，
 *   避免后台空转解码，也不会把用户主动暂停的视频强行重新播放。
 *
 * 后续接入 LazyColumn 可见性监听后，再做"滚出视口暂停"。
 *
 * @param videoUrl 视频文件 URL（后端下发的相对路径会自动补全后端地址）
 * @param modifier 外部修饰符（对齐、间距等）
 * @param muted 是否静音自动循环播放
 * @param showController 是否显示播放控制条（静音自动播放的场景不需要）
 * @param maxWidth 视频气泡最大宽度（dp）
 * @param maxHeight 视频气泡最大高度（dp）
 */
@Composable
fun VideoMessageBubble(
    videoUrl: String,
    modifier: Modifier = Modifier,
    muted: Boolean = true,
    showController: Boolean = false,
    maxWidth: Dp = VideoMaxWidth,
    maxHeight: Dp = VideoMaxHeight
) {
    val context = LocalContext.current
    val appPreferences = remember { context.applicationContext.videoAppPreferences() }
    // 与图片同一套规则：生效地址作为重组依赖，通道切换后重新解析（见 MessageBubble 的说明）
    val activeBackend by appPreferences.effectiveBackendUrlFlow.collectAsStateWithLifecycle()
    val resolvedUrl = remember(videoUrl, activeBackend) {
        MediaUrlResolver.resolve(activeBackend, videoUrl)
    }
    val lifecycleOwner = LocalLifecycleOwner.current

    // 解码出首帧前拿不到真实宽高比，先按 max 框占位，拿到后收缩到实际尺寸
    var videoSize by remember(resolvedUrl) { mutableStateOf<Pair<Int, Int>?>(null) }

    val player = remember(resolvedUrl, muted) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(Uri.parse(resolvedUrl)))
            repeatMode = if (muted) Player.REPEAT_MODE_ALL else Player.REPEAT_MODE_OFF
            playWhenReady = muted
            volume = if (muted) 0f else 1f
            addListener(object : Player.Listener {
                override fun onVideoSizeChanged(size: androidx.media3.common.VideoSize) {
                    if (size.width > 0 && size.height > 0) {
                        videoSize = size.width to size.height
                    }
                }
            })
            prepare()
        }
    }

    // 释放资源 + 跟随生命周期暂停/恢复
    DisposableEffect(player, lifecycleOwner) {
        var wasPlaying = player.playWhenReady
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_PAUSE -> {
                    wasPlaying = player.playWhenReady
                    player.pause()
                }
                Lifecycle.Event.ON_RESUME -> {
                    if (wasPlaying) player.play()
                }
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            player.release()
        }
    }

    val (boxWidth, boxHeight) = videoSize?.let { (w, h) ->
        scaledImageDisplaySize(w, h, maxWidth, maxHeight)
    } ?: (maxWidth to maxHeight)

    val clickInteractionSource = remember { MutableInteractionSource() }

    Box(
        modifier = modifier
            .size(boxWidth, boxHeight)
            // 有控制条时点击由控制条自己处理，不能外层再抢一次
            .then(
                if (showController) {
                    Modifier
                } else {
                    Modifier.clickable(
                        interactionSource = clickInteractionSource,
                        indication = null
                    ) {
                        if (player.isPlaying) player.pause() else player.play()
                    }
                }
            ),
        contentAlignment = Alignment.Center
    ) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    this.player = player
                    useController = showController
                    resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                }
            },
            update = { view -> view.useController = showController },
            modifier = Modifier.fillMaxSize()
        )
    }
}
