package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.domain.models.GiftInventoryItem
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.domain.models.UserBalance
import com.aveline.ai.mobile.domain.repository.ShopRepository
import com.aveline.ai.mobile.domain.repository.ShopCacheSnapshot
import kotlinx.coroutines.CancellationException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 商城仓库实现
 *
 * 调用 /api/v1/food/shop/menu 分页接口,
 * 支持 7 个类别(food/gift/toy/book/clothing/tech/luxury) + recipient。
 * 商城余额同样以后端 shop/menu 返回值为准，不再复用角色 life/status 的 coins。
 */
@Singleton
class ShopRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService
) : ShopRepository {

    private data class CachedPage(
        val items: List<ShopItem>,
        val hasMore: Boolean
    )

    private val cacheLock = Any()
    private val cachedPages = mutableMapOf<String, MutableMap<Int, CachedPage>>()
    private val cacheUpdatedAt = mutableMapOf<String, Long>()
    @Volatile
    private var cachedBalance: UserBalance = UserBalance(coins = 0, totalEarned = 0)

    override fun getCachedShopSnapshot(category: ShopCategory?): ShopCacheSnapshot? {
        val key = category.cacheKey()
        return synchronized(cacheLock) {
            val pages = cachedPages[key]?.toSortedMap().orEmpty()
            if (pages.isEmpty()) return@synchronized null
            val lastPage = pages.keys.maxOrNull() ?: 1
            ShopCacheSnapshot(
                items = pages.values.flatMap { it.items }.distinctBy { it.id },
                balance = cachedBalance,
                currentPage = lastPage,
                hasMore = pages[lastPage]?.hasMore ?: false,
                updatedAtMillis = cacheUpdatedAt[key] ?: 0L
            )
        }
    }

    override suspend fun getShopItems(
        category: ShopCategory?,
        page: Int,
        pageSize: Int
    ): Pair<List<ShopItem>, Boolean> {
        return try {
            val response = apiService.getShopMenu(
                category = category?.name?.lowercase(),
                page = page,
                pageSize = pageSize
            )
            val items = response.items.map { it.toDomainModel() }
            val backendBalance = UserBalance(
                coins = response.coins,
                totalEarned = response.coins
            )

            val key = category.cacheKey()
            synchronized(cacheLock) {
                val pages = cachedPages.getOrPut(key) { mutableMapOf() }
                // 第一页刷新代表一次新快照，旧的后续页不能继续拼接。
                if (page == 1) pages.clear()
                pages[page] = CachedPage(items, response.has_more)
                cachedBalance = backendBalance
                cacheUpdatedAt[key] = System.currentTimeMillis()
            }

            Pair(items, response.has_more)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val cachedPage = synchronized(cacheLock) {
                cachedPages[category.cacheKey()]?.get(page)
            }
            cachedPage?.let { Pair(it.items, it.hasMore) } ?: Pair(emptyList(), false)
        }
    }

    override suspend fun getItemById(itemId: String): ShopItem? {
        // 先从缓存找
        synchronized(cacheLock) {
            cachedPages.values.asSequence()
                .flatMap { it.values.asSequence() }
                .flatMap { it.items.asSequence() }
                .firstOrNull { it.id == itemId }
        }?.let { return it }
        // 缓存没有就加载第一页再找
        return try {
            val (items, _) = getShopItems(page = 1, pageSize = 100)
            items.find { it.id == itemId }
        } catch (e: Exception) {
            null
        }
    }

    override suspend fun getBalance(): UserBalance {
        return try {
            // 商城余额必须由商城接口本身给出。life/status 的 coins 是角色生命状态字段，
            // 与当前无限金币商城语义不是同一个数据源。
            val response = apiService.getShopMenu(page = 1, pageSize = 1)
            val balance = UserBalance(
                coins = response.coins,
                totalEarned = response.coins
            )
            cachedBalance = balance
            balance
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            cachedBalance
        }
    }

    override suspend fun purchaseItem(
        itemId: String,
        quantity: Int,
        recipient: String
    ): Result<PurchaseResult> {
        return try {
            val response = apiService.buyShopItem(itemId, quantity, recipient)

            val success = response.success ?: false
            if (success) {
                getBalance()
            }

            val result = PurchaseResult(
                success = success,
                message = response.message ?: if (success) "购买成功" else "购买失败",
                newBalance = cachedBalance
            )

            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getGiftInventory(): List<GiftInventoryItem> {
        return try {
            val response = apiService.getGiftInventory()
            response.data.map { it.toDomainModel() }
        } catch (e: Exception) {
            emptyList()
        }
    }

    override suspend fun useGiftItem(itemId: String, recipient: String): Result<String> {
        return try {
            val response = apiService.useGiftItem(itemId, recipient)
            val success = response.success ?: false
            if (success) {
                val effects = response.applied_effects
                val effectText = if (!effects.isNullOrEmpty()) {
                    effects.entries.joinToString(", ") { "${it.key}+${it.value.toInt()}" }
                } else ""
                Result.success(response.message ?: "使用成功" + if (effectText.isNotEmpty()) " ($effectText)" else "")
            } else {
                Result.success(response.message ?: "使用失败")
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}

private fun ShopCategory?.cacheKey(): String = this?.name ?: "ALL"
