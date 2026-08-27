package com.aveline.ai.mobile.domain

import com.aveline.ai.mobile.domain.models.PlanItem

/**
 * plan.md 文本与 [PlanItem] 列表之间的编解码器（领域层,与 UI/框架无关）。
 *
 * - [parse]：将后端 plan.md 文本解析为 [PlanItem] 列表。
 * - [serialize]：将 [PlanItem] 列表重新序列化为 plan.md 文本。
 *
 * 二者为 round-trip 兼容：serialize(parse(text)) 能还原原有结构（在支持的行格式内）。
 *
 * 支持的行格式：
 * - "07:30 起床+早餐 (30分钟)"        → time=07:30 content=起床+早餐 duration=30分钟
 * - "- [x] 08:00 物理复习 (90分钟)"    → isDone=true
 * - "- [ ] 08:00 物理复习 (90分钟)"    → isDone=false
 * - "- 08:00 物理复习 (90分钟)"        → 无 checkbox 标记
 *
 * 无法识别的行跳过。
 */
object PlanMarkdownCodec {

    private val timeRegex = Regex("""(\d{1,2}:\d{2})""")
    private val durationParenRegex = Regex("""[（(]([^()（）]+)[)）]\s*$""")
    private val checkboxRegex = Regex("""^[-*]\s*\[([ xX])]\s*(.*)""")

    /**
     * 解析 plan.md 文本为计划项列表。
     */
    fun parse(text: String?): List<PlanItem> {
        if (text.isNullOrBlank()) return emptyList()
        val result = mutableListOf<PlanItem>()
        text.lines().forEach { rawLine ->
            val line = rawLine.trim()
            if (line.isEmpty()) return@forEach

            var isDone = false
            var workLine = line
            val checkboxMatch = checkboxRegex.matchEntire(line)
            if (checkboxMatch != null) {
                isDone = checkboxMatch.groupValues[1].equals("x", ignoreCase = true)
                workLine = checkboxMatch.groupValues[2]
            } else if (line.startsWith("- ") || line.startsWith("* ")) {
                workLine = line.drop(2).trim()
            }

            // 兼容后端旧格式 "[x] ... ⏭️"：跳过不等于完成。
            if (workLine.trimEnd().endsWith("⏭️")) {
                isDone = false
            }

            val timeMatch = timeRegex.find(workLine) ?: return@forEach
            val time = timeMatch.value
            val afterTime = workLine.substring(timeMatch.range.last + 1).trim()

            var duration = ""
            var content = afterTime
            val durMatch = durationParenRegex.find(afterTime)
            if (durMatch != null) {
                duration = durMatch.groupValues[1]
                content = afterTime.substring(0, durMatch.range.first).trim()
            }
            if (content.isEmpty()) content = afterTime

            result.add(PlanItem(time = time, content = content, duration = duration, isDone = isDone))
        }
        return result
    }

    /**
     * 将计划项列表序列化为 plan.md 文本。
     *
     * 生成格式与 [parse] 兼容：
     * "- [x] 08:00 物理复习 （90分钟）" / "- [ ] 07:30 起床+早餐"
     */
    fun serialize(items: List<PlanItem>): String {
        return items.joinToString("\n") { item ->
            val checkbox = if (item.isDone) "- [x]" else "- [ ]"
            val durationPart = if (item.duration.isNotBlank()) " （${item.duration}）" else ""
            "$checkbox ${item.time} ${item.content}$durationPart"
        } + "\n"
    }
}
