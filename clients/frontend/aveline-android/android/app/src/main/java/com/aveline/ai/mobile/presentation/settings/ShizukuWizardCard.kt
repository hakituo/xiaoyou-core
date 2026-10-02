package com.aveline.ai.mobile.presentation.settings

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.PrimaryVariant
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import rikka.shizuku.Shizuku

/**
 * Shizuku 状态枚举
 *
 * 4 种状态:
 * - NOT_INSTALLED: 未安装 Shizuku 应用
 * - NOT_RUNNING: 已安装但 binder 未运行 (用户没点启动按钮)
 * - NOT_AUTHORIZED: 已运行但未授权 (用户没在 Shizuku 应用里授权本应用)
 * - AUTHORIZED: 已授权, 可执行 shell 命令
 */
enum class ShizukuState {
    NOT_INSTALLED,
    NOT_RUNNING,
    NOT_AUTHORIZED,
    AUTHORIZED
}

/**
 * Shizuku 权限引导卡片
 *
 * 展示 Shizuku 当前状态, 根据不同状态提供引导按钮:
 * - 未安装 → 跳应用市场安装
 * - 已安装未运行 → 跳 Shizuku 应用启动服务
 * - 已运行未授权 → 调 Shizuku.requestPermission 弹授权框
 * - 已授权 → 显示绿色徽标
 *
 * 状态刷新时机:
 * - 首次进入 Composable
 * - Lifecycle ON_RESUME (从 Shizuku 应用返回时刷新)
 * - 用户点击"刷新状态"按钮
 */
@Composable
fun ShizukuWizardCard(
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var state by remember { mutableStateOf(ShizukuState.NOT_INSTALLED) }
    var refreshKey by remember { mutableStateOf(0) }

    // 检查状态
    fun checkState() {
        state = try {
            // 1. 是否安装 Shizuku 应用 (moe.shizuku.privileged.api)
            val installed = try {
                context.packageManager.getPackageInfo("moe.shizuku.privileged.api", 0)
                true
            } catch (e: PackageManager.NameNotFoundException) {
                false
            }
            if (!installed) {
                ShizukuState.NOT_INSTALLED
            } else if (!Shizuku.pingBinder()) {
                ShizukuState.NOT_RUNNING
            } else if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                ShizukuState.NOT_AUTHORIZED
            } else {
                ShizukuState.AUTHORIZED
            }
        } catch (e: Exception) {
            // 异常时按 NOT_INSTALLED 处理 (避免崩溃)
            ShizukuState.NOT_INSTALLED
        }
    }

    // 首次进入 + refreshKey 变化时检查
    LaunchedEffect(refreshKey) {
        checkState()
    }

    // 监听 Lifecycle ON_RESUME, 从 Shizuku 应用返回时刷新
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                checkState()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    SectionCard(
        title = "Shizuku 高级权限",
        subtitle = "用于强制停止应用、截图屏幕等高级操作",
        icon = Icons.Default.Security,
        modifier = modifier
    ) {
        // 状态行: 图标 + 标题/描述 + 状态徽标
        StatusRow(state = state)

        Spacer(modifier = Modifier.height(12.dp))

        // 引导文案
        Text(
            text = when (state) {
                ShizukuState.NOT_INSTALLED ->
                    "Shizuku 是一个提供 shell 权限的工具, 安装后能让 Aveline 强制停止应用、截图屏幕等。"
                ShizukuState.NOT_RUNNING ->
                    "Shizuku 已安装但服务未启动, 请打开 Shizuku 应用点击「启动」按钮。"
                ShizukuState.NOT_AUTHORIZED ->
                    "Shizuku 服务已运行, 但未授权本应用。请在弹窗中允许。"
                ShizukuState.AUTHORIZED ->
                    "Shizuku 已就绪, 高级设备控制功能可用。"
            },
            style = MaterialTheme.typography.bodySmall,
            color = TextTertiary
        )

        Spacer(modifier = Modifier.height(12.dp))

        // 按钮区: 根据状态显示不同操作
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            when (state) {
                ShizukuState.NOT_INSTALLED -> {
                    Button(
                        onClick = { openMarketForShizuku(context) },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = PrimaryVariant.copy(alpha = 0.5f)
                        )
                    ) {
                        Text("安装 Shizuku")
                    }
                }
                ShizukuState.NOT_RUNNING -> {
                    Button(
                        onClick = { launchShizukuApp(context) },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = PrimaryVariant.copy(alpha = 0.5f)
                        )
                    ) {
                        Text("打开 Shizuku")
                    }
                }
                ShizukuState.NOT_AUTHORIZED -> {
                    Button(
                        onClick = { requestShizukuPermission() },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = PrimaryVariant.copy(alpha = 0.5f)
                        )
                    ) {
                        Text("授权")
                    }
                }
                ShizukuState.AUTHORIZED -> {
                    // 已授权时显示一个"重新检测"按钮, 以防状态过期
                    OutlinedButton(
                        onClick = { refreshKey++ },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("重新检测")
                    }
                }
            }

            // 所有非已授权状态都附带"我已操作, 刷新"按钮
            if (state != ShizukuState.AUTHORIZED) {
                OutlinedButton(
                    onClick = { refreshKey++ },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("我已操作, 刷新")
                }
            }
        }
    }
}

