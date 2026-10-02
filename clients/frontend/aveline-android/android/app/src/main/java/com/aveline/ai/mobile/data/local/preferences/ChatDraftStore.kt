package com.aveline.ai.mobile.data.local.preferences

import android.content.Context
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 聊天输入框草稿的本地存储，一个会话一份。
 *
 * 存在的原因：ChatViewModel 绑定在聊天页的 backStackEntry 上，从会话列表退出聊天页时
 * ViewModel 被清掉，输入框里没发出去的内容（uiState.inputText）跟着一起丢，
 * 再点进来是一片空白，用户得把话重打一遍。这里把它落到磁盘，重新进入同一会话时回填。
 *
 * 为什么单独一个 SP 文件而不是并到 [AppPreferences]：草稿是按会话累积的临时数据，
 * 条数会随使用增长、还要淘汰老草稿，和常年不变的全局设置混在一个 xml 里
 * 既不好清理，也会把设置文件养大。
 */
@Singleton
class ChatDraftStore @Inject constructor(
    @ApplicationContext context: Context
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** 读取会话草稿；没有草稿返回空串。 */
    fun readDraft(sessionId: String): String =
        if (sessionId.isBlank()) "" else prefs.getString(draftKey(sessionId), "").orEmpty()

    /**
     * 写入草稿（异步落盘），供打字过程中调用。
     *
     * 空串语义 = 删草稿：发送成功后输入框被清空，对应草稿也要跟着删，
     * 否则退出再进会看到一条早就发出去的话。
     */
    fun writeDraft(sessionId: String, text: String) {
        commitDraft(sessionId, text, sync = false)
    }

    /**
     * 同步落盘版本，用在「页面正在被销毁」的时刻。
     *
     * apply() 的写排在 QueuedWork 里异步执行，退出聊天页后如果进程很快被回收，
     * 那次写入可能根本没发生。这里必须 commit() 兜住最后一句话。
     */
    fun writeDraftSync(sessionId: String, text: String) {
        commitDraft(sessionId, text, sync = true)
    }

    fun clearDraft(sessionId: String) = writeDraft(sessionId, "")

    private fun commitDraft(sessionId: String, text: String, sync: Boolean) {
        if (sessionId.isBlank()) return
        val edit = prefs.edit()
        if (text.isBlank()) {
            edit.remove(draftKey(sessionId)).remove(timestampKey(sessionId))
        } else {
            edit.putString(draftKey(sessionId), text)
            edit.putLong(timestampKey(sessionId), System.currentTimeMillis())
        }
        // apply() 已经足够快（后台线程写）；sync=true 只用于退出前的最后一次。
        if (sync) edit.commit() else edit.apply()
        trimOldestIfNeeded()
    }

    /**
     * 条数上限保护：每个会话一条草稿，长期不清理会一直堆积。
     * 超过 [MAX_DRAFTS] 条时按最后一次编辑时间淘汰最旧的。
     */
    private fun trimOldestIfNeeded() {
        val sessionIds = (prefs.all ?: return).keys.mapNotNull { key ->
            key.takeIf { it.startsWith(DRAFT_PREFIX) }?.removePrefix(DRAFT_PREFIX)
        }
        if (sessionIds.size <= MAX_DRAFTS) return
        val expireCount = sessionIds.size - MAX_DRAFTS
        val edit = prefs.edit()
        sessionIds
            .sortedBy { prefs.getLong(timestampKey(it), 0L) }
            .take(expireCount)
            .forEach { id ->
                edit.remove(draftKey(id)).remove(timestampKey(id))
            }
        edit.apply()
    }

    private fun draftKey(sessionId: String): String = DRAFT_PREFIX + sessionId

    private fun timestampKey(sessionId: String): String = TIMESTAMP_PREFIX + sessionId

    companion object {
        private const val PREFS_NAME = "chat_input_drafts"
        private const val DRAFT_PREFIX = "draft_"
        private const val TIMESTAMP_PREFIX = "ts_"

        /** 最多留这么多条会话草稿，超出按最久没动过的先删。 */
        private const val MAX_DRAFTS = 100
    }
}
