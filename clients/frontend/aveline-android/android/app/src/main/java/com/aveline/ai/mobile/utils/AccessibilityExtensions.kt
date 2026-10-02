package com.aveline.ai.mobile.utils

import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp

/**
 * 无障碍扩展函数
 * 
 * 提供 Compose 无障碍功能的扩展
 * 
 * Requirements: 26.1, 26.6
 */

/**
 * 添加无障碍内容描述
 * 
 * @param description 内容描述
 */
fun Modifier.accessibilityDescription(description: String): Modifier {
    return this.semantics {
        contentDescription = description
    }
}

/**
 * 添加按钮无障碍属性
 * 
 * @param description 按钮描述
 */
fun Modifier.accessibilityButton(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Button
    }
}

/**
 * 添加图片无障碍属性
 * 
 * @param description 图片描述
 */
fun Modifier.accessibilityImage(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Image
    }
}

/**
 * 添加开关无障碍属性
 * 
 * @param description 开关描述
 * @param isChecked 是否选中
 */
fun Modifier.accessibilitySwitch(
    description: String,
    isChecked: Boolean
): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Switch
        stateDescription = if (isChecked) "已开启" else "已关闭"
    }
}

/**
 * 添加复选框无障碍属性
 * 
 * @param description 复选框描述
 * @param isChecked 是否选中
 */
fun Modifier.accessibilityCheckbox(
    description: String,
    isChecked: Boolean
): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Checkbox
        stateDescription = if (isChecked) "已选中" else "未选中"
    }
}

/**
 * 添加单选按钮无障碍属性
 * 
 * @param description 单选按钮描述
 * @param isSelected 是否选中
 */
fun Modifier.accessibilityRadioButton(
    description: String,
    isSelected: Boolean
): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.RadioButton
        stateDescription = if (isSelected) "已选中" else "未选中"
    }
}

/**
 * 添加标签页无障碍属性
 * 
 * @param description 标签页描述
 * @param isSelected 是否选中
 */
fun Modifier.accessibilityTab(
    description: String,
    isSelected: Boolean
): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Tab
        stateDescription = if (isSelected) "当前页面" else "切换到此页面"
    }
}

/**
 * 添加链接无障碍属性
 * 
 * @param description 链接描述
 */
fun Modifier.accessibilityLink(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Button
    }
}

/**
 * 添加标题无障碍属性
 * 
 * @param description 标题描述
 */
fun Modifier.accessibilityHeading(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        // 在 Compose 1.5+ 可以使用 heading() 语义
    }
}

/**
 * 添加列表项无障碍属性
 * 
 * @param description 列表项描述
 * @param position 位置（从1开始）
 * @param totalCount 总数
 */
fun Modifier.accessibilityListItem(
    description: String,
    position: Int,
    totalCount: Int
): Modifier {
    return this.semantics {
        contentDescription = "$description, 第 $position 项, 共 $totalCount 项"
    }
}

/**
 * 确保最小触摸目标大小
 * 
 * @param minSize 最小尺寸（默认 48dp）
 */
fun Modifier.minimumTouchTargetSize(minSize: Int = 48): Modifier {
    return this.size(minSize.dp)
}

/**
 * 添加进度条无障碍属性
 * 
 * @param description 进度条描述
 * @param progress 当前进度（0-100）
 */
fun Modifier.accessibilityProgressBar(
    description: String,
    progress: Int
): Modifier {
    return this.semantics {
        contentDescription = "$description: $progress%"
    }
}

/**
 * 添加滑块无障碍属性
 * 
 * @param description 滑块描述
 * @param value 当前值
 * @param valueRange 值范围
 */
fun Modifier.accessibilitySlider(
    description: String,
    value: Float,
    @Suppress("UNUSED_PARAMETER") valueRange: ClosedFloatingPointRange<Float>
): Modifier {
    return this.semantics {
        contentDescription = "$description: ${value.toInt()}"
    }
}

/**
 * 添加文本字段无障碍属性
 * 
 * @param label 标签
 * @param value 当前值
 * @param isRequired 是否必填
 */
fun Modifier.accessibilityTextField(
    label: String,
    value: String,
    isRequired: Boolean = false
): Modifier {
    return this.semantics {
        val requiredText = if (isRequired) "（必填）" else ""
        contentDescription = "$label$requiredText: $value"
    }
}

/**
 * 添加图标按钮无障碍属性
 * 
 * @param description 按钮功能描述
 */
fun Modifier.accessibilityIconButton(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Button
    }
}

/**
 * 添加菜单项无障碍属性
 * 
 * @param description 菜单项描述
 */
fun Modifier.accessibilityMenuItem(description: String): Modifier {
    return this.semantics {
        contentDescription = description
        role = Role.Button
    }
}

/**
 * 添加对话框无障碍属性
 * 
 * @param title 对话框标题
 */
fun Modifier.accessibilityDialog(title: String): Modifier {
    return this.semantics {
        contentDescription = "对话框: $title"
    }
}

/**
 * 添加展开/折叠无障碍属性
 * 
 * @param description 描述
 * @param isExpanded 是否展开
 */
fun Modifier.accessibilityExpandable(
    description: String,
    isExpanded: Boolean
): Modifier {
    return this.semantics {
        contentDescription = description
        stateDescription = if (isExpanded) "已展开" else "已折叠"
    }
}

/**
 * 组合无障碍描述
 * 
 * @param elements 要组合的元素描述列表
 */
fun combineAccessibilityDescription(vararg elements: String): String {
    return elements.filter { it.isNotEmpty() }.joinToString(", ")
}

/**
 * 获取无障碍友好的状态描述
 */
@Composable
fun getAccessibilityStateDescription(
    enabled: Boolean,
    selected: Boolean = false,
    expanded: Boolean = false
): String {
    val states = mutableListOf<String>()
    
    if (!enabled) states.add("已禁用")
    if (selected) states.add("已选中")
    if (expanded) states.add("已展开")
    
    return states.joinToString(", ")
}
