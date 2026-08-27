package com.aveline.ai.mobile.presentation.food

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.MonetizationOn
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.ItemRarity
import com.aveline.ai.mobile.domain.models.PurchaseRecipient
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.ModuleHeaderActionContainer
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.shop.ShopUiState
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.PrimaryVariant
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/** 商城类别筛选选项（与 Pager 页一一对应，index = page） */
private val CATEGORY_OPTIONS = listOf(
    null to "全部",
    ShopCategory.FOOD to "食物",
    ShopCategory.GIFT to "礼物",
    ShopCategory.TOY to "玩具",
    ShopCategory.BOOK to "书籍",
    ShopCategory.CLOTHING to "服饰",
    ShopCategory.TECH to "科技",
    ShopCategory.LUXURY to "奢侈品"
)

/**
 * 商城主界面
 *
 * 类目切换：TabRow + HorizontalPager，左右滑动切换 8 个商品类目（全部 / 食物 / 礼物 /
 * 玩具 / 书籍 / 服饰 / 科技 / 奢侈品）。Tab 与 Pager 双向同步：
 * - 用户滑动 Pager → 通知 ViewModel.selectCategory(对应 category) 重新加载
 * - ViewModel.selectedCategory 变化（外部代码触发，如重置）→ 同步 Pager 滚动到对应页
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FoodScreen(
    shopUiState: ShopUiState,
    onRefresh: () -> Unit,
    onSelectCategory: (ShopCategory?) -> Unit,
    onLoadMore: () -> Unit,
    onShowPurchaseConfirm: (ShopItem) -> Unit,
    onHidePurchaseConfirm: () -> Unit,
    onConfirmPurchase: () -> Unit,
    onIncreaseQuantity: () -> Unit,
    onDecreaseQuantity: () -> Unit,
    onSelectRecipient: (PurchaseRecipient) -> Unit,
    onHidePurchaseResult: () -> Unit,
    onClearError: () -> Unit,
    onShowGiftInventory: () -> Unit,
    onHideGiftInventory: () -> Unit,
    onUseGift: (String, String) -> Unit,
    onHideUseGiftResult: () -> Unit,
    onEatFood: (String) -> Unit
) {
    // 根据当前 selectedCategory 反推 pager 初始页；找不到则回退到第 0 页（全部）
    val initialPage = remember(shopUiState.selectedCategory) {
        CATEGORY_OPTIONS.indexOfFirst { it.first == shopUiState.selectedCategory }.coerceAtLeast(0)
    }
    val pagerState = rememberPagerState(initialPage = initialPage) { CATEGORY_OPTIONS.size }
    val tabScrollState = rememberScrollState()
    val scope = rememberCoroutineScope()

    // Pager 滑动 → 切 category（仅 page 真的变了才通知，避免循环）
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.currentPage }
            .distinctUntilChanged()
            .collect { page ->
                val newCategory = CATEGORY_OPTIONS[page].first
                if (newCategory != shopUiState.selectedCategory) {
                    onSelectCategory(newCategory)
                }
            }
    }

    // 外部代码改变 selectedCategory（例如重新进入页面）→ Pager 同步
    LaunchedEffect(shopUiState.selectedCategory) {
        val targetPage = CATEGORY_OPTIONS.indexOfFirst { it.first == shopUiState.selectedCategory }
        if (targetPage >= 0 && targetPage != pagerState.currentPage) {
            pagerState.animateScrollToPage(targetPage)
        }
        // 切到目标页后，让对应 tab 滚到可视范围
        scope.launch { tabScrollState.animateScrollTo(targetPage * 96) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        ModuleHeader(
            title = "Mall",
            subtitle = "商城"
        ) {
            ModuleHeaderActionContainer {
                IconButton(onClick = onShowGiftInventory) {
                    Icon(Icons.Default.Inventory2, contentDescription = "库存", tint = Color.White)
                }
                IconButton(onClick = onRefresh) {
                    if (shopUiState.isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = Color.White,
                            strokeWidth = 2.dp
                        )
                    } else {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新", tint = Color.White)
                    }
                }
            }
        }

        // 类目 Tab 行：横向可滚，点击或左右滑切换类目
        // 用 Row + horizontalScroll 而不是 TabRow：TabRow 在 8+ 个 tab 时对长 label 截断，
        // 这里需要显示 "全部 / 食物 / 礼物 / 玩具 / 书籍 / 服饰 / 科技 / 奢侈品" 完整文字
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .horizontalScroll(tabScrollState),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            CATEGORY_OPTIONS.forEachIndexed { index, (category, label) ->
                val selected = pagerState.currentPage == index
                Surface(
                    onClick = {
                        scope.launch { pagerState.animateScrollToPage(index) }
                    },
                    shape = RoundedCornerShape(20.dp),
                    color = if (selected) PrimaryVariant.copy(alpha = 0.17f) else OverlayLight
                ) {
                    val icon = category?.icon ?: "🏪"
                    Text(
                        text = "$icon $label",
                        style = MaterialTheme.typography.labelLarge,
                        color = if (selected) Color.White else TextPrimary,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp)
                    )
                }
            }
        }

        // 类目内容：HorizontalPager 支持左右滑动切换
        HorizontalPager(
            state = pagerState,
            modifier = Modifier.fillMaxSize(),
            pageSpacing = 0.dp,
            contentPadding = PaddingValues(horizontal = 0.dp)
        ) { page ->
            CategoryPage(
                shopUiState = shopUiState,
                onLoadMore = onLoadMore,
                onShowPurchaseConfirm = onShowPurchaseConfirm,
                onEatFood = onEatFood
            )
        }
    }

    // 购买确认对话框
    if (shopUiState.showPurchaseConfirm && shopUiState.itemToPurchase != null) {
        PurchaseConfirmDialog(
            item = shopUiState.itemToPurchase,
            quantity = shopUiState.purchaseQuantity,
            totalCost = shopUiState.totalCost,
            canAfford = shopUiState.canAffordSelectedItem,
            userBalance = shopUiState.balance.coins,
            selectedRecipient = shopUiState.purchaseRecipient,
            onSelectRecipient = onSelectRecipient,
            onConfirm = onConfirmPurchase,
            onDismiss = onHidePurchaseConfirm,
            onIncrease = onIncreaseQuantity,
            onDecrease = onDecreaseQuantity
        )
    }

    // 购买结果对话框
    if (shopUiState.showPurchaseResult && shopUiState.purchaseResult != null) {
        PurchaseResultDialog(
            result = shopUiState.purchaseResult,
            onDismiss = onHidePurchaseResult
        )
    }

    // 礼物库存弹窗
    if (shopUiState.showGiftInventory) {
        GiftInventoryDialog(
            giftInventory = shopUiState.giftInventory,
            onUseGift = onUseGift,
            onDismiss = onHideGiftInventory
        )
    }

    // 使用礼物结果
    if (shopUiState.showUseGiftResult && shopUiState.useGiftResult != null) {
        AlertDialog(
            onDismissRequest = onHideUseGiftResult,
            title = { Text("使用结果") },
            text = { Text(shopUiState.useGiftResult) },
            confirmButton = {
                TextButton(onClick = onHideUseGiftResult) { Text("确定") }
            }
        )
    }

    // 错误提示（全局，只在 LoadingState 错误时显示一次）
    if (shopUiState.error?.isNotBlank() == true && shopUiState.items.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
            SectionCard(title = "错误") {
                Text(shopUiState.error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                Spacer(modifier = Modifier.height(8.dp))
                TextButton(onClick = onClearError) { Text("清除") }
            }
        }
    }
}

/**
 * 单个类目页：商品卡片列表 + 滚动加载更多。
 */
