"""验证 Android 聊天主页的 Markdown / LaTeX 渲染接线与关键回归保护。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID_JAVA = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)
ANDROID_TEST = ROOT / (
    "clients/frontend/aveline-android/android/app/src/test/java/com/aveline/ai/mobile"
)
MESSAGE_BUBBLE = ANDROID_JAVA / "presentation/components/MessageBubble.kt"
NOTES_RENDERER = ANDROID_JAVA / "presentation/study/StudyNotesTab.kt"
DIARY_RENDERER = ANDROID_JAVA / "presentation/study/StudyDiaryTab.kt"
INLINE_RENDERER = ANDROID_JAVA / "presentation/components/MarkdownInlineText.kt"
INLINE_PARSER = ANDROID_JAVA / "utils/text/MarkdownInlineParser.kt"
BLOCK_PARSER = ANDROID_JAVA / "utils/text/MarkdownBlockParser.kt"
TEXT_SEGMENTER = ANDROID_JAVA / "utils/text/TextSegmenter.kt"
LATEX_RENDERER = ANDROID_JAVA / "presentation/components/LatexMath.kt"
CHAT_SCREEN = ANDROID_JAVA / "presentation/chat/ChatScreen.kt"
PULLABLE_PANEL = ANDROID_JAVA / "presentation/components/PullableDismissPanel.kt"
HORIZONTAL_GESTURE = ANDROID_JAVA / "presentation/components/HorizontalContentGesture.kt"
APP_BUILD = ROOT / "clients/frontend/aveline-android/android/app/build.gradle.kts"
LOCAL_ANDROID_MATH = ROOT / (
    "clients/frontend/aveline-android/android/app/libs/AndroidMath-v1.1.0.aar"
)
PARSER_TESTS = (
    ANDROID_TEST / "utils/text/MarkdownInlineParserTest.kt",
    ANDROID_TEST / "utils/text/MarkdownBlockParserTest.kt",
    ANDROID_TEST / "utils/text/MarkdownLatexSegmenterTest.kt",
)


def require(source: str, fragment: str, description: str) -> None:
    """断言关键实现片段存在，并输出清晰的失败原因。"""
    if fragment not in source:
        raise AssertionError(f"缺少{description}: {fragment}")


def main() -> None:
    """检查聊天接线、AST 解析、LaTeX 守卫、行内布局和横向手势仲裁。"""
    bubble = MESSAGE_BUBBLE.read_text(encoding="utf-8")
    renderer = NOTES_RENDERER.read_text(encoding="utf-8")
    diary = DIARY_RENDERER.read_text(encoding="utf-8")
    inline_renderer = INLINE_RENDERER.read_text(encoding="utf-8")
    inline_parser = INLINE_PARSER.read_text(encoding="utf-8")
    block_parser = BLOCK_PARSER.read_text(encoding="utf-8")
    text_segmenter = TEXT_SEGMENTER.read_text(encoding="utf-8")
    latex = LATEX_RENDERER.read_text(encoding="utf-8")
    chat_screen = CHAT_SCREEN.read_text(encoding="utf-8")
    pullable_panel = PULLABLE_PANEL.read_text(encoding="utf-8")
    horizontal_gesture = HORIZONTAL_GESTURE.read_text(encoding="utf-8")
    app_build = APP_BUILD.read_text(encoding="utf-8")

    require(bubble, "NotesMarkdownRenderer(text = segment)", "AI Markdown 渲染")
    require(bubble, "MessageType.AI -> Color.Transparent", "AI 无气泡正文样式")
    require(bubble, "else Modifier.fillMaxWidth()", "AI 正文完整宽度")

    require(renderer, "remember(text) { MarkdownBlockParser.parse(text) }", "Markdown AST 缓存")
    require(renderer, "is MarkdownBlock.Math -> RenderMathBlock", "块级公式 AST 渲染")
    require(renderer, "is MarkdownBlock.Table -> RenderTable", "表格 AST 渲染")
    require(renderer, "MarkdownInlineText(", "统一行内富文本渲染")
    require(renderer, ".horizontalScroll(rememberScrollState())", "宽表格和代码块横向滚动")
    if renderer.count(".claimHorizontalContentGesture()") < 3:
        raise AssertionError("表格、代码块、宽公式未完整声明横向手势所有权")

    require(diary, "NotesMarkdownRenderer(text = text)", "日记复用统一 Markdown renderer")
    if "fun RenderRichText(" in diary or "parseRichTextSegments" in diary:
        raise AssertionError("日记仍保留旧 Row 行内 Markdown/LaTeX 渲染器")

    require(block_parser, "代码块状态优先级最高", "代码块优先状态机")
    require(block_parser, "parseSingleLineMath", "单行 $$...$$ 公式")
    require(block_parser, "TABLE_SEPARATOR_CELL", "GFM 对齐分隔行过滤")
    require(block_parser, "MarkdownInlineParser.parse", "标题/列表/表格统一行内解析")

    require(inline_renderer, "InlineTextContent", "Compose 行内公式占位")
    require(inline_renderer, "appendInlineContent", "单一 Text 内嵌 LaTeX")
    require(inline_renderer, "LatexMath(", "行内原生 LaTeX")
    if "Row(modifier = Modifier.fillMaxWidth())" in inline_renderer:
        raise AssertionError("行内富文本又退回 Row 多 child 布局")

    require(inline_parser, "ESCAPABLE_CHARS", "美元符号转义")
    require(inline_parser, "looksLikeInlineMath", "公式有效性判定")
    require(inline_parser, "CJK_PUNCTUATION", "货币/自然语言误配保护")
    require(inline_parser, "val italic: Boolean = false", "行内节点的斜体样式位")
    require(inline_parser, "hasClosingAsterisk", "单星号斜体的 CommonMark flank 判定")
    require(inline_parser, "findClosingDoubleDollar", "列表项/标题内的块级公式兜底")
    if "buffer.append(\"$$\")" not in inline_parser:
        raise AssertionError("半截 $$ 公式缺少退化为原样文本的兜底")

    require(inline_renderer, "fontStyle = if (node.italic) FontStyle.Italic else null", "斜体渲染")

    require(text_segmenter, "LATEX_MARKER_REGEX", "块级 LaTeX 展示守卫")
    require(text_segmenter, "groupByStructure", "按 Markdown 结构分组断句")
    require(text_segmenter, "DisplayGroup(buf.joinToString(\"\\n\"), atomic = true)", "跨行结构整组保留")

    for test_path in PARSER_TESTS:
        if not test_path.is_file():
            raise AssertionError(f"缺少 Markdown/LaTeX 回归测试: {test_path}")

    require(latex, "MTMathView(context)", "原生 LaTeX View")
    require(latex, "KMTMathViewModeDisplay", "块级 LaTeX 排版模式")
    require(horizontal_gesture, "gestureState.isActive = true", "富文本手势开始标记")
    require(horizontal_gesture, "gestureState.isActive = false", "富文本手势结束标记")
    require(chat_screen, "val horizontalContentGestureState = remember", "显式手势仲裁状态")
    require(
        chat_screen,
        "LocalHorizontalContentGestureState provides horizontalContentGestureState",
        "聊天消息手势状态下发",
    )
    require(chat_screen, "if (horizontalContentGestureState.isActive)", "富文本横滑识别")
    require(chat_screen, "!childConsumedHorizontalDrag", "伴侣详情手势冲突保护")
    require(chat_screen, "if (startX <= screenWidthPx * 0.12f)", "左边缘侧边栏保护")
    if "startX > screenWidthPx / 2" in chat_screen:
        raise AssertionError("伴侣详情左滑仍被限制为只能从右半屏起手")
    if "change.isConsumed" in chat_screen or "event.changes.any { it.isConsumed }" in chat_screen:
        raise AssertionError("普通组件的 consumed 状态仍会错误屏蔽伴侣详情左滑")
    open_block = chat_screen.split("val openCompanionPanel: () -> Unit = {", 1)[1].split(
        "val closeCompanionPanel", 1
    )[0]
    require(open_block, "showCompanionPanel = true", "面板先加入组合树")
    if "companionPanelState.show()" in open_block:
        raise AssertionError("打开回调仍在面板组合前等待 show()")
    require(pullable_panel, "LaunchedEffect(state, panelWidthPx)", "面板重进组合时复位")
    require(pullable_panel, "state.show()", "面板可见状态恢复")
    require(pullable_panel, "hasBeenShown.value &&", "首次重开时的关闭回调竞态保护")
    require(app_build, 'implementation(files("libs/AndroidMath-v1.1.0.aar"))', "本地 LaTeX AAR")
    if not LOCAL_ANDROID_MATH.is_file() or LOCAL_ANDROID_MATH.stat().st_size < 4_000_000:
        raise AssertionError("本地 AndroidMath AAR 缺失或下载不完整")

    print("PASS: Android 聊天 Markdown/LaTeX 已使用 AST + 单 Text 行内公式，并保护块级公式不被断句。")


if __name__ == "__main__":
    main()
