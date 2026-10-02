package com.aveline.ai.mobile.presentation.chat

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.TextFieldValue

/**
 * 编辑已发送消息（重新生成前改写原文）的对话框。
 *
 * 文本状态内聚在对话框内部（进入时以原文本初始化），ChatScreen 只需记住"正在编辑哪条消息"。
 *
 * @param initialText 原消息文本
 * @param onConfirm 提交并重新生成
 * @param textFieldModifier 输入框修饰符（由调用方决定宽度）
 */
@Composable
fun ChatEditMessageDialog(
    initialText: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
    textFieldModifier: Modifier = Modifier
) {
    var editingText by remember(initialText) { mutableStateOf(TextFieldValue(initialText)) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑请求") },
        text = {
            OutlinedTextField(
                value = editingText,
                onValueChange = { editingText = it },
                modifier = textFieldModifier,
                minLines = 3,
                maxLines = 8
            )
        },
        confirmButton = {
            TextButton(
                enabled = editingText.text.isNotBlank(),
                onClick = { onConfirm(editingText.text) }
            ) {
                Text("提交并生成")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        }
    )
}
