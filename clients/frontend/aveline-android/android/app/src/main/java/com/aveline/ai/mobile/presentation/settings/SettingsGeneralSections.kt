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
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 常规 tab 的网络分区:后端地址 + 访问令牌 + 测试/保存 + 结果。
 *
 * 从 [SettingsGeneralTab] 拆出,以控制单文件行数。
 */
@Composable
internal fun NetworkSection(
    backendUrl: String,
    accessToken: String,
    isValid: Boolean,
    isTesting: Boolean,
    testResult: ConnectionTestResult?,
    onUrlChange: (String) -> Unit,
    onTokenChange: (String) -> Unit,
    onTestConnection: () -> Unit,
    onSave: () -> Unit,
    tunnelUrl: String = "",
    isUsingTunnel: Boolean = false,
    onTunnelUrlChange: (String) -> Unit = {},
    onToggleTunnel: (Boolean) -> Unit = {}
) {
    Column {
        OutlinedTextField(
            value = backendUrl,
            onValueChange = onUrlChange,
            label = { Text("后端地址") },
            placeholder = { Text("http://localhost:8000") },
            singleLine = true,
            isError = backendUrl.isNotEmpty() && !isValid,
            supportingText = {
                if (backendUrl.isNotEmpty() && !isValid) {
                    Text("请输入有效的 URL(以 http:// 或 https:// 开头)")
                }
            },
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

        // Cloudflare Tunnel 备用域名
        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = tunnelUrl,
            onValueChange = onTunnelUrlChange,
            label = { Text("Tunnel 域名 (外出时用)") },
            placeholder = { Text("https://your-domain.example.com") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        // Tunnel 一键切换开关 (没填 tunnel 域名时隐藏)
        if (tunnelUrl.isNotBlank()) {
            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "使用 Tunnel",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    Text(
                        text = if (isUsingTunnel) "当前: 公网域名 (外出可用)" else "当前: 内网 IP (低延迟)",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(
                    checked = isUsingTunnel,
                    onCheckedChange = onToggleTunnel
                )
            }
        }

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
                onClick = onSave,
                enabled = isValid,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A10B981), contentColor = Color(0xFFE2E8F0))
            ) {
                Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("保存")
            }
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
