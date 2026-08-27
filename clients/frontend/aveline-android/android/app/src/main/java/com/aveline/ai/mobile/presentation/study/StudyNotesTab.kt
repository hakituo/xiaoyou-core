package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.components.LatexMath
import com.aveline.ai.mobile.presentation.components.claimHorizontalContentGesture
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 知识笔记 Tab。
 *
 * 以文件夹树形式展示学习库（D:\AI\Study）中的 .md 笔记：
 * - 顶层为科目文件夹，下面按实际目录层级展开
 * - 隐藏目录/文件（如 .trae、.qoder）已在后端和本地双重过滤
 * - 默认仅展开顶层科目，子文件夹默认折叠，避免一次性渲染过多节点
 * - 点击文件进入全屏 [NoteReaderScreen] 阅读，内容走内存/磁盘/后端三级缓存懒加载
 *
 * @param notesUiState 知识笔记域 UI 状态
 * @param onOpenNote 打开笔记回调（传入相对路径）
 * @param onCloseReader 关闭阅读页回调
 */
@Composable
fun StudyNotesTab(
    notesUiState: StudyNotesUiState,
    onOpenNote: (String) -> Unit,
    onCloseReader: () -> Unit
) {
    val noteTree = notesUiState.noteTree
    val totalCount = remember(noteTree) { noteTree.sumOf { it.fileCount() } }

    // 展开集合：每次更新都赋新 Set 实例（保证 MutableState 正确触发重组）。
    // 默认全部折叠，用户点击文件夹才展开，避免进入页面时一片铺开。
    var expandedPaths by remember { mutableStateOf(setOf<String>()) }

    // 根据展开集合生成扁平可见节点列表（含缩进层级），LazyColumn 只组合可见项
    val visibleNodes = remember(noteTree, expandedPaths) {
        flattenVisibleNodes(noteTree, expandedPaths)
    }

    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp)
        ) {
            item {
                SectionCard(title = "知识笔记") {
                    if (noteTree.isEmpty()) {
                        Text(
                            text = "学习库暂无笔记",
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextTertiary,
                            modifier = Modifier.padding(vertical = 12.dp)
                        )
                    } else {
                        Text(
                            text = "共 ${totalCount} 篇笔记 · ${noteTree.size} 个科目，点击文件夹展开/折叠，点击文件阅读",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary,
                            modifier = Modifier.padding(bottom = 12.dp)
                        )
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            visibleNodes.forEach { (node, depth) ->
                                NoteTreeItem(
                                    node = node,
                                    depth = depth,
                                    isExpanded = expandedPaths.contains(node.path),
                                    onFolderClick = {
                                        expandedPaths = if (node.path in expandedPaths)
                                            expandedPaths - node.path
                                        else
                                            expandedPaths + node.path
                                    },
                                    onFileClick = { onOpenNote(node.path) }
                                )
                            }
                        }
                    }
                }
            }
        }

        // 全屏阅读页
        if (notesUiState.isReaderOpen) {
            NoteReaderScreen(
                uiState = notesUiState,
                onClose = onCloseReader
            )
        }
    }
}

/** 可见节点 + 缩进层级 */
private data class VisibleNode(val node: NoteTreeNode, val depth: Int)

/** 根据展开集合把树展开成扁平列表 */
private fun flattenVisibleNodes(
    nodes: List<NoteTreeNode>,
    expanded: Set<String>,
    depth: Int = 0
): List<VisibleNode> = buildList {
    nodes.forEach { node ->
        add(VisibleNode(node, depth))
        if (node is NoteTreeNode.Folder && node.path in expanded) {
            addAll(flattenVisibleNodes(node.children, expanded, depth + 1))
        }
    }
}

/** 单个树节点项：文件夹或文件 */
@Composable
private fun NoteTreeItem(
    node: NoteTreeNode,
    depth: Int,
    isExpanded: Boolean,
    onFolderClick: () -> Unit,
    onFileClick: () -> Unit
) {
    val startPadding = (16 * depth).dp
    val iconColor = when (node) {
        is NoteTreeNode.Folder -> Color(0xFFF59E0B)
        is NoteTreeNode.File -> Primary
    }
    val icon = when (node) {
        is NoteTreeNode.Folder -> if (isExpanded) Icons.Default.FolderOpen else Icons.Default.Folder
        is NoteTreeNode.File -> Icons.AutoMirrored.Filled.Article
    }
    val countText = if (node is NoteTreeNode.Folder) "（${node.fileCount()}）" else ""

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(Color(0x14000000))
            .clickable {
                when (node) {
                    is NoteTreeNode.Folder -> onFolderClick()
                    is NoteTreeNode.File -> onFileClick()
                }
            }
            .padding(start = 12.dp + startPadding, top = 10.dp, end = 12.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = iconColor,
            modifier = Modifier.width(20.dp).height(20.dp)
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = node.name + countText,
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold),
                color = TextPrimary
            )
            if (node is NoteTreeNode.File) {
                // 副标题显示所在目录（去掉文件名），顶层散文件则不显示
                val parentDir = node.path.removeSuffix("/${node.note.filename}").let {
                    if (it == node.note.filename) "" else it
                }
                if (parentDir.isNotBlank()) {
                    Text(
                        text = parentDir,
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                        maxLines = 1
                    )
                }
            }
        }
        if (node is NoteTreeNode.Folder) {
            Icon(
                imageVector = if (isExpanded) Icons.Default.ExpandLess else Icons.Default.ChevronRight,
                contentDescription = if (isExpanded) "折叠" else "展开",
                tint = TextTertiary
            )
        }
    }
}

