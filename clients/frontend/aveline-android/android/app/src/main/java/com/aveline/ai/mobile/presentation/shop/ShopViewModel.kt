package com.aveline.ai.mobile.presentation.shop

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.GiftInventoryItem
import com.aveline.ai.mobile.domain.models.PurchaseRecipient
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.domain.models.UserBalance
import com.aveline.ai.mobile.domain.repository.ShopRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 商城 UI 状态
 */
data class ShopUiState(
    val items: List<ShopItem> = emptyList(),
    val balance: UserBalance = UserBalance(),
    val selectedCategory: ShopCategory? = null,
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val error: String? = null,
    val currentPage: Int = 1,
    val hasMore: Boolean = false,
    val totalItems: Int = 0,
    // 购买对话框
    val showPurchaseConfirm: Boolean = false,
    val itemToPurchase: ShopItem? = null,
    val purchaseQuantity: Int = 1,
    val purchaseRecipient: PurchaseRecipient = PurchaseRecipient.SELF,
    val purchaseResult: PurchaseResult? = null,
    val showPurchaseResult: Boolean = false,
    // 礼物库存
    val giftInventory: List<GiftInventoryItem> = emptyList(),
    val showGiftInventory: Boolean = false,
    val useGiftResult: String? = null,
    val showUseGiftResult: Boolean = false
) {
    val canAffordSelectedItem: Boolean
        get() = itemToPurchase?.let { item ->
            balance.coins >= item.price * purchaseQuantity
        } ?: false

    val totalCost: Int
        get() = itemToPurchase?.let { it.price * purchaseQuantity } ?: 0
}

/**
 * 商城 ViewModel
 *
 * 功能：
 * - 7 类商品分页加载(懒加载)
 * - 类别切换
 * - 购买(支持 recipient)
 * - 礼物库存查看/使用
 */
