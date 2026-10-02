package com.aveline.ai.mobile.utils.text

import kotlin.random.Random

/**
 * 通用聊天文本断句与清洗——对外唯一入口（薄壳门面，只做委托与展示层组合）。
 *
 * 这套规则与 QQ 端同源：规则真源是 Python 端 `core/utils/text_segmenter.py`，
 * 本包是它的 Kotlin 等价实现。按职责拆分的兄弟模块：
 *
 * | 模块 | 职责 | 对应 Python 函数 |
 * |------|------|------------------|
 * | [TextSegmentRules] | 规则常量与预编译正则（单点真源） | 模块常量 |
 * | [TextCleaners] | 时间戳剥离 / 句尾标点清理 | `strip_ai_timestamp` 等 |
 * | [ChatMessageSplitter] | 断句主循环 | `split_chat_message` |
 * | [ChunkMerger] | 分段合并 / 空格分泡判定 | `merge_*` 系列 |
 * | [NumberedListSplitter] | 行内编号列表归一化 | `normalize_numbered_list` |
 * | [LongSentenceSplitter] | 强制长句分割 | `force_split_long_sentence` |
 * | [ContinuationWords] | 续接词判定 | `is_continuation_start` |
 * | [EmojiRanges] | emoji 范围表与判定 | `EMOJI_RANGES` |
 *
 * 两端规则常量必须保持一致，由
 * `tests/scripts/android_frontend/verify_text_segmenter_parity.py` 做对齐校验；
 * 唯一有意保留的实现差异是续接词识别（安卓端没有 jieba 分词库，见 [ContinuationWords]）。
 *
 * 调用方只 import 本门面，不直接依赖兄弟模块，内部结构调整不外溢：
 * - [com.aveline.ai.mobile.presentation.chat.ChatTextProcessor] 整段消息分段
 * - [com.aveline.ai.mobile.presentation.chat.ChatFlushManager] 流式气泡边界
 * - [com.aveline.ai.mobile.presentation.chat.ChatSendController] 落库前清洗
 * - [com.aveline.ai.mobile.presentation.components.MessageBubble] 展示前分段
 */
object TextSegmenter {

    // ------------------------------------------------------------------
    // 清洗（委托 TextCleaners）
    // ------------------------------------------------------------------

    /** 剥离模型模仿历史消息格式输出的时间戳（全局匹配，不只行首）。 */
    fun stripAiTimestamp(text: String): String = TextCleaners.stripAiTimestamp(text)

    /** 去除句尾多余标点（句号/逗号/省略号等），句中标点保留。 */
    fun stripTrailingPunctuation(text: String): String = TextCleaners.stripTrailingPunctuation(text)

    /** 展示/发送前的统一清洗：剥时间戳 + 去句尾多余标点。 */
    fun clean(text: String): String = TextCleaners.cleanText(text)

    // ------------------------------------------------------------------
    // 规则判定（委托 TextSegmentRules）
    // ------------------------------------------------------------------

    /** 判断字符是否是"硬气泡边界"标点（。.！!？?…）。 */
    fun isHardBoundary(ch: Char): Boolean = TextSegmentRules.isHardBoundary(ch)

    /** 判断字符是否是逗号/分号一类的软边界标点。 */
    fun isSoftBoundary(ch: Char): Boolean = TextSegmentRules.isSoftBoundary(ch)

    // ------------------------------------------------------------------
    // 断句（委托 ChatMessageSplitter）
    // ------------------------------------------------------------------

    /**
     * 把模型回复切成多个气泡，模拟真人碎句聊天节奏。
     *
     * 注意：断句只在"断点处"吃掉句号；某段只产出 1 块时会原样返回带句号的原文。
     * 展示场景请用 [splitForDisplay]，它会对每一段再清一次句尾。
     *
     * @param random 逗号断句的随机源，注入固定种子即可在测试里得到确定结果
     */
    fun splitMessage(
        text: String,
        maxLen: Int = 150,
        commaSplitProb: Double = 0.2,
        minSplitLen: Int = 40,
        passThroughMarkers: List<String> = emptyList(),
        random: Random = Random.Default,
    ): List<String> = ChatMessageSplitter.splitMessage(
        text,
        maxLen,
        commaSplitProb,
        minSplitLen,
        passThroughMarkers,
        random,
    )

    // ------------------------------------------------------------------
    // 展示层组合（Markdown / LaTeX 守卫 + 逐段清洗）
    // ------------------------------------------------------------------

    /** 单行块级结构：代码块 / 标题 / 列表 / 引用块。 */
    private val MARKDOWN_BLOCK_START_REGEX = Regex("(?m)^\\s{0,3}(?:```|~~~|#{1,6}\\s|[-*+]\\s|>)")

    /** Markdown 表格行：整行由 `|` 包裹。 */
    private val MARKDOWN_TABLE_LINE_REGEX = Regex("^\\s*\\|.*\\|\\s*$")