/**
 * 笔记阅读页（全屏覆盖）。
 *
 * 正经的 Markdown 文档阅读界面：顶部返回 + 标题/路径，正文用 LazyColumn 渲染。
 */
@Composable
private fun NoteReaderScreen(
    uiState: StudyNotesUiState,
    onClose: () -> Unit
) {
    val content = uiState.currentNoteContent
    val isLoading = uiState.isLoading && content == null
    val error = uiState.error

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0F0F13))
            .statusBarsPadding()
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // 顶部栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                IconButton(onClick = onClose) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = TextPrimary
                    )
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = content?.filename?.removeSuffix(".md") ?: "笔记",
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary,
                        maxLines = 1
                    )
                    if (content?.path != null) {
                        Text(
                            text = content.path,
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary,
                            maxLines = 1
                        )
                    }
                }
            }

            // 内容区
            Box(modifier = Modifier.fillMaxSize()) {
                when {
                    isLoading -> {
                        CircularProgressIndicator(
                            modifier = Modifier.align(Alignment.Center),
                            color = Primary
                        )
                    }
                    error != null && content == null -> {
                        Text(
                            text = error,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier
                                .align(Alignment.Center)
                                .padding(24.dp)
                        )
                    }
                    content != null -> {
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(horizontal = 16.dp),
                            contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp)
                        ) {
                            item {
                                NotesMarkdownRenderer(text = content.content)
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * 笔记 Markdown 渲染器。
 *
 * 支持:标题(#/##/###)、无序列表(- 星号)、引用(>)、粗体(**text**)、表格(|)、代码块(```)、分隔线(---)、
 * 行内 LaTeX($...$)、块级 LaTeX($$...$$)。
 *
 * @param text Markdown 文本
 */
@Composable
fun NotesMarkdownRenderer(text: String) {
    val lines = text.lines()
    var inCodeBlock = false
    var inMathBlock = false
    val codeBlockLines = mutableListOf<String>()
    val mathBlockLines = mutableListOf<String>()
    val tableLines = mutableListOf<String>()

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        lines.forEach { line ->
            val trimmed = line.trim()

            // 块级 LaTeX 处理: $$...$$
            if (trimmed == "$$") {
                if (inMathBlock) {
                    inMathBlock = false
                    RenderMathBlock(mathBlockLines.toList())
                    mathBlockLines.clear()
                } else {
                    inMathBlock = true
                }
                return@forEach
            }
            if (inMathBlock) {
                mathBlockLines.add(line)
                return@forEach
            }

            // 代码块处理
            if (trimmed.startsWith("```")) {
                if (inCodeBlock) {
                    // 结束代码块
                    inCodeBlock = false
                    RenderCodeBlock(codeBlockLines.toList())
                    codeBlockLines.clear()
                } else {
                    // 开始代码块
                    inCodeBlock = true
                }
                return@forEach
            }
            if (inCodeBlock) {
                codeBlockLines.add(line)
                return@forEach
            }

            // 表格处理
            if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
                tableLines.add(trimmed)
                return@forEach
            } else if (tableLines.isNotEmpty()) {
                // 表格结束,渲染
                RenderTable(tableLines.toList())
                tableLines.clear()
            }

            val quote = parseMarkdownQuote(trimmed)
            when {
                trimmed.isEmpty() -> Spacer(modifier = Modifier.height(2.dp))
                trimmed.startsWith("# ") -> Text(
                    text = trimmed.removePrefix("# ").trim(),
                    style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                    color = TextPrimary
                )
                trimmed.startsWith("## ") -> {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = trimmed.removePrefix("## ").trim(),
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary
                    )
                }
                trimmed.startsWith("### ") -> Text(
                    text = trimmed.removePrefix("### ").trim(),
                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
                    color = Primary
                )
                quote != null -> RenderMarkdownQuote(quote)
                trimmed.startsWith("- ") || trimmed.startsWith("* ") -> Row(modifier = Modifier.fillMaxWidth()) {
                    Text("•", style = MaterialTheme.typography.bodyMedium, color = Primary, modifier = Modifier.width(20.dp))
                    RenderRichText(trimmed.drop(2).trim(), MaterialTheme.typography.bodyMedium, TextPrimary)
                }
                trimmed == "---" -> Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(1.dp)
                        .background(Color(0x2AFFFFFF))
                )
                else -> RenderRichText(trimmed, MaterialTheme.typography.bodyMedium, TextPrimary)
            }
        }

        // 处理末尾残留的表格
        if (tableLines.isNotEmpty()) {
            RenderTable(tableLines.toList())
        }
        // 处理末尾残留的代码块
        if (inCodeBlock && codeBlockLines.isNotEmpty()) {
            RenderCodeBlock(codeBlockLines.toList())
        }
        // 处理末尾残留的块级公式
        if (inMathBlock && mathBlockLines.isNotEmpty()) {
            RenderMathBlock(mathBlockLines.toList())
        }
    }
}

