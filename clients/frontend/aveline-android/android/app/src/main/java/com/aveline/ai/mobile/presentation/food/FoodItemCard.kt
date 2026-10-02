package com.aveline.ai.mobile.presentation.food

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
import androidx.compose.material.icons.filled.MonetizationOn
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.ItemRarity
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 商城商品卡片
 *
 * 食物类商品显示"购买"+"食用"按钮;
 * 非食物类商品只显示"购买"按钮(使用在礼物库存里)。
 */
@Composable
fun ShopItemCard(
    item: ShopItem,
    canAfford: Boolean,
    onBuy: () -> Unit,
    onEat: () -> Unit,
    modifier: Modifier = Modifier
) {
    val enabled = canAfford && item.isAvailable
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (enabled) Color(0x1A000000) else Color(0x12000000)
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // 顶部: 图标 + 名称 + 类别标签 + 稀有度 + 价格
            Row(verticalAlignment = Alignment.CenterVertically) {
                // 商品图标
                Box(
                    modifier = Modifier
                        .size(48.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(categoryColor(item.category)),
                    contentAlignment = Alignment.Center
                ) {
                    Text(text = item.icon, fontSize = 24.sp)
                }

                Spacer(modifier = Modifier.width(12.dp))

                // 名称 + 类别标签
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = item.name,
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (enabled) TextPrimary else TextTertiary,
                            fontWeight = FontWeight.Medium
                        )
                        // 稀有度图标
                        if (item.rarity != ItemRarity.COMMON) {
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = item.rarity.icon,
                                fontSize = 14.sp
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    CategoryBadge(category = item.category)
                }

                // 价格
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.MonetizationOn,
                        contentDescription = null,
                        tint = if (canAfford) Color(0xFFFFD700) else TextTertiary,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = formatPrice(item.price),
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (canAfford) TextPrimary else TextTertiary,
                        fontWeight = FontWeight.Bold
                    )
                }
            }

            // 描述
            if (item.description.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = item.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }

            // 效果描述
            if (item.effectDescription.isNotEmpty()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = item.effectDescription,
                    style = MaterialTheme.typography.labelSmall,
                    color = Primary
                )
            }

            Spacer(modifier = Modifier.height(10.dp))

            // 操作按钮
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = onBuy,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A38BDF8))
                ) {
                    Icon(Icons.Default.ShoppingCart, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("购买")
                }
                // 只有食物才有"食用"按钮
                if (item.isFood) {
                    Button(
                        onClick = onEat,
                        enabled = item.isAvailable,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0x1A000000))
                    ) {
                        Icon(Icons.Default.Restaurant, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("食用")
                    }
                }
            }

            // 状态提示
            if (!canAfford) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "余额不足",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error
                )
            } else if (!item.isAvailable) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "已售罄",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
        }
    }
}

/**
 * 类别标签
 */
@Composable
private fun CategoryBadge(category: ShopCategory) {
    Surface(
        color = categoryColor(category),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = category.label,
            style = MaterialTheme.typography.labelSmall,
            color = categoryBadgeTextColor(category),
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
        )
    }
}

/** 格式化价格(大数字加 k/w 后缀) */
private fun formatPrice(price: Int): String {
    return when {
        price >= 10000 -> "${price / 10000}w"
        price >= 1000 -> "${price / 1000}k"
        else -> price.toString()
    }
}

/** 类别对应的图标背景色 */
private fun categoryColor(category: ShopCategory): Color = when (category) {
    ShopCategory.FOOD -> Color(0xFFFFE0B2)
    ShopCategory.GIFT -> Color(0xFFF8BBD0)
    ShopCategory.TOY -> Color(0xFFB3E5FC)
    ShopCategory.BOOK -> Color(0xFFC8E6C9)
    ShopCategory.CLOTHING -> Color(0xFFE1BEE7)
    ShopCategory.TECH -> Color(0xFFB2EBF2)
    ShopCategory.LUXURY -> Color(0xFFFFF9C4)
}

/** 类别标签文字色 */
private fun categoryBadgeTextColor(category: ShopCategory): Color = when (category) {
    ShopCategory.FOOD -> Color(0xFFFF6F00)
    ShopCategory.GIFT -> Color(0xFFAD1457)
    ShopCategory.TOY -> Color(0xFF0277BD)
    ShopCategory.BOOK -> Color(0xFF2E7D32)
    ShopCategory.CLOTHING -> Color(0xFF6A1B9A)
    ShopCategory.TECH -> Color(0xFF006064)
    ShopCategory.LUXURY -> Color(0xFFF57F17)
}