    /**
     * 未转义的 `$$` 表示 LaTeX 边界。
     *
     * 流式阶段可能只收到开头的一个 `$$`，因此只要出现 marker 就整行保留；不能等到成对闭合后再保护，
     * 否则中间帧仍会先被按换行拆成多个气泡，最终 renderer 无法恢复原始数学块。
     */
    private val LATEX_MARKER_REGEX = Regex("(?<!\\\\)\\$\\$")

    /** 按结构分组后的文本块：[atomic] 为真表示整块保留，不再交给断句器切分。 */
    private data class DisplayGroup(val text: String, val atomic: Boolean)

    /**
     * 按 Markdown 块级结构把清洗后的文本切成"组"。
     *
     * 只有真正跨行连续的结构（代码围栏 / 块级公式 / 表格）和单行的块级标记
     * （标题 / 列表项 / 引用 / 含 `$$` 的行）需要整组保留；普通段落行照常交给
     * [splitMessage] 按标点切气泡。
     *
     * 旧实现是"命中任一标记就整条消息透传"：模型输出里只要出现一个 `- ` 列表项、
     * 一个 `#` 标题或一对 `|`，整条回复就退化成一个大气泡、换行原样显示，而同样措辞
     * 但没用 markdown 的另一条回复却被正常切成多个气泡。这就是"一会能断句一会不能
     * 断句"的来源。改成按行分组后，断句行为只取决于文本本身，与模型这一轮有没有用
     * markdown 无关。
     */
    private fun groupByStructure(text: String): List<DisplayGroup> {
        val lines = text.split('\n')
        val groups = mutableListOf<DisplayGroup>()
        var index = 0

        while (index < lines.size) {
            val line = lines[index]
            val stripped = line.trim()
            if (stripped.isEmpty()) {
                index++
                continue
            }

            // 1) 代码围栏：从 ``` / ~~~ 起一直到闭合围栏（流式未闭合就吃到结尾）。
            val fence = when {
                stripped.startsWith("```") -> "```"
                stripped.startsWith("~~~") -> "~~~"
                else -> null
            }
            if (fence != null) {
                val buf = mutableListOf<String>()
                var cursor = index
                while (cursor < lines.size) {
                    buf += lines[cursor]
                    cursor++
                    // cursor - 1 == index 时刚收进去的是开启围栏本身，不能当闭合围栏
                    if (cursor > index + 1 && lines[cursor - 1].trim().startsWith(fence)) break
                }
                groups += DisplayGroup(buf.joinToString("\n"), atomic = true)
                index = cursor
                continue
            }

            // 2) 块级公式 $$ ... $$：整体保留，流式阶段未闭合也保留。
            if (stripped == "$$") {
                val buf = mutableListOf<String>()
                var cursor = index
                while (cursor < lines.size) {
                    buf += lines[cursor]
                    cursor++
                    if (cursor > index + 1 && lines[cursor - 1].trim() == "$$") break
                }
                groups += DisplayGroup(buf.joinToString("\n"), atomic = true)
                index = cursor
                continue
            }

            // 3) 连续的表格行：整组保留，否则表头 / 分隔行 / 数据行会被拆散。
            if (MARKDOWN_TABLE_LINE_REGEX.containsMatchIn(line)) {
                val buf = mutableListOf<String>()
                var cursor = index
                while (cursor < lines.size && MARKDOWN_TABLE_LINE_REGEX.containsMatchIn(lines[cursor])) {
                    buf += lines[cursor].trim()
                    cursor++
                }
                groups += DisplayGroup(buf.joinToString("\n"), atomic = true)
                index = cursor
                continue
            }

            // 4) 单行块级结构（标题 / 列表项 / 引用 / 含 $$）：整行保留。
            val atomic = MARKDOWN_BLOCK_START_REGEX.containsMatchIn(stripped) ||
                LATEX_MARKER_REGEX.containsMatchIn(stripped)
            groups += DisplayGroup(stripped, atomic)
            index++
        }

        return groups
    }

    /**
     * 展示前把 AI 回复拆成多个"气泡"：清洗（时间戳 / 句末句号）+ 按结构分组 + 断句。
     *
     * - 断句只在"断点处"吃掉句号，某段只产出 1 块时会原样返回带句号的原文
     *   （例如换行分段后的"你要求的。"），所以**每一段**都要再清一次句尾——
     *   与 QQ 端一致：QQ 是 split 之后对每条消息单独 strip 再发送。
     * - 分组规则见 [groupByStructure]：整组保留的块（代码 / 公式 / 表格 / 单行块级标记）
     *   不再二次 strip，避免把代码末尾的点也吃掉。
     */
    fun splitForDisplay(text: String): List<String> {
        val cleaned = clean(text)
        if (cleaned.isEmpty()) return emptyList()
        val result = mutableListOf<String>()
        for (group in groupByStructure(cleaned)) {
            if (group.atomic) {
                if (group.text.isNotBlank()) result += group.text
                continue
            }
            splitMessage(group.text)
                .map { stripTrailingPunctuation(it) }
                .filter { it.isNotEmpty() }
                .forEach(result::add)
        }
        return result
    }
}
