package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * 时间分隔符组件
 * 
 * 当消息间隔超过 3 分钟时显示，用于消息分组。
 * 格式：
 * - 今天：HH:mm
 * - 昨天：昨天 HH:mm
 * - 其他：周几 HH:mm / MM月dd日 HH:mm
 * 
 * @param timestamp 时间戳（毫秒）
 * @param modifier 修饰符
 */
@Composable
fun TimeSeparator(
    timestamp: Long,
    modifier: Modifier = Modifier
) {
    val formattedTime = formatMessageTime(timestamp)
    
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 10.dp)
            .semantics { contentDescription = "时间分隔符: $formattedTime" },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = androidx.compose.foundation.layout.Arrangement.Center
    ) {
        Text(
            text = formattedTime,
            style = MaterialTheme.typography.labelSmall.copy(
                fontWeight = FontWeight.Light,
                letterSpacing = 1.2.sp,
            ),
            color = TextTertiary,
            modifier = Modifier.padding(horizontal = 12.dp)
        )
    }
}

/**
 * 格式化时间
 */
fun formatMessageTime(timestamp: Long): String {
    val now = System.currentTimeMillis()
    val calendar = Calendar.getInstance()
    calendar.timeInMillis = timestamp
    
    val messageDay = calendar.get(Calendar.DAY_OF_YEAR)
    val messageYear = calendar.get(Calendar.YEAR)
    
    calendar.timeInMillis = now
    val todayDay = calendar.get(Calendar.DAY_OF_YEAR)
    val todayYear = calendar.get(Calendar.YEAR)
    
    val yesterdayCalendar = Calendar.getInstance()
    yesterdayCalendar.add(Calendar.DAY_OF_YEAR, -1)
    val yesterdayDay = yesterdayCalendar.get(Calendar.DAY_OF_YEAR)
    val yesterdayYear = yesterdayCalendar.get(Calendar.YEAR)
    
    val timeFormat = SimpleDateFormat("HH:mm", Locale.getDefault())
    val timeStr = timeFormat.format(Date(timestamp))
    
    return when {
        messageYear == todayYear && messageDay == todayDay -> {
            timeStr
        }
        messageYear == yesterdayYear && messageDay == yesterdayDay -> {
            "昨天 $timeStr"
        }
        else -> {
            val diffDays = ((now - timestamp) / 86400000L).toInt()
            if (diffDays in 2..6) {
                val week = arrayOf("周日", "周一", "周二", "周三", "周四", "周五", "周六")
                "${week[calendar.get(Calendar.DAY_OF_WEEK) - 1]} $timeStr"
            } else {
                val dateFormat = SimpleDateFormat("MM月dd日", Locale.getDefault())
                dateFormat.format(Date(timestamp))
            }
        }
    }
}

/**
 * 检查是否需要显示时间分隔符
 * 
 * @param previousTimestamp 前一条消息的时间戳
 * @param currentTimestamp 当前消息的时间戳
 * @param thresholdMinutes 阈值（分钟），默认 3 分钟
 * @return 是否需要显示分隔符
 */
fun shouldShowTimeSeparator(
    previousTimestamp: Long?,
    currentTimestamp: Long,
    thresholdMinutes: Long = 3
): Boolean {
    if (previousTimestamp == null) return true
    
    val diff = currentTimestamp - previousTimestamp
    val thresholdMs = thresholdMinutes * 60 * 1000
    
    return diff >= thresholdMs
}

/**
 * 日期分隔符组件
 * 用于显示日期变化
 */
@Composable
fun DateSeparator(
    timestamp: Long,
    modifier: Modifier = Modifier
) {
    val dateFormat = SimpleDateFormat("yyyy年MM月dd日 EEEE", Locale.CHINA)
    val formattedDate = dateFormat.format(Date(timestamp))
    
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp)
            .semantics { contentDescription = "日期: $formattedDate" },
        verticalAlignment = Alignment.CenterVertically
    ) {
        @Suppress("DEPRECATION")
        Divider(
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
            thickness = 1.dp
        )
        
        Text(
            text = formattedDate,
            style = MaterialTheme.typography.labelMedium,
            color = TextTertiary,
            modifier = Modifier.padding(horizontal = 16.dp)
        )
        
        @Suppress("DEPRECATION")
        Divider(
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
            thickness = 1.dp
        )
    }
}
