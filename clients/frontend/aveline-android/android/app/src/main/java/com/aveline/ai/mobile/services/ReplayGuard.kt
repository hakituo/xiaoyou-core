package com.aveline.ai.mobile.services

import java.util.LinkedHashMap

/**
 * 远程指令重放防护。
 *
 * 后端下发的敏感指令(截图 / 位置 / 强停应用 / 蓝牙等)进入执行前先经过本门卫去重:
 * 同一 request_id / action_id 在时间窗内重复到达一律判定为重放并丢弃。
 *
 * 设计取舍:
 * - 全程无感, 不弹窗、不打断用户, 只做静默丢弃 —— 满足"远程截图等操作保持无感"的要求。
 * - 有界存储(LinkedHashMap 淘汰最旧条目), 避免长期运行内存膨胀。
 * - 事不过时: 超过 [windowMs] 的旧记录自动清掉, 防止历史 id 被永久占用。
 *
 * 说明: 本类只防"同一指令的重复重放"。若要防"攻击者伪造全新指令", 需后端对指令做
 * 签名 + nonce + 时间戳(客户端验签), 属于跨端协作项, 不在本客户端侧实现。
 */
class ReplayGuard(
    private val maxSize: Int = 512,
    private val windowMs: Long = 5 * 60 * 1000L
) {
    // accessOrder=false => 按插入顺序迭代, removeEldestEntry 淘汰最旧条目(近似 FIFO)
    private val seen = object : LinkedHashMap<String, Long>(128, 0.75f, false) {
        override fun removeEldestEntry(
            eldest: MutableMap.MutableEntry<String, Long>
        ): Boolean = size > maxSize
    }

    /**
     * 判断 [id] 是否为重放。
     *
     * @return true=该 id 在时间窗内已处理过, 属重放(调用方应丢弃);
     *         false=首次到达(调用方应正常执行), 本次会记录该 id。
     */
    fun isReplay(id: String, nowMs: Long = System.currentTimeMillis()): Boolean {
        val trimmed = id.trim()
        if (trimmed.isEmpty()) return false

        synchronized(seen) {
            // 先清理超过时间窗的旧记录, 避免历史 id 永久占用 / 误拦新指令
            val iterator = seen.entries.iterator()
            while (iterator.hasNext()) {
                if (nowMs - iterator.next().value > windowMs) iterator.remove()
            }

            return if (seen.containsKey(trimmed)) {
                true
            } else {
                seen[trimmed] = nowMs
                false
            }
        }
    }

    /** 清空全部记录(如手动断开重连后可调用, 避免积压)。 */
    fun clear() {
        synchronized(seen) { seen.clear() }
    }
}