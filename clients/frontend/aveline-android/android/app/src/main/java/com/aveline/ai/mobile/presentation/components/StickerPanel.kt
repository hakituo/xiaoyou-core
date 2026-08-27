package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 表情包面板：常用 emoji 大字号网格，点击直接发送为文本消息。
 *
 * 设计：
 * - 不依赖任何图片资源，开箱即用
 * - emoji 大字号渲染在视觉上接近贴纸
 * - 后续要支持图片贴纸时，把 grid 内容替换为图片 AsyncImage 即可
 *
 * @param onSelect 选中 emoji 回调
 * @param modifier 修饰符
 */
@Composable
fun StickerPanel(
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .height(280.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
        tonalElevation = 0.dp
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            Text(
                text = "表情",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
            )

            LazyVerticalGrid(
                columns = GridCells.Fixed(6),
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 12.dp),
                contentPadding = PaddingValues(bottom = 12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                items(EMOJIS) { emoji ->
                    Box(
                        modifier = Modifier
                            .aspectRatio(1f)
                            .clip(RoundedCornerShape(8.dp))
                            .background(OverlayLight)
                            .clickable { onSelect(emoji) },
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = emoji,
                            fontSize = 28.sp,
                            textAlign = TextAlign.Center
                        )
                    }
                }
            }
        }
    }
}

/** 常用 emoji 列表（按使用频率排序，QQ/微信风格） */
private val EMOJIS = listOf(
    // 笑脸
    "😀", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂",
    "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😋",
    "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔",
    // 情绪
    "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "🤥",
    "😌", "😔", "😪", "🤤", "😴", "😷", "🤒", "🤕",
    "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯",
    // 惊讶/生气/难过
    "😱", "😨", "😰", "😥", "😢", "😭", "😤", "😡",
    "🤬", "😈", "👿", "💀", "☠️", "💩", "🤡", "👹",
    // 爱心/手势
    "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍",
    "💔", "❣️", "💕", "💞", "💓", "💗", "💖", "💘",
    "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "🤙",
    "👏", "🙌", "👐", "🤲", "🤝", "🙏", "💪", "🦾",
    // 动物/物品
    "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼",
    "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🐔",
    "🎉", "🎊", "🎁", "🎂", "🍰", "🍕", "🍔", "🍟"
)
