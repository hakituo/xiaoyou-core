@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Fastfood
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.CalendarToday
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Face
import androidx.compose.material.icons.outlined.Fastfood
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PushPin
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.ShoppingBag
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.theme.DividerColor
import com.aveline.ai.mobile.presentation.theme.InteractivePrimary
import com.aveline.ai.mobile.presentation.theme.StatusOffline
import com.aveline.ai.mobile.presentation.theme.StatusOnline
import com.aveline.ai.mobile.presentation.theme.TextMuted
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class ConnectionState {
    CONNECTED, CONNECTING, DISCONNECTED
}

data class DrawerItem(
    val route: String,
    val title: String,
    val icon: ImageVector,
    val selectedIcon: ImageVector,
    val contentDescription: String
)

val drawerItems = listOf(
    DrawerItem(
        route = Routes.CONVERSATIONS,
        title = "消息",
        icon = Icons.Outlined.ChatBubbleOutline,
        selectedIcon = Icons.Filled.Chat,
        contentDescription = "会话列表"
    ),
    DrawerItem(
        route = Routes.STUDY,
        title = "学习",
        icon = Icons.Outlined.MenuBook,
        selectedIcon = Icons.Filled.MenuBook,
        contentDescription = "学习(计划/日记/笔记/词汇)"
    ),
    DrawerItem(
        route = Routes.LIFE,
        title = "生活",
        icon = Icons.Outlined.CalendarToday,
        selectedIcon = Icons.Filled.CalendarToday,
        contentDescription = "生活(健康/饮水/日程/餐食)"
    ),
    DrawerItem(
        route = Routes.FOOD,
        title = "商城",
        icon = Icons.Outlined.ShoppingBag,
        selectedIcon = Icons.Filled.ShoppingBag,
        contentDescription = "商城"
    ),
    DrawerItem(
        route = Routes.WELLBEING,
        title = "数字健康",
        icon = Icons.Outlined.Timer,
        selectedIcon = Icons.Filled.Timer,
        contentDescription = "数字健康(应用使用时长限额)"
    ),
    DrawerItem(
        route = Routes.SETTINGS,
        title = "设置",
        icon = Icons.Outlined.Settings,
        selectedIcon = Icons.Filled.Settings,
        contentDescription = "设置"
    )
)

@Composable
fun DrawerContent(
    currentRoute: String,
    currentEmotion: String,
    @Suppress("UNUSED_PARAMETER") connectionState: ConnectionState,
    @Suppress("UNUSED_PARAMETER") sessions: List<Session>,
    @Suppress("UNUSED_PARAMETER") currentSessionId: String?,
    onNavigate: (String) -> Unit,
    @Suppress("UNUSED_PARAMETER") onSessionClick: (String) -> Unit,
    @Suppress("UNUSED_PARAMETER") onNewSession: () -> Unit,
    @Suppress("UNUSED_PARAMETER") onSessionRename: (String, String) -> Unit,
    @Suppress("UNUSED_PARAMETER") onSessionDelete: (String) -> Unit,
    @Suppress("UNUSED_PARAMETER") onSessionPin: (String, Boolean) -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
    ) {
        // 添加呼吸灯背景作为侧边栏的底色
        BreathingBackground(
            modifier = Modifier.fillMaxSize(),
            emotion = currentEmotion,
            backgroundAlpha = 0.9f
        )

        // 毛玻璃效果遮罩，使用半透明深色覆盖在呼吸灯上面，让背景既有颜色又有深邃感
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0x88101522))
        )
        
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp)
        ) {
            Spacer(modifier = Modifier.weight(1f))
            Column(
                modifier = Modifier
                    .weight(3f)
                    .fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically)
            ) {
                drawerItems.forEach { item ->
                    // "消息"(CONVERSATIONS) 在聊天详情页(CHAT)也应视为选中态，
                    // 否则在聊天页点时看不到高亮反馈，误以为没点到。
                    val isSelected = if (item.route == Routes.CONVERSATIONS) {
                        currentRoute == Routes.CONVERSATIONS ||
                            currentRoute.startsWith(Routes.CHAT)
                    } else {
                        currentRoute == item.route
                    }
                    DrawerNavigationItem(
                        item = item,
                        isSelected = isSelected,
                        // 设置与其他顶层栏目必须共用同一导航入口。若设置单独直接
                        // navigate，之后恢复其他栏目时会连同设置页一起恢复，导致
                        // 返回栈顶仍停留在设置页。
                        onClick = { onNavigate(item.route) }
                    )
                }
            }
            Spacer(modifier = Modifier.weight(1f))
        }
    }
}

@Composable
fun DrawerNavigationItem(
    item: DrawerItem,
    isSelected: Boolean,
    onClick: () -> Unit
) {
    val backgroundColor = if (isSelected) Color(0x1A000000) else Color.Transparent
    val contentColor = if (isSelected) Color.White else Color(0x66FFFFFF)
    val borderColor = if (isSelected) Color(0x14000000) else Color.Transparent

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(backgroundColor)
            .border(1.dp, borderColor, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = if (isSelected) item.selectedIcon else item.icon,
            contentDescription = item.contentDescription,
            tint = contentColor,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = item.title,
            style = MaterialTheme.typography.bodyMedium.copy(
                fontWeight = FontWeight.Medium,
                letterSpacing = 0.5.sp
            ),
            color = if (isSelected) contentColor else Color(0xE6FFFFFF)
        )
    }
}

// 遗留的 SessionItem 和其他代码被清理了，因为侧边栏不再需要它们
