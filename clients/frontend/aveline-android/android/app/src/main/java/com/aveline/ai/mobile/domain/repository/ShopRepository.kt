package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.GiftInventoryItem
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.domain.models.UserBalance

/** 商城在应用进程内保存的某一类目分页快照。 */
data class ShopCacheSnapshot(
    val items: List<ShopItem>,
    val balance: UserBalance,
    val currentPage: Int,
    val hasMore: Boolean,
    val updatedAtMillis: Long
)

/**
 * 商城仓库接口
 */
interface ShopRepository {

    /**
     * 立即读取内存缓存，不发起网络请求；应用进程内跨商城 ViewModel 复用。
     */
    fun getCachedShopSnapshot(category: ShopCategory?): ShopCacheSnapshot?

    /**
     * 分页获取商城商品(按类别过滤)
     * @param category 类别(null=全部)
     * @param page 页码(从1开始)
     * @param pageSize 每页数量
     * @return 商品列表 + 是否还有更多
     */
    suspend fun getShopItems(
        category: ShopCategory? = null,
        page: Int = 1,
        pageSize: Int = 20
    ): Pair<List<ShopItem>, Boolean>

    /**
     * 获取物品详情(从缓存)
     */
    suspend fun getItemById(itemId: String): ShopItem?

    /**
     * 获取用户余额
     */
    suspend fun getBalance(): UserBalance

    /**
     * 购买商品
     * @param itemId 商品ID
     * @param quantity 数量
     * @param recipient 给谁买(self/aveline/ling)
     */
    suspend fun purchaseItem(
        itemId: String,
        quantity: Int = 1,
        recipient: String = "self"
    ): Result<PurchaseResult>

    /**
     * 获取礼物/非食物商品库存
     */
    suspend fun getGiftInventory(): List<GiftInventoryItem>

    /**
     * 使用/赠送非食物商品
     * @param itemId 商品ID
     * @param recipient 给谁用
     */
    suspend fun useGiftItem(itemId: String, recipient: String = "self"): Result<String>
}