/** Markdown 引用行；depth 大于 1 时表示引用中的子回复。 */
private data class MarkdownQuote(val depth: Int, val content: String)

/**
 * 解析 `> 回复`、`>> 子回复` 和 `> > 子回复` 三种常见写法。
 */
private fun parseMarkdownQuote(line: String): MarkdownQuote? {
    if (!line.startsWith(">")) return null

    var cursor = 0
    var depth = 0
    while (cursor < line.length) {
        while (cursor < line.length && line[cursor].isWhitespace()) cursor++
        if (cursor >= line.length || line[cursor] != '>') break
        depth++
        cursor++
    }
    return MarkdownQuote(depth = depth.coerceAtLeast(1), content = line.substring(cursor).trim())
}

/** 使用类似 ChatGPT 的竖线层级呈现引用与子回复。 */
@Composable
private fun RenderMarkdownQuote(quote: MarkdownQuote) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .padding(start = ((quote.depth - 1) * 12).dp, top = 4.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        repeat(quote.depth.coerceAtMost(3)) {
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color(0x4DFFFFFF))
            )
        }
        Box(modifier = Modifier.weight(1f)) {
            RenderRichText(
                text = quote.content,
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
        }
    }
}

/** 渲染块级 LaTeX 公式；超宽公式可独立横向滚动。 */
@Composable
private fun RenderMathBlock(lines: List<String>) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x1A38BDF8))
            .claimHorizontalContentGesture()
            .padding(12.dp)
    ) {
        Row(
            modifier = Modifier.horizontalScroll(rememberScrollState())
        ) {
            LatexMath(
                formula = lines.joinToString("\n"),
                displayMode = true
            )
        }
    }
}

/** 渲染代码块 */
@Composable
private fun RenderCodeBlock(lines: List<String>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x33000000))
            .claimHorizontalContentGesture()
            .horizontalScroll(rememberScrollState())
            .padding(12.dp)
    ) {
        lines.forEach { line ->
            Text(
                text = line,
                style = MaterialTheme.typography.bodySmall,
                color = EmotionGreen,
                fontFamily = FontFamily.Monospace
            )
        }
    }
}

/** 渲染 Markdown 表格 */
@Composable
private fun RenderTable(lines: List<String>) {
    // 过滤分隔行(|---|---|)
    val dataRows = lines.filter { row ->
        !row.replace("|", "").replace("-", "").replace(" ", "").isEmpty()
    }
    if (dataRows.isEmpty()) return

    // 解析每行的单元格
    val rows = dataRows.map { row ->
        row.trim()
            .removePrefix("|")
            .removeSuffix("|")
            .split("|")
            .map { it.trim() }
    }

    val maxColumnCount = rows.maxOfOrNull { it.size } ?: return
    val tableWidth = maxOf(280, maxColumnCount * 136).dp

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x14000000))
            .claimHorizontalContentGesture()
    ) {
        Column(
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .width(tableWidth)
        ) {
            rows.forEachIndexed { index, cells ->
                Row(
                    modifier = Modifier
                        .width(tableWidth)
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    repeat(maxColumnCount) { columnIndex ->
                        Text(
                            text = cells.getOrNull(columnIndex).orEmpty(),
                            style = MaterialTheme.typography.labelSmall,
                            color = if (index == 0) Primary else TextSecondary,
                            fontWeight = if (index == 0) FontWeight.Bold else FontWeight.Normal,
                            modifier = Modifier.width(128.dp)
                        )
                    }
                }
                if (index < rows.size - 1) {
                    Box(
                        modifier = Modifier
                            .width(tableWidth)
                            .height(1.dp)
                            .background(Color(0x1AFFFFFF))
                    )
                }
            }
        }
    }
}
