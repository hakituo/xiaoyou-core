"""验证 ChatScreen 解耦结果与重复头像实现的收敛。

背景：ChatScreen.kt 曾膨胀到 1250 行，把顶栏、消息列表、伴侣面板、底部输入条、
手势处理、编辑对话框等全部塞在一个文件里；同时"本地头像 > 网络 URL > 首字母兜底"
这套逻辑在 ChatScreen / ConversationListScreen / PersonaEditSheet 各写了一份。

本脚本校验解耦后的结构约束，防止再次膨胀或把重复实现写回去：
1. ChatScreen.kt 行数不超过阈值，且只做组装（不再内联大块 UI 私有组件）
2. 拆分出的子组件文件都在 chat 包下
3. 首字母头像兜底实现全局只剩 PersonaAvatar.kt 一处，三处调用方都改用它
4. 死参数（@Suppress("UNUSED_PARAMETER") 的 connectionState）已移除
5. ChatScreen.kt 不再使用内联全限定名（如 androidx.compose.material3.MaterialTheme）
6. 本次涉及的文件没有未使用的 import

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/android_frontend/verify_chat_screen_decomposition.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
CHAT_DIR = APP_MAIN / "presentation/chat"
CHAT_SCREEN = CHAT_DIR / "ChatScreen.kt"
PERSONA_AVATAR = APP_MAIN / "presentation/components/PersonaAvatar.kt"
CONVERSATION_LIST = APP_MAIN / "presentation/conversations/ConversationListScreen.kt"
PERSONA_EDIT_SHEET = APP_MAIN / "presentation/conversations/PersonaEditSheet.kt"

# 解耦后允许的最大行数（拆分前 1251 行）
MAX_CHAT_SCREEN_LINES = 400

# 期望从 ChatScreen 拆出去的子组件文件
EXPECTED_CHAT_FILES = (
    "ChatTopBar.kt",
    "ChatMessageList.kt",
    "ChatCompanionPanel.kt",
    "ChatCompanionPanelGesture.kt",
    "ChatInputBars.kt",
    "ChatEditMessageDialog.kt",
    "ChatMediaPickers.kt",
    "ChatPersonaTitle.kt",
    "ChatPeerChatArea.kt",
)

# 曾内联在 ChatScreen 里的私有组件/函数，解耦后不应再出现
MOVED_OUT_SYMBOLS = (
    "private fun ChatTopBar",
    "private fun ChatPersonaAvatar",
    "private fun AvatarTextFallback",
    "private fun ChatBottomBar",
    "private fun PendingImageBar",
    "private fun PendingVideoBar",
    "private fun ImageAnalyzingBar",
    "private fun UploadProgressIndicator",
    "private fun EmptyChatState",
    "private fun CenteredNarration",
    "private fun extractActivePersonaInfo",
)

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")

# Kotlin 属性委托（`val x by y`）会隐式调用 getValue/setValue，正文里搜不到名字，不算未使用
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)

# 正文出现这些用法就必须有对应 import。
# 拆分 ChatScreen 时漏过 `@Composable`（ChatPeerChatArea.kt）与 `lazy.items`，
# 都属于"少一行 import 就编译失败"的错误，这里统一做成回归检查。
REQUIRED_IMPORTS = (
    ("@Composable", "androidx.compose.runtime.Composable"),
    ("AnimatedVisibility(", "androidx.compose.animation.AnimatedVisibility"),
    ("AsyncImage(", "coil.compose.AsyncImage"),
    ("LazyColumn(", "androidx.compose.foundation.lazy.LazyColumn"),
    ("AlertDialog(", "androidx.compose.material3.AlertDialog"),
    ("Scaffold(", "androidx.compose.material3.Scaffold"),
    ("BackHandler(", "androidx.activity.compose.BackHandler"),
    ("pointerInput(", "androidx.compose.ui.input.pointer.pointerInput"),
    ("TextFieldValue(", "androidx.compose.ui.text.input.TextFieldValue"),
    (
        "rememberLauncherForActivityResult(",
        "androidx.activity.compose.rememberLauncherForActivityResult",
    ),
    ("PullableDismissPanel(", "com.aveline.ai.mobile.presentation.components.PullableDismissPanel"),
    ("PersonaAvatar(", "com.aveline.ai.mobile.presentation.components.PersonaAvatar"),
    ("RowScope.", "androidx.compose.foundation.layout.RowScope"),
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    """返回文件里未被引用的 import 行（粗粒度：按 import 末段标识符整词匹配正文）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    body_lines = [
        line
        for line in lines
        if not line.startswith("import ") and not line.startswith("package ")
    ]
    body = "\n".join(body_lines)
    unused: list[str] = []
    for line in lines:
        if not line.startswith("import "):
            continue
        matched = IMPORT_RE.match(line)
        if not matched:
            continue
        if line.strip() in DELEGATE_IMPORTS:
            continue
        fq_name, alias = matched.group(1), matched.group(2)
        if fq_name.endswith("*"):
            continue
        name = alias or fq_name.rsplit(".", 1)[-1]
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            unused.append(line)
    return unused


