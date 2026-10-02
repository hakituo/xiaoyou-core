package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 消息树路径提取的回归测试。
 *
 * 背景：会话超过 200 条时 `enforceMessageLimit` 会删掉最旧的消息，而最旧的那条
 * 正是 `parentId == null` 的树根。根没了以后，剩下所有消息的父链都指向已删除的
 * 节点，`selectActiveConversationPath` 找不到入口会返回空列表 —— 用户看到的
 * 现象就是"聊着聊着整个聊天页变空"。
 *
 * 这里钉住两件事：
 * 1. 链路完整时必须返回完整路径；
 * 2. **断根时必须退化取最旧一条当根，绝不能返回空列表**。
 */
class MessageTreePathTest {

    private fun msg(
        id: String,
        ts: Long,
        parentId: String? = null,
        isUser: Boolean = false,
        variantIndex: Int = 0,
        isActiveVariant: Boolean = true
    ) = MessageEntity(
        id = id,
        text = "m$id",
        isUser = isUser,
        timestamp = ts,
        sessionId = "s1",
        parentId = parentId,
        variantIndex = variantIndex,
        isActiveVariant = isActiveVariant
    )

    @Test
    fun `完整链路按时间顺序返回整条路径`() {
        val entities = listOf(
            msg("a", 100),
            msg("b", 200, parentId = "a", isUser = true),
            msg("c", 300, parentId = "b")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("a", "b", "c"), path.map { it.id })
    }

    @Test
    fun `断根时退化取最旧一条当根而不是返回空列表`() {
        // 根 "a" 已被裁剪删除，"b" 的 parentId 成了悬空引用
        val entities = listOf(
            msg("b", 200, parentId = "a"),
            msg("c", 300, parentId = "b"),
            msg("d", 400, parentId = "c")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("b", "c", "d"), path.map { it.id })
    }

    @Test
    fun `整棵树全部悬空时至少保住最旧一条`() {
        val entities = listOf(
            msg("x", 100, parentId = "gone"),
            msg("y", 200, parentId = "gone2")
        )

        val path = selectActiveConversationPath(entities)

        assertTrue("断根的会话不能返回空列表", path.isNotEmpty())
        assertEquals("x", path.first().id)
    }

    @Test
    fun `空输入返回空列表`() {
        assertTrue(selectActiveConversationPath(emptyList()).isEmpty())
    }

    @Test
    fun `只走激活变体那条分支`() {
        val entities = listOf(
            msg("a", 100),
            msg("b1", 200, parentId = "a", isUser = true, variantIndex = 0, isActiveVariant = false),
            msg("b2", 210, parentId = "a", isUser = true, variantIndex = 1, isActiveVariant = true),
            msg("c", 300, parentId = "b2")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("a", "b2", "c"), path.map { it.id })
        // 版本计数：同一父节点下同为用户的兄弟共 2 个
        assertEquals(2, path[1].variantCount)
        assertEquals(1, path[1].variantIndex)
    }

    @Test
    fun `循环引用不会死循环`() {
        val entities = listOf(
            msg("a", 100, parentId = "c"),
            msg("b", 200, parentId = "a"),
            msg("c", 300, parentId = "b")
        )

        val path = selectActiveConversationPath(entities)

        assertTrue(path.isNotEmpty())
        assertTrue("同一节点不应重复出现", path.distinctBy { it.id }.size == path.size)
    }

