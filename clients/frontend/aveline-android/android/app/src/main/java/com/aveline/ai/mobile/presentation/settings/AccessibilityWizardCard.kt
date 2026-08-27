package com.aveline.ai.mobile.presentation.settings

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings
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
import androidx.compose.material.icons.filled.TouchApp
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
import com.aveline.ai.mobile.services.AvelineAccessibilityService

/**
 * 无障碍服务引导卡片
 *
 * 展示无障碍服务当前状态:
 * - 未开启 → 跳系统设置开启
 * - 已开启 → 显示绿色徽标
 *
 * 用 AvelineAccessibilityService.isRunning() 判断是否已连接 (system 调 onServiceConnected 后才会有实例)。
 * 同时用 AccessibilityManager 的 enabled services 列表兜底检测 (服务在系统层注册但未完成 onServiceConnected)。
 */
@Composable
fun AccessibilityWizardCard(
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    // 无障碍状态: true=已连接运行中; false=未运行
    var enabled by remember { mutableStateOf(false) }
    // 系统设置层是否仍启用该服务 (用于区分"进程被杀需重开"和"用户主动关闭")
    var enabledInSystem by remember { mutableStateOf(false) }
    var refreshKey by remember { mutableStateOf(0) }

    fun checkState() {
        val running = try {
            AvelineAccessibilityService.isRunning()
        } catch (e: Exception) {
            false
        }
        enabled = running
        enabledInSystem = if (running) {
            true
        } else {
            // 服务实例丢失, 但系统设置层可能仍启用 (进程被杀场景)
            try {
                isAccessibilityServiceEnabledInSettings(context)
            } catch (e: Exception) {
                false
            }
        }
    }

    LaunchedEffect(refreshKey) {
        checkState()
    }

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
        title = "无障碍服务",
        subtitle = "用于点击屏幕按钮、滑动、查找元素等 UI 自动化",
        icon = Icons.Default.TouchApp,
        modifier = modifier
    ) {
        StatusRow(enabled = enabled)

        Spacer(modifier = Modifier.height(12.dp))

        // 系统已启用但实例丢失(进程被杀): 提示用户重新开关一次以完成绑定
        if (!enabled && enabledInSystem) {
            Text(
                text = "系统设置中已开启, 但服务当前未运行(可能因进程被清理)。请关闭再重新开启, 或点击下方按钮进入设置修复。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error
            )
            Spacer(modifier = Modifier.height(12.dp))
        }

        Text(
            text = when {
                enabled -> "无障碍服务已就绪, AI 可执行点击/滑动/返回/桌面/找文字等 UI 操作。"
                enabledInSystem -> "服务未运行, 需要重新开关一次才能恢复 UI 自动化能力。"
                else -> "开启后 AI 可自动点击屏幕按钮 (如打开蓝牙开关、关闭弹窗等)。"
            },
            style = MaterialTheme.typography.bodySmall,
            color = TextTertiary
        )

        Spacer(modifier = Modifier.height(12.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            if (!enabled) {
                Button(
                    onClick = { openAccessibilitySettings(context) },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = PrimaryVariant.copy(alpha = 0.5f)
                    )
                ) {
                    Text(if (enabledInSystem) "进入设置修复" else "开启无障碍")
                }
                OutlinedButton(
                    onClick = { refreshKey++ },
                    modifier = Modifier.weight(1f)
                ) {
                    Text(if (enabledInSystem) "重新检测" else "我已开启, 刷新")
                }
            } else {
                OutlinedButton(
                    onClick = { refreshKey++ },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("重新检测")
                }
            }
        }
    }
}

@Composable
private fun StatusRow(enabled: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0x12000000))
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Default.TouchApp,
            contentDescription = null,
            tint = if (enabled) Primary else TextTertiary,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Aveline 无障碍服务",
                style = MaterialTheme.typography.bodyLarge,
                color = TextPrimary,
                fontWeight = FontWeight.Medium
            )
            Text(
                text = if (enabled) "已开启" else "未开启",
                style = MaterialTheme.typography.bodySmall,
                color = if (enabled) Primary else TextTertiary
            )
        }
        Box(
            modifier = Modifier
                .size(24.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(
                    if (enabled) Primary.copy(alpha = 0.2f)
                    else MaterialTheme.colorScheme.error.copy(alpha = 0.2f)
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (enabled) Icons.Default.Check else Icons.Default.Close,
                contentDescription = null,
                tint = if (enabled) Primary else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(16.dp)
            )
        }
    }
}

/**
 * 检查 AvelineAccessibilityService 是否在系统设置的已启用无障碍服务列表中。
 *
 * 系统的 enabled accessibility services 字段格式:
 * "pkg1/svc1:pkg2/svc2:..."
 */
private fun isAccessibilityServiceEnabledInSettings(context: Context): Boolean {
    return try {
        val targetComponent = ComponentName(
            context.packageName,
            AvelineAccessibilityService::class.java.name
        )
        val targetFlat = targetComponent.flattenToString()

        val enabledServices = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false

        // 分隔符可能为 ":" 或 ";", 不同 Android 版本可能不同
        val splitter = if (enabledServices.contains(":")) ":" else ";"
        enabledServices.split(splitter).any { it.equals(targetFlat, ignoreCase = true) }
    } catch (e: Exception) {
        false
    }
}

/**
 * 跳转到系统无障碍设置页面。
 */
private fun openAccessibilitySettings(context: Context) {
    try {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    } catch (e: Exception) {
        // 失败兜底: 跳通用设置
        try {
            val intent = Intent(Settings.ACTION_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        } catch (e2: Exception) {
            // 不处理
        }
    }
}

/**
 * 兼容性辅助: 用 AccessibilityManager 的 enabled services 列表检查 (备用方法)。
 * 保留但不使用, 因为某些厂商 ROM 不一定及时刷新。
 */
@Suppress("unused")
private fun checkEnabledViaAccessibilityManager(context: Context): Boolean {
    return try {
        val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE)
            as android.view.accessibility.AccessibilityManager
        val enabledServices = am.getEnabledAccessibilityServiceList(
            AccessibilityServiceInfo.FEEDBACK_GENERIC
        )
        val targetComponent = ComponentName(
            context.packageName,
            AvelineAccessibilityService::class.java.name
        )
        enabledServices.any { info ->
            info.resolveInfo?.let { resolveInfo ->
                ComponentName(
                    resolveInfo.serviceInfo.packageName,
                    resolveInfo.serviceInfo.name
                ) == targetComponent
            } ?: false
        }
    } catch (e: Exception) {
        false
    }
}