@HiltViewModel
class ShopViewModel @Inject constructor(
    private val shopRepository: ShopRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(ShopUiState())
    val uiState: StateFlow<ShopUiState> = _uiState.asStateFlow()

    companion object {
        private const val PAGE_SIZE = 20
        private const val CACHE_MAX_AGE_MILLIS = 10 * 60 * 1000L
    }

    private var loadJob: Job? = null
    private var loadMoreJob: Job? = null

    init {
        loadItems(forceRefresh = false)
    }

    /**
     * 加载商品(第一页,切换类别时调用)
     */
    private fun loadItems(forceRefresh: Boolean) {
        val category = _uiState.value.selectedCategory
        val cached = shopRepository.getCachedShopSnapshot(category)

        if (!forceRefresh && cached != null) {
            // ViewModel 即使随 Route 重建，也先同步恢复单例 Repository 中的快照，
            // 页面不会闪回空白或整页 Loading。
            _uiState.update {
                it.copy(
                    items = cached.items,
                    balance = cached.balance,
                    isLoading = false,
                    error = null,
                    currentPage = cached.currentPage,
                    hasMore = cached.hasMore,
                    totalItems = cached.items.size
                )
            }
            if (System.currentTimeMillis() - cached.updatedAtMillis <= CACHE_MAX_AGE_MILLIS) {
                return
            }
        }

        loadJob?.cancel()
        loadMoreJob?.cancel()
        loadJob = viewModelScope.launch {
            val keepVisibleItems = cached != null || _uiState.value.items.isNotEmpty()
            _uiState.update {
                it.copy(
                    isLoading = true,
                    error = null,
                    items = if (keepVisibleItems) it.items else emptyList(),
                    currentPage = if (keepVisibleItems) it.currentPage else 1
                )
            }

            try {
                val (balance, pageResult) = coroutineScope {
                    val balanceRequest = async { shopRepository.getBalance() }
                    val itemsRequest = async {
                        shopRepository.getShopItems(
                            category = category,
                            page = 1,
                            pageSize = PAGE_SIZE
                        )
                    }
                    balanceRequest.await() to itemsRequest.await()
                }
                val (items, hasMore) = pageResult

                _uiState.update {
                    if (it.selectedCategory != category) return@update it
                    it.copy(
                        items = items,
                        balance = balance,
                        isLoading = false,
                        hasMore = hasMore,
                        currentPage = 1,
                        totalItems = items.size
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _uiState.update {
                    if (it.selectedCategory != category) return@update it
                    it.copy(
                        isLoading = false,
                        error = "加载失败: ${e.message}"
                    )
                }
            }
        }
    }

    /** 用户点击刷新时保留现有商品，只在标题栏显示轻量刷新状态。 */
    fun refreshItems() {
        loadItems(forceRefresh = true)
    }

    /**
     * 加载更多(翻页)
     */
    fun loadMore() {
        val state = _uiState.value
        if (state.isLoading || state.isLoadingMore || !state.hasMore) return
        val category = state.selectedCategory

        _uiState.update { it.copy(isLoadingMore = true) }
        loadMoreJob = viewModelScope.launch {

            try {
                val nextPage = state.currentPage + 1
                val (items, hasMore) = shopRepository.getShopItems(
                    category = category,
                    page = nextPage,
                    pageSize = PAGE_SIZE
                )

                _uiState.update {
                    if (it.selectedCategory != category) {
                        return@update it.copy(isLoadingMore = false)
                    }
                    it.copy(
                        items = it.items + items,
                        isLoadingMore = false,
                        hasMore = hasMore,
                        currentPage = nextPage
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(isLoadingMore = false)
                }
            }
        }
    }

    /**
     * 选择类别
     */
    fun selectCategory(category: ShopCategory?) {
        if (_uiState.value.selectedCategory == category) return
        loadJob?.cancel()
        loadMoreJob?.cancel()
        _uiState.update { it.copy(selectedCategory = category) }
        loadItems(forceRefresh = false)
    }

    /**
     * 显示购买确认
     */
    fun showPurchaseConfirm(item: ShopItem) {
        _uiState.update {
            it.copy(
                showPurchaseConfirm = true,
                itemToPurchase = item,
                purchaseQuantity = 1,
                purchaseRecipient = PurchaseRecipient.SELF
            )
        }
    }

    fun hidePurchaseConfirm() {
        _uiState.update {
            it.copy(
                showPurchaseConfirm = false,
                itemToPurchase = null,
                purchaseQuantity = 1
            )
        }
    }

    fun increaseQuantity() {
        val maxQuantity = _uiState.value.itemToPurchase?.let { item ->
            _uiState.value.balance.coins / maxOf(item.price, 1)
        } ?: 1

        _uiState.update {
            it.copy(
                purchaseQuantity = minOf(it.purchaseQuantity + 1, maxQuantity, 99)
            )
        }
    }

    fun decreaseQuantity() {
        _uiState.update {
            it.copy(
                purchaseQuantity = maxOf(it.purchaseQuantity - 1, 1)
            )
        }
    }

    fun selectRecipient(recipient: PurchaseRecipient) {
        _uiState.update { it.copy(purchaseRecipient = recipient) }
    }

    /**
     * 确认购买
     */
    fun confirmPurchase() {
        val item = _uiState.value.itemToPurchase ?: return
        val quantity = _uiState.value.purchaseQuantity
        val recipient = _uiState.value.purchaseRecipient.key

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }

            val result = shopRepository.purchaseItem(item.id, quantity, recipient)

            result.fold(
                onSuccess = { purchaseResult ->
                    _uiState.update { state ->
                        state.copy(
                            isLoading = false,
                            showPurchaseConfirm = false,
                            itemToPurchase = null,
                            purchaseQuantity = 1,
                            purchaseResult = purchaseResult,
                            showPurchaseResult = true,
                            balance = purchaseResult.newBalance ?: state.balance
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            showPurchaseConfirm = false,
                            itemToPurchase = null,
                            error = "购买失败: ${e.message}"
                        )
                    }
                }
            )
        }
    }

    fun hidePurchaseResult() {
        _uiState.update {
            it.copy(
                showPurchaseResult = false,
                purchaseResult = null
            )
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    // ==================== 礼物库存 ====================

    fun showGiftInventory() {
        _uiState.update { it.copy(showGiftInventory = true) }
        loadGiftInventory()
    }

    fun hideGiftInventory() {
        _uiState.update { it.copy(showGiftInventory = false) }
    }

    fun loadGiftInventory() {
        viewModelScope.launch {
            try {
                val gifts = shopRepository.getGiftInventory()
                _uiState.update { it.copy(giftInventory = gifts) }
            } catch (e: Exception) {
                // 静默失败
            }
        }
    }

    fun useGift(itemId: String, recipient: String = "self") {
        viewModelScope.launch {
            val result = shopRepository.useGiftItem(itemId, recipient)
            result.fold(
                onSuccess = { msg ->
                    _uiState.update {
                        it.copy(
                            useGiftResult = msg,
                            showUseGiftResult = true
                        )
                    }
                    // 刷新库存
                    loadGiftInventory()
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            useGiftResult = "使用失败: ${e.message}",
                            showUseGiftResult = true
                        )
                    }
                }
            )
        }
    }

    fun hideUseGiftResult() {
        _uiState.update {
            it.copy(
                showUseGiftResult = false,
                useGiftResult = null
            )
        }
    }
}
