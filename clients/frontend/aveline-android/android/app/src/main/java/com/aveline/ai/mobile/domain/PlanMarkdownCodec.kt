package com.aveline.ai.mobile.domain

import com.aveline.ai.mobile.domain.models.PlanItem

/**
 * plan.md 文本与 [PlanItem] 列表之间的解码器（领域层,与 UI/框架无关）。
 *
 * 只负责「后端 plan.md 投影 -> UI 列表」的解析。计划项的写入统一走后端计划真源
 * 接口（勾选 / 新增 / 编辑 / 删除），客户端**不再**把整篇 plan.md 序列化写回——
 * 那条路径只改投影、不写真源，会被后端计划同步覆盖，还会丢掉标题、备注与无时间项。
 *
 * 支持的行格式：
 * - `- [x] 08:00 物理复习（90分钟）`            → isDone=true
 * - `- [ ] 08:00 物理复习（90分钟） ✅`         → 行尾状态标记不进入 content
 * - `- [ ] 08:00 物理复习（90分钟） ⏭️`         → 跳过不算完成,isDone=false
 * - `- [~] 08:00 物理复习（90分钟） 🔄`         → 进行中,isDone=false
 * - `- [ ] 灵活 巩固昨日重点：general（60分钟）` → time="" 表示无固定时间
 * - `07:30 起床+早餐 (30分钟)`                  → 无 checkbox 标记
 *
 * 无法识别的行跳过。
 */
object PlanMarkdownCodec {

    private val timeRegex = Regex("""(\d{1,2}:\d{2})""")
    private val durationParenRegex = Regex("""[（(]([^()（）]+)[)）]\s*$""")
    private val checkboxRegex = Regex("""^[-*]\s*\[([ xX~])]\s*(.*)""")

    /** 后端对无固定时间的计划项统一写作"灵活" */
    private val flexibleTimeRegex = Regex("""^灵活\s+(.*)$""")

    /** 后端写在行尾的状态标记,不属于计划名称 */
    private val statusMarks = listOf("✅", "⏭️", "🔄")

    /**
     * 解析 plan.md 文本为计划项列表。
     */
    fun parse(text: String?): List<PlanItem> {
        if (text.isNullOrBlank()) return emptyList()
        val result = mutableListOf<PlanItem>()
        text.lines().forEach { rawLine ->
            // 兼容带 UTF-8 BOM 的旧文件：BOM 会让首行匹配不上 checkbox，整项恒显示未勾选
            val line = rawLine.trim().trimStart('\uFEFF').trim()
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
            workLine = workLine.trim()

            // 行尾状态标记不参与内容解析；⏭️ 表示跳过，不能显示成已完成
            statusMarks.forEach { mark ->
                if (workLine.endsWith(mark)) {
                    if (mark == "⏭️") isDone = false
                    workLine = workLine.removeSuffix(mark).trim()
                }
            }

            // 时间：优先 HH:mm；"灵活" 表示无固定时间
            var time = ""
            val timeMatch = timeRegex.find(workLine)
            val flexibleMatch = flexibleTimeRegex.matchEntire(workLine)
            val afterTime = when {
                timeMatch != null -> {
                    time = timeMatch.value
                    workLine.substring(timeMatch.range.last + 1).trim()
                }
                flexibleMatch != null -> flexibleMatch.groupValues[1].trim()
                else -> return@forEach
            }

            var duration = ""
            var content = afterTime
            val durMatch = durationParenRegex.find(afterTime)
            if (durMatch != null) {
                duration = durMatch.groupValues[1]
                content = afterTime.substring(0, durMatch.range.first).trim()
            }
            if (content.isEmpty()) content = afterTime

            result.add(
                PlanItem(time = time, content = content, duration = duration, isDone = isDone)
            )
        }
        return result
    }
}