def has_import(source: str, fq_name: str) -> bool:
    return f"import {fq_name}" in source


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("ChatScreen 解耦验证")
    print("=" * 70)

    chat_screen = CHAT_SCREEN.read_text(encoding="utf-8")
    chat_lines = len(chat_screen.splitlines())
    print(f"ChatScreen.kt 行数：{chat_lines}")

    # 1. 体积与职责
    results.append(
        _check(
            chat_lines <= MAX_CHAT_SCREEN_LINES,
            f"ChatScreen.kt {chat_lines} 行 <= {MAX_CHAT_SCREEN_LINES} 行",
        )
    )
    remaining = [symbol for symbol in MOVED_OUT_SYMBOLS if symbol in chat_screen]
    results.append(
        _check(not remaining, f"ChatScreen.kt 已不含内联子组件 {remaining or ''}")
    )

    # 2. 拆分出的文件都在
    missing_files = [name for name in EXPECTED_CHAT_FILES if not (CHAT_DIR / name).exists()]
    results.append(
        _check(not missing_files, f"拆分出的子组件文件齐全，缺失：{missing_files or '无'}")
    )

    # 3. 首字母头像兜底只剩一处实现
    fallback_sources = [
        path
        for path in APP_MAIN.rglob("*.kt")
        if "firstOrNull()?.toString()" in path.read_text(encoding="utf-8")
    ]
    results.append(
        _check(
            fallback_sources == [PERSONA_AVATAR],
            "首字母头像兜底实现只剩 PersonaAvatar.kt，实际："
            f"{[p.name for p in fallback_sources]}",
        )
    )
    for path in (CHAT_DIR / "ChatTopBar.kt", CONVERSATION_LIST, PERSONA_EDIT_SHEET):
        results.append(
            _check(
                "PersonaAvatar(" in path.read_text(encoding="utf-8"),
                f"{path.name} 复用公共 PersonaAvatar 组件",
            )
        )

    # 4. 死参数已移除
    results.append(
        _check(
            "UNUSED_PARAMETER" not in chat_screen,
            "ChatScreen.kt 不再有 @Suppress(\"UNUSED_PARAMETER\") 死参数",
        )
    )

    # 5. 不再内联全限定名
    inline_fqns = [
        line.strip()
        for line in chat_screen.splitlines()
        if "androidx.compose." in line and not line.strip().startswith("import ")
    ]
    results.append(
        _check(not inline_fqns, f"ChatScreen.kt 无内联全限定名，实际：{inline_fqns[:3]}")
    )

    # 6. 未使用 import
    checked_files = [CHAT_SCREEN, PERSONA_AVATAR, CONVERSATION_LIST, PERSONA_EDIT_SHEET]
    checked_files += [CHAT_DIR / name for name in EXPECTED_CHAT_FILES]
    unused_report: list[str] = []
    for path in checked_files:
        if not path.exists():
            continue
        for unused in find_unused_imports(path):
            unused_report.append(f"{path.name}: {unused}")
    results.append(
        _check(
            not unused_report,
            "涉及文件无未使用 import"
            + ("" if not unused_report else "，实际：\n    " + "\n    ".join(unused_report)),
        )
    )

    # 7. LazyColumn 的 items(...) 必须显式导入（Compose 里漏这个 import 直接编译失败）
    missing_items_import = [
        path.name
        for path in checked_files
        if path.exists() and "items(" in path.read_text(encoding="utf-8")
        and not has_import(path.read_text(encoding="utf-8"), "androidx.compose.foundation.lazy.items")
    ]
    results.append(
        _check(
            not missing_items_import,
            f"用到 items(...) 的文件都已导入 lazy.items，缺失：{missing_items_import or '无'}",
        )
    )

    # 8. 必需 import 齐全（少一行 import 就编译失败）
    missing_imports: list[str] = []
    for path in checked_files:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for symbol, fq_name in REQUIRED_IMPORTS:
            if symbol not in source:
                continue
            # 本文件自己就是该符号的定义处，不需要 import 自己
            if f"fun {symbol.rstrip('(').rstrip('.')}(" in source:
                continue
            if not has_import(source, fq_name):
                missing_imports.append(f"{path.name}: 用到 {symbol} 但缺少 import {fq_name}")
    results.append(
        _check(
            not missing_imports,
            "必需 import 齐全"
            + ("" if not missing_imports else "，实际：\n    " + "\n    ".join(missing_imports)),
        )
    )

    print("\n" + "-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：ChatScreen 已解耦为组装层，头像实现已收敛。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
