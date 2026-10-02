package com.aveline.ai.mobile.presentation.study

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
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
import com.aveline.ai.mobile.presentation.components.LatexMath
import com.aveline.ai.mobile.presentation.components.MarkdownInlineText
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.components.claimHorizontalContentGesture
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import com.aveline.ai.mobile.utils.text.CodeHighlighter
import com.aveline.ai.mobile.utils.text.MarkdownBlock
import com.aveline.ai.mobile.utils.text.MarkdownBlockParser
import com.aveline.ai.mobile.utils.text.MarkdownInlineNode

/**
 * 知识笔记 Tab。
 *
 * 以文件夹树形式展示学习库（D:\projects\study）中的 .md 笔记：
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
    onCloseReader: () -> Unit,
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
            contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        ) {
            item {
                SectionCard(title = "知识笔记") {
                    if (noteTree.isEmpty()) {
                        Text(
                            text = "学习库暂无笔记",
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextTertiary,
                            modifier = Modifier.padding(vertical = 12.dp),
                        )
                    } else {
                        Text(
                            text = "共 ${totalCount} 篇笔记 · ${noteTree.size} 个科目，点击文件夹展开/折叠，点击文件阅读",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary,
                            modifier = Modifier.padding(bottom = 12.dp),
                        )
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            visibleNodes.forEach { (node, depth) ->
                                NoteTreeItem(
                                    node = node,
                                    depth = depth,
                                    isExpanded = expandedPaths.contains(node.path),
                                    onFolderClick = {
                                        expandedPaths = if (node.path in expandedPaths) {
                                            expandedPaths - node.path
                                        } else {
                                            expandedPaths + node.path
                                        }
                                    },
                                    onFileClick = { onOpenNote(node.path) },
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
                onClose = onCloseReader,
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
    depth: Int = 0,
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
    onFileClick: () -> Unit,
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
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = iconColor,
            modifier = Modifier.width(20.dp).height(20.dp),
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = node.name + countText,
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold),
                color = TextPrimary,
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
                        maxLines = 1,
                    )
                }
            }
        }
        if (node is NoteTreeNode.Folder) {
            Icon(
                imageVector = if (isExpanded) Icons.Default.ExpandLess else Icons.Default.ChevronRight,
                contentDescription = if (isExpanded) "折叠" else "展开",
                tint = TextTertiary,
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
    onClose: () -> Unit,
) {
    val content = uiState.currentNoteContent
    val isLoading = uiState.isLoading && content == null
    val error = uiState.error

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0F0F13))
            .statusBarsPadding(),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = TextPrimary,
                    )
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = content?.filename?.removeSuffix(".md") ?: "笔记",
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary,
                        maxLines = 1,
                    )
                    if (content?.path != null) {
                        Text(
                            text = content.path,
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary,
                            maxLines = 1,
                        )
                    }
                }
            }

            Box(modifier = Modifier.fillMaxSize()) {
                when {
                    isLoading -> {
                        CircularProgressIndicator(
                            modifier = Modifier.align(Alignment.Center),
                            color = Primary,
                        )
                    }

                    error != null && content == null -> {
                        Text(
                            text = error,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier
                                .align(Alignment.Center)
                                .padding(24.dp),
                        )
                    }

                    content != null -> {
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(horizontal = 16.dp),
                            contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
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
 * 聊天与知识笔记共用的 Markdown renderer。
 *
 * 全文先通过 [MarkdownBlockParser] 解析成块 AST，并用 `remember(text)` 缓存；标题、列表、引用、表格 cell
 * 都复用 [MarkdownInlineText]，因此粗体、斜体、删除线与行内 LaTeX 的行为一致。代码 fence 优先于数学块，
 * `$$...$$` 同时支持多行和单行形式。
 */
