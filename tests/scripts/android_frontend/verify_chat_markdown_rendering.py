"""验证 Android 聊天主页的 ChatGPT 式 Markdown 渲染接线。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MESSAGE_BUBBLE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/components/MessageBubble.kt"
)
NOTES_RENDERER = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/study/StudyNotesTab.kt"
)
LATEX_RENDERER = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/components/LatexMath.kt"
)
CHAT_SCREEN = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/chat/ChatScreen.kt"
)
PULLABLE_PANEL = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/components/PullableDismissPanel.kt"
)
HORIZONTAL_GESTURE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/components/HorizontalContentGesture.kt"
)
APP_BUILD = ROOT / "clients/frontend/aveline-android/android/app/build.gradle.kts"
LOCAL_ANDROID_MATH = ROOT / (
    "clients/frontend/aveline-android/android/app/libs/AndroidMath-v1.1.0.aar"
)


def require(source: str, fragment: str, description: str) -> None:
    """断言关键实现片段存在，并输出清晰的失败原因。"""
    if fragment not in source:
        raise AssertionError(f"缺少{description}: {fragment}")


def main() -> None:
    """检查聊天接线、Markdown 块能力和子回复引用样式。"""
    bubble = MESSAGE_BUBBLE.read_text(encoding="utf-8")
    renderer = NOTES_RENDERER.read_text(encoding="utf-8")
    latex = LATEX_RENDERER.read_text(encoding="utf-8")
    chat_screen = CHAT_SCREEN.read_text(encoding="utf-8")
    pullable_panel = PULLABLE_PANEL.read_text(encoding="utf-8")
    horizontal_gesture = HORIZONTAL_GESTURE.read_text(encoding="utf-8")
    app_build = APP_BUILD.read_text(encoding="utf-8")

    require(bubble, "NotesMarkdownRenderer(text = displayText)", "AI Markdown 渲染")
    require(bubble, "MessageType.AI -> Color.Transparent", "AI 无气泡正文样式")
    require(bubble, "else Modifier.fillMaxWidth()", "AI 正文完整宽度")

    for fragment, description in (
        ('trimmed.startsWith("```")', "围栏代码块"),
        ('trimmed.startsWith("|")', "Markdown 表格"),
        ("parseMarkdownQuote(trimmed)", "引用解析"),
        ("repeat(quote.depth.coerceAtMost(3))", "多层子回复竖线"),
        ('trimmed.startsWith("# ")', "Markdown 标题"),
        ('trimmed.startsWith("- ")', "Markdown 列表"),
    ):
        require(renderer, fragment, description)

    require(latex, "MTMathView(context)", "原生 LaTeX View")
    require(latex, "KMTMathViewModeDisplay", "块级 LaTeX 排版模式")
    require(renderer, 'formula = lines.joinToString("\\n")', "块级公式接线")
    require(renderer, ".horizontalScroll(rememberScrollState())", "宽表格和代码块横向滚动")
    if renderer.count(".claimHorizontalContentGesture()") < 3:
        raise AssertionError("表格、代码块、宽公式未完整声明横向手势所有权")
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

    print("PASS: Android 聊天主页已支持 Markdown、原生 LaTeX、横向表格及手势仲裁。")


if __name__ == "__main__":
    main()