@Composable
private fun CategoryPage(
    shopUiState: ShopUiState,
    onLoadMore: () -> Unit,
    onShowPurchaseConfirm: (ShopItem) -> Unit,
    onEatFood: (String) -> Unit
) {
    val listState = rememberLazyListState()

    // 滚动到底部自动加载更多
    val shouldLoadMore = remember {
        derivedStateOf {
            val lastVisibleIndex = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
            val totalItems = listState.layoutInfo.totalItemsCount
            lastVisibleIndex >= totalItems - 3 && shopUiState.hasMore && !shopUiState.isLoadingMore
        }
    }
    LaunchedEffect(shouldLoadMore.value) {
        if (shouldLoadMore.value) {
            onLoadMore()
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        state = listState,
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // 加载中(首次)
        if (shopUiState.isLoading && shopUiState.items.isEmpty()) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 48.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator()
                }
            }
        }

        // 空状态
        if (!shopUiState.isLoading && shopUiState.items.isEmpty()) {
            item { EmptyShopState() }
        }

        // 商品卡片
        items(
            items = shopUiState.items,
            key = { it.id }
        ) { item ->
            ShopItemCard(
                item = item,
                canAfford = shopUiState.balance.coins >= item.price,
                onBuy = { onShowPurchaseConfirm(item) },
                onEat = { onEatFood(item.id) }
            )
        }

        // 加载更多指示器
        if (shopUiState.isLoadingMore) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 16.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
        }

        // 到底提示
        if (!shopUiState.hasMore && shopUiState.items.isNotEmpty()) {
            item {
                Text(
                    text = "— 已经到底啦 —",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 12.dp),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                )
            }
        }
    }
}

/**
 * 空状态
 */
@Composable
private fun EmptyShopState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            imageVector = Icons.Default.ShoppingBag,
            contentDescription = null,
            tint = TextTertiary,
            modifier = Modifier.size(48.dp)
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(text = "暂无商品", style = MaterialTheme.typography.titleMedium, color = TextSecondary)
    }
}