    /**
     * 同一轮回复里的多张表情包必须**串成一条链**，不能都挂在 AI 正文气泡下面。
     *
     * 这是线上"连着发几个表情包，要点切换键才看得到"的根因：
     * 消息树把「同一个父节点 + 同为 AI」的节点视为互为版本，只走 isActiveVariant
     * 的那一条，于是三张图折叠成一个槽位、旁边多出一个 `1/3` 切换键。
     * 串成 user -> aiText -> img1 -> img2 -> img3 后，每张图的兄弟数都是 1。
     */
    @Test
    fun `同一轮多张表情包串成链时全部按顺序渲染`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("aiText", 200, parentId = "user"),
            msg("img1", 300, parentId = "aiText"),
            msg("img2", 400, parentId = "img1"),
            msg("img3", 500, parentId = "img2")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("user", "aiText", "img1", "img2", "img3"), path.map { it.id })
        // 每张图都没有兄弟，界面不会画出切换键
        listOf(2, 3, 4).forEach { i ->
            assertEquals("第 ${i - 1} 张表情包不应有版本切换键", 1, path[i].variantCount)
            assertEquals(0, path[i].variantIndex)
        }
    }

    /** 反例：都挂在 AI 正文下 → 只剩一张可见，其余被折叠成版本（这条钉住"不能这么存"）。 */
    @Test
    fun `同一轮多张表情包都挂在正文下会被折叠成版本`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("aiText", 200, parentId = "user"),
            msg("img1", 300, parentId = "aiText"),
            msg("img2", 400, parentId = "aiText"),
            msg("img3", 500, parentId = "aiText")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("user", "aiText", "img1"), path.map { it.id })
        assertEquals(3, path.last().variantCount)
    }

    /**
     * 后端按 [MEME] 标签位置下发图片后，一条回复会被切成
     * `正文1 -> 图 -> 正文2 -> 图 -> 正文3`。
     *
     * 这条钉住切分后的链路形状：每段正文与每张图都是链上独立的一环，
     * 顺序即"图在它那句话之后"，且没有任何一环出现版本切换键。
     */
    @Test
    fun `正文被表情包切成多段时按顺序渲染`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("t1", 200, parentId = "user"),
            msg("img1", 300, parentId = "t1"),
            msg("t2", 400, parentId = "img1"),
            msg("img2", 500, parentId = "t2"),
            msg("t3", 600, parentId = "img2")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(
            listOf("user", "t1", "img1", "t2", "img2", "t3"),
            path.map { it.id }
        )
        path.drop(1).forEach { node ->
            assertEquals("链路每一环都不该有版本切换键", 1, node.variantCount)
        }
    }

    /** 回复以表情包开头/结尾时，空气泡留在链上只当链接（UI 渲染成空气泡）。 */
    @Test
    fun `回复以表情包开头时空气泡只当链接不打断链路`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("blankText", 200, parentId = "user"),
            msg("img", 300, parentId = "blankText"),
            msg("t2", 400, parentId = "img")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("user", "blankText", "img", "t2"), path.map { it.id })
        assertEquals(1, path[2].variantCount)
    }

    /**
     * 安卓端连发多张表情包时的**真实**链路形状。
     *
     * 每次收到媒体事件，客户端都会在媒体下面新开一条空正文占位当"链上的连接点"
     * （渲染成空气泡，看不见），所以三张图的形状是
     * `img1 -> 空占位 -> img2 -> 空占位 -> img3`，而不是 img1 -> img2 -> img3。
     *
     * 这条钉住"中间夹着空占位也不能把图挤出活跃路径"：
     * 第二张图必须挂在**空占位**下，不能挂回第一张图下。
     */
    @Test
    fun `连发多张表情包时每张图之间夹着空占位仍按顺序全部渲染`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("blankText", 200, parentId = "user"),
            msg("img1", 300, parentId = "blankText"),
            msg("ph1", 400, parentId = "img1"),
            msg("img2", 500, parentId = "ph1"),
            msg("ph2", 600, parentId = "img2"),
            msg("img3", 700, parentId = "ph2"),
            msg("ph3", 800, parentId = "img3")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(
            listOf("user", "blankText", "img1", "ph1", "img2", "ph2", "img3", "ph3"),
            path.map { it.id }
        )
        listOf("img1", "img2", "img3").forEach { id ->
            val node = path.first { it.id == id }
            assertEquals("$id 不该被挤出活跃路径", 1, node.variantCount)
        }
    }

    /**
     * 反例：第二张图挂回第一张图下（而不是挂在那段的空占位下）。
     *
     * 这是 `mediaTailId` 方案的缺陷：img2 与 ph1 同父、同为 AI，于是互为版本，
     * `selectActiveMessageEntities` 每层只跟一个激活子节点、ph1 时间更早被选中，
     * img2 整条子树（含 img3）都从活跃路径上消失 —— 表现为"连发多张只剩第一张"。
     */
    @Test
    fun `第二张图挂回第一张图下会被空占位挤出活跃路径`() {
        val entities = listOf(
            msg("user", 100, isUser = true),
            msg("blankText", 200, parentId = "user"),
            msg("img1", 300, parentId = "blankText"),
            msg("ph1", 400, parentId = "img1"),
            msg("img2", 500, parentId = "img1"),
            msg("img3", 600, parentId = "img2")
        )

        val path = selectActiveConversationPath(entities)

        assertEquals(listOf("user", "blankText", "img1", "ph1"), path.map { it.id })
        assertTrue("img2 不该出现在活跃路径上", path.none { it.id == "img2" })
    }
}
