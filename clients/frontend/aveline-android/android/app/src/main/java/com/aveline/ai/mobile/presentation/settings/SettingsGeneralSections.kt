package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 常规 tab 的网络分区：三个地址槽位 + 当前通道 + 访问令牌 + 测试/重探/保存。
 *
 * 地址模型（与 AppPreferences / EndpointResolver 一致）：
 * - 局域网地址：在家优先走这条，留空则靠自动发现；
 * - 组网地址：Tailscale 等点对点通道，外出时优先于公网域名，两者并存不是互斥开关；
 * - 公网域名：Cloudflare Tunnel，组网不可用时的兜底；
 * - 手动锁定：填了就强制用它、不再自动切换（留空 = 自动）。
 *
 * 从 [SettingsGeneralTab] 拆出,以控制单文件行数。
 */
@Composable
internal fun NetworkSection(
    manualUrl: String,
    lanUrl: String,
    vpnUrl: String,
    tunnelUrl: String,
    activeUrl: String,
    activeChannel: String,
    accessToken: String,
    isValid: Boolean,
    isTesting: Boolean,
    testResult: ConnectionTestResult?,
    onManualUrlChange: (String) -> Unit,
    onLanUrlChange: (String) -> Unit,
    onVpnUrlChange: (String) -> Unit,
    onTunnelUrlChange: (String) -> Unit,
    onTokenChange: (String) -> Unit,
    onTestConnection: () -> Unit,
    onReprobe: () -> Unit,
    onSave: () -> Unit
) {
    Column {
        // 当前生效通道（只读）：让用户一眼看出「现在到底在走哪条」
        if (activeUrl.isNotBlank()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "当前通道",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = activeChannel,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF38BDF8)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = activeUrl,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        OutlinedTextField(
            value = lanUrl,
            onValueChange = onLanUrlChange,
            label = { Text("局域网地址（在家优先）") },
            placeholder = { Text("http://192.0.2.1:8000") },
            singleLine = true,
            isError = isInvalidBackendUrl(lanUrl),
            supportingText = { Text("留空则由启动时的自动发现填写；探测不通会自动降级到组网或公网") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = vpnUrl,
            onValueChange = onVpnUrlChange,
            label = { Text("组网地址（外出优先）") },
            placeholder = { Text("http://100.x.y.z:8000") },
            singleLine = true,
            isError = isInvalidBackendUrl(vpnUrl),
            supportingText = { Text("Tailscale 等点对点地址，手机端需开启组网；不通时自动退回公网域名") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = tunnelUrl,
            onValueChange = onTunnelUrlChange,
            label = { Text("公网域名（外出兜底）") },
            placeholder = { Text("https://your-domain.example.com") },
            singleLine = true,
            isError = isInvalidBackendUrl(tunnelUrl),
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = manualUrl,
            onValueChange = onManualUrlChange,
            label = { Text("手动锁定（可选）") },
            placeholder = { Text("留空 = 自动选择") },
            singleLine = true,
            isError = isInvalidBackendUrl(manualUrl),
            supportingText = { Text("填写后强制使用该地址，不再自动切换通道") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = accessToken,
            onValueChange = onTokenChange,
            label = { Text("访问令牌 (Access Token)") },
            placeholder = { Text("输入后端安全令牌") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(16.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = onTestConnection,
                enabled = isValid && !isTesting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A38BDF8), contentColor = Color(0xFFE2E8F0))
            ) {
                if (isTesting) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text("测试连接")
            }
            Button(
                onClick = onReprobe,
                enabled = isValid && !isTesting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A38BDF8), contentColor = Color(0xFFE2E8F0))
            ) {
                Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("重新探测")
            }
        }

        Spacer(modifier = Modifier.height(8.dp))
        Button(
            onClick = onSave,
            enabled = isValid,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A10B981), contentColor = Color(0xFFE2E8F0))
        ) {
            Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(modifier = Modifier.width(8.dp))
            Text("保存")
        }

        // 连接测试结果
        testResult?.let { result ->
            Spacer(modifier = Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (result.success) Icons.Default.Check else Icons.Default.Close,
                    contentDescription = null,
                    tint = if (result.success) Color(0xFF10B981) else MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = result.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (result.success) Color(0xFF10B981) else MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

/**
 * 常规 tab 的模型分区:下拉选择可用模型。
 *
 * 从 [SettingsGeneralTab] 拆出,以控制单文件行数。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ModelSection(
    availableModels: List<AIModel>,
    selectedModel: AIModel?,
    isLoading: Boolean,
    error: String?,
    onModelSelected: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        when {
            isLoading -> Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                Spacer(modifier = Modifier.width(8.dp))
                Text("正在加载模型...", style = MaterialTheme.typography.bodyMedium, color = TextTertiary)
            }
            error != null -> Text("错误: $error", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
            availableModels.isEmpty() -> Text("无可用模型", style = MaterialTheme.typography.bodyMedium, color = TextTertiary)
            else -> ExposedDropdownMenuBox(
                expanded = expanded,
                onExpandedChange = { expanded = !expanded },
                modifier = Modifier.fillMaxWidth()
            ) {
                OutlinedTextField(
                    value = selectedModel?.name ?: "未选择模型",
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("选择语言模型") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                    colors = ExposedDropdownMenuDefaults.outlinedTextFieldColors(),
                    modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth()
                )
                ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    availableModels.forEach { model ->
                        DropdownMenuItem(
                            text = {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(model.name)
                                    if (selectedModel?.id == model.id) {
                                        Spacer(modifier = Modifier.weight(1f))
                                        Icon(Icons.Default.Check, contentDescription = "已选择", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(16.dp))
                                    }
                                }
                            },
                            onClick = { onModelSelected(model.id); expanded = false }
                        )
                    }
                }
            }
        }
        selectedModel?.let {
            Spacer(modifier = Modifier.height(8.dp))
            Text(text = "Provider: ${it.provider}", style = MaterialTheme.typography.bodySmall, color = TextTertiary)
        }
    }
}