/**
 * 购买确认对话框
 */
@Composable
private fun PurchaseConfirmDialog(
    item: ShopItem,
    quantity: Int,
    totalCost: Int,
    canAfford: Boolean,
    userBalance: Int,
    selectedRecipient: PurchaseRecipient,
    onSelectRecipient: (PurchaseRecipient) -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    onIncrease: () -> Unit,
    onDecrease: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("确认购买") },
        text = {
            Column {
                Text(text = "${item.icon} ${item.name}", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text(text = "单价: ${item.price} 金币", style = MaterialTheme.typography.bodySmall, color = TextTertiary)

                // 稀有度
                if (item.rarity != ItemRarity.COMMON) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "${item.rarity.icon} ${item.rarity.label}",
                        style = MaterialTheme.typography.labelSmall,
                        color = when (item.rarity) {
                            ItemRarity.RARE -> Color(0xFF4FC3F7)
                            ItemRarity.EPIC -> Color(0xFFBA68C8)
                            ItemRarity.LEGENDARY -> Color(0xFFFFD54F)
                            else -> TextTertiary
                        }
                    )
                }

                // 效果
                if (item.effectDescription.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "效果: ${item.effectDescription}",
                        style = MaterialTheme.typography.labelSmall,
                        color = Primary
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))

                // 给谁买
                Text("给谁买", style = MaterialTheme.typography.bodyMedium)
                Spacer(modifier = Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PurchaseRecipient.values().forEach { recipient ->
                        val selected = recipient == selectedRecipient
                        Surface(
                            onClick = { onSelectRecipient(recipient) },
                            shape = RoundedCornerShape(16.dp),
                            color = if (selected) PrimaryVariant.copy(alpha = 0.2f) else OverlayLight
                        ) {
                            Text(
                                text = recipient.label,
                                style = MaterialTheme.typography.labelMedium,
                                color = if (selected) Color.White else TextPrimary,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // 数量
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("数量", style = MaterialTheme.typography.bodyMedium)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onDecrease, enabled = quantity > 1) {
                            Icon(Icons.Default.Remove, contentDescription = "减少")
                        }
                        Text(quantity.toString(), modifier = Modifier.padding(horizontal = 16.dp))
                        IconButton(onClick = onIncrease, enabled = canAfford) {
                            Icon(Icons.Default.Add, contentDescription = "增加")
                        }
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider()
                Spacer(modifier = Modifier.height(8.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("总计", style = MaterialTheme.typography.bodyMedium)
                    Text(
                        text = "$totalCost 金币",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                        color = if (canAfford) TextPrimary else MaterialTheme.colorScheme.error
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onConfirm, enabled = canAfford) { Text("确认购买") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

/**
 * 购买结果对话框
 */
@Composable
private fun PurchaseResultDialog(
    result: PurchaseResult,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = {
            Icon(
                imageVector = if (result.success) Icons.Default.CheckCircle else Icons.Default.Error,
                contentDescription = null,
                tint = if (result.success) EmotionGreen else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(48.dp)
            )
        },
        title = { Text(if (result.success) "购买成功" else "购买失败") },
        text = {
            Column {
                Text(text = result.message, style = MaterialTheme.typography.bodyMedium)
                result.newBalance?.let { balance ->
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.MonetizationOn, contentDescription = null, tint = Color(0xFFFFD700), modifier = Modifier.size(20.dp))
                        Spacer(modifier = Modifier.size(8.dp))
                        Text("当前余额: ${balance.coins} 金币", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("确定") }
        }
    )
}

/**
 * 礼物库存弹窗
 */
@Composable
private fun GiftInventoryDialog(
    giftInventory: List<com.aveline.ai.mobile.domain.models.GiftInventoryItem>,
    onUseGift: (String, String) -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("🎁 礼物库存") },
        text = {
            if (giftInventory.isEmpty()) {
                Text("库存是空的，去商城买点东西吧！", color = TextSecondary)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    giftInventory.forEach { item ->
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = Color(0x1A000000)
                        ) {
                            Column(modifier = Modifier.padding(10.dp).fillMaxWidth()) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        text = item.itemName,
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.Medium,
                                        modifier = Modifier.weight(1f)
                                    )
                                    Text(
                                        text = "x${item.quantity}",
                                        style = MaterialTheme.typography.labelLarge,
                                        color = TextTertiary
                                    )
                                }
                                if (item.effectDesc.isNotEmpty()) {
                                    Text(
                                        text = item.effectDesc,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Primary
                                    )
                                }
                                Spacer(modifier = Modifier.height(4.dp))
                                Button(
                                    onClick = { onUseGift(item.itemId, item.recipient) },
                                    modifier = Modifier.fillMaxWidth(),
                                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x2A38BDF8))
                                ) {
                                    Text("使用")
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("关闭") }
        }
    )
}