@Composable
fun NotesMarkdownRenderer(text: String) {
    val blocks = remember(text) { MarkdownBlockParser.parse(text) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        blocks.forEach { block ->
            when (block) {
                MarkdownBlock.Blank -> Spacer(modifier = Modifier.height(2.dp))
                MarkdownBlock.Divider -> Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(1.dp)
                        .background(Color(0x2AFFFFFF)),
                )

                is MarkdownBlock.Paragraph -> MarkdownInlineText(
                    nodes = block.content,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextPrimary,
                    modifier = Modifier.fillMaxWidth(),
                )

                is MarkdownBlock.Heading -> RenderHeading(block)
                is MarkdownBlock.Bullet -> Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = "•",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Primary,
                        modifier = Modifier.alignByBaseline(),
                    )
                    MarkdownInlineText(
                        nodes = block.content,
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary,
                        modifier = Modifier
                            .weight(1f)
                            .alignByBaseline(),
                    )
                }

                is MarkdownBlock.Quote -> RenderMarkdownQuote(block)
                is MarkdownBlock.Math -> RenderMathBlock(block.formula)
                is MarkdownBlock.Code -> RenderCodeBlock(block.code, block.language)
                is MarkdownBlock.Table -> RenderTable(block.rows)
            }
        }
    }
}

@Composable
private fun RenderHeading(block: MarkdownBlock.Heading) {
    val style = when (block.level) {
        1 -> MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
        2 -> MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
        3 -> MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold)
        else -> MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold)
    }
    val color = if (block.level == 3) Primary else TextPrimary

    if (block.level == 2) Spacer(modifier = Modifier.height(4.dp))
    MarkdownInlineText(
        nodes = block.content,
        style = style,
        color = color,
        modifier = Modifier.fillMaxWidth(),
    )
}

/** 使用类似 ChatGPT 的竖线层级呈现引用与子回复。 */
@Composable
private fun RenderMarkdownQuote(quote: MarkdownBlock.Quote) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .padding(start = ((quote.depth - 1) * 12).dp, top = 4.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        repeat(quote.depth.coerceAtMost(3)) {
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color(0x4DFFFFFF)),
            )
        }
        MarkdownInlineText(
            nodes = quote.content,
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
            modifier = Modifier.weight(1f),
        )
    }
}

/** 渲染块级 LaTeX 公式；超宽公式可独立横向滚动。 */
@Composable
private fun RenderMathBlock(formula: String) {
    if (formula.isBlank()) return
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x1A38BDF8))
            .claimHorizontalContentGesture()
            .padding(12.dp),
    ) {
        Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
            LatexMath(
                formula = formula,
                displayMode = true,
            )
        }
    }
}

/** 渲染代码块：头部显示语言标签，正文按语言做语法高亮。 */
@Composable
private fun RenderCodeBlock(code: String, languageTag: String) {
    val language = remember(code, languageTag) { CodeHighlighter.resolveLanguage(languageTag, code) }
    val highlighted = remember(code, language) { CodeHighlighter.highlightCode(code, language) }
    val languageLabel = CodeHighlighter.displayName(language)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x33000000))
            .claimHorizontalContentGesture(),
    ) {
        if (languageLabel.isNotEmpty()) {
            Text(
                text = languageLabel,
                style = MaterialTheme.typography.labelSmall,
                color = EmotionGreen.copy(alpha = 0.8f),
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(top = 8.dp, start = 12.dp),
            )
        }
        Text(
            text = highlighted,
            style = MaterialTheme.typography.bodySmall,
            color = EmotionGreen,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .padding(12.dp),
        )
    }
}

/** 渲染已解析的 GFM 表格；对齐分隔行已在 parser 阶段剔除。 */
@Composable
private fun RenderTable(rows: List<List<List<MarkdownInlineNode>>>) {
    if (rows.isEmpty()) return
    val maxColumnCount = rows.maxOfOrNull { it.size } ?: return
    val tableWidth = maxOf(280, maxColumnCount * 136).dp

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x14000000))
            .claimHorizontalContentGesture(),
    ) {
        Column(
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .width(tableWidth),
        ) {
            rows.forEachIndexed { index, cells ->
                Row(
                    modifier = Modifier
                        .width(tableWidth)
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    repeat(maxColumnCount) { columnIndex ->
                        MarkdownInlineText(
                            nodes = cells.getOrNull(columnIndex).orEmpty(),
                            style = MaterialTheme.typography.labelSmall.copy(
                                fontWeight = if (index == 0) FontWeight.Bold else FontWeight.Normal,
                            ),
                            color = if (index == 0) Primary else TextSecondary,
                            modifier = Modifier.width(128.dp),
                        )
                    }
                }
                if (index < rows.size - 1) {
                    Box(
                        modifier = Modifier
                            .width(tableWidth)
                            .height(1.dp)
                            .background(Color(0x1AFFFFFF)),
                    )
                }
            }
        }
    }
}