/**
 * 状态行: 图标 + 标题/副标题 + 状态徽标
 */
@Composable
private fun StatusRow(state: ShizukuState) {
    val isAuthorized = state == ShizukuState.AUTHORIZED
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0x12000000))
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = if (isAuthorized) Icons.Default.VerifiedUser else Icons.Default.Security,
            contentDescription = null,
            tint = if (isAuthorized) Primary else TextTertiary,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Shizuku",
                style = MaterialTheme.typography.bodyLarge,
                color = TextPrimary,
                fontWeight = FontWeight.Medium
            )
            Text(
                text = when (state) {
                    ShizukuState.NOT_INSTALLED -> "未安装"
                    ShizukuState.NOT_RUNNING -> "未启动"
                    ShizukuState.NOT_AUTHORIZED -> "未授权"
                    ShizukuState.AUTHORIZED -> "已就绪"
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (isAuthorized) Primary else TextTertiary
            )
        }
        // 状态徽标
        Box(
            modifier = Modifier
                .size(24.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(
                    if (isAuthorized) Primary.copy(alpha = 0.2f)
                    else MaterialTheme.colorScheme.error.copy(alpha = 0.2f)
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isAuthorized) Icons.Default.Check else Icons.Default.Close,
                contentDescription = null,
                tint = if (isAuthorized) Primary else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(16.dp)
            )
        }
    }
}

// ── 操作辅助函数 ──────────────────────────────────────

/**
 * 跳应用市场安装 Shizuku
 * 优先用市场 scheme, 失败回退到浏览器打开 Google Play / 酷安链接
 */
private fun openMarketForShizuku(context: android.content.Context) {
    val packageName = "moe.shizuku.privileged.api"
    val marketIntent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$packageName"))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    try {
        context.startActivity(marketIntent)
    } catch (e: Exception) {
        // 没有市场应用, 回退到浏览器
        val browserIntent = Intent(
            Intent.ACTION_VIEW,
            Uri.parse("https://play.google.com/store/apps/details?id=$packageName")
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            context.startActivity(browserIntent)
        } catch (e2: Exception) {
            // 仍失败, 不处理
        }
    }
}

/**
 * 启动 Shizuku 应用主界面
 */
private fun launchShizukuApp(context: android.content.Context) {
    val intent = Intent().apply {
        setClassName("moe.shizuku.privileged.api", "moe.shizuku.manager.MainActivity")
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    try {
        context.startActivity(intent)
    } catch (e: Exception) {
        // 回退: 用包名启动 launch intent
        try {
            val launchIntent = context.packageManager.getLaunchIntentForPackage(
                "moe.shizuku.privileged.api"
            )
            launchIntent?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (launchIntent != null) {
                context.startActivity(launchIntent)
            }
        } catch (e2: Exception) {
            // 不处理
        }
    }
}

/**
 * 请求 Shizuku 授权 (会弹出系统对话框)
 * 结果通过 Shizuku 的广播回传, 这里不监听, 由用户点"刷新"按钮触发重新检查
 */
private fun requestShizukuPermission() {
    try {
        Shizuku.requestPermission(1001)
    } catch (e: Exception) {
        // 异常不处理, 用户可重试
    }
}
