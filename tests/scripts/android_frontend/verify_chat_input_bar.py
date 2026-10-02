"""验证聊天页底部输入栏只保留麦克风与"+"，且键盘弹出时像微信一样把页面顶起来。

需求：
1. 聊天页底部只应有「麦克风」与「+」（输入框有内容时变「发送」），录像按钮下线；
2. 呼出键盘时输入栏上移到键盘之上、消息列表相应缩短并贴住最新消息（微信/QQ 行为）。

对应实现：
- InputArea 删除录像按钮与 onVideoPick，键盘处理改为
  `windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))`
  （原 imePadding + navigationBarsPadding 叠加会在三键导航下多留一条导航栏高度的空隙）；
- ChatBottomBar / ChatMediaPickers / ChatScreen 收敛为只有相册入口；
- ChatScreen 在整页 imePadding() **之前**读取键盘可见性，键盘弹出时滚动到最新消息
  （子层读会被外层 imePadding 消费成 false，滚动会静默失效）。

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/android_frontend/verify_chat_input_bar.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_MAIN = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
INPUT_AREA = APP_MAIN / "presentation/components/InputArea.kt"
CHAT_DIR = APP_MAIN / "presentation/chat"
CHAT_INPUT_BARS = CHAT_DIR / "ChatInputBars.kt"
CHAT_SCREEN = CHAT_DIR / "ChatScreen.kt"
CHAT_MEDIA_PICKERS = CHAT_DIR / "ChatMediaPickers.kt"
CHAT_MESSAGE_LIST = CHAT_DIR / "ChatMessageList.kt"

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
# Kotlin 属性委托（`val x by y`）会隐式调用 getValue/setValue，正文里搜不到名字，不算未使用
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    body = "\n".join(
        line
        for line in lines
        if not line.startswith("import ") and not line.startswith("package ")
    )
    unused: list[str] = []
    for line in lines:
        if not line.startswith("import ") or line.strip() in DELEGATE_IMPORTS:
            continue
        matched = IMPORT_RE.match(line)
        if not matched:
            continue
        fq_name, alias = matched.group(1), matched.group(2)
        if fq_name.endswith("*"):
            continue
        name = alias or fq_name.rsplit(".", 1)[-1]
        if not re.search(r"\b" + re.escape(name) + r"\b", body):
            unused.append(line)
    return unused


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("聊天页底部输入栏与键盘行为验证")
    print("=" * 70)

    input_area = INPUT_AREA.read_text(encoding="utf-8")
    input_bars = CHAT_INPUT_BARS.read_text(encoding="utf-8")
    chat_screen = CHAT_SCREEN.read_text(encoding="utf-8")
    media_pickers = CHAT_MEDIA_PICKERS.read_text(encoding="utf-8")
    message_list = CHAT_MESSAGE_LIST.read_text(encoding="utf-8")

    # 1. 录像入口彻底下线
    results.append(
        _check("onVideoPick" not in input_area, "InputArea 不再有 onVideoPick 参数")
    )
    results.append(
        _check("Icons.Filled.Videocam" not in input_area, "InputArea 不再渲染录像按钮")
    )
    results.append(
        _check("onVideoPick" not in input_bars, "ChatBottomBar 不再有 onVideoPick 参数")
    )
    results.append(
        _check("pickVideo" not in media_pickers, "ChatMediaPickers 不再提供 pickVideo")
    )
    results.append(
        _check("PendingVideoBar" not in chat_screen, "ChatScreen 不再渲染待发送视频条")
    )
    results.append(
        _check("fun PendingVideoBar" not in input_bars, "PendingVideoBar 组件已删除")
    )

    # 2. 底部仍保留麦克风与"+"（或发送）
    results.append(
        _check("Icons.Filled.Mic" in input_area, "InputArea 保留麦克风按钮")
    )
    results.append(
        _check("Icons.Filled.Add" in input_area, "InputArea 保留\"+\"按钮（无内容时）")
    )
    results.append(
        _check(
            "onAttach = { mediaPickers.pickImage() }" in chat_screen,
            "ChatScreen 把\"+\"接到打开相册",
        )
    )

    # 3. 键盘 insets：必须用 union，避免 ime 与导航栏叠加
    results.append(
        _check(
            "windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))" in input_area,
            "InputArea 用 ime ∪ navigationBars 处理键盘（不再叠加两层 padding）",
        )
    )
    results.append(
        _check(
            "import androidx.compose.foundation.layout.imePadding" not in input_area
            and "import androidx.compose.foundation.layout.navigationBarsPadding" not in input_area,
            "InputArea 不再导入旧的 imePadding/navigationBarsPadding（已换成 union 写法）",
        )
    )

    # 3b. 整页必须在键盘上方重新布局（只给输入栏加 padding 不够：列表不会缩短，最后几条被遮挡）
    results.append(
        _check(
            "    Box(\n        modifier = Modifier\n            .fillMaxSize()\n            .imePadding()\n    ) {"
            in chat_screen,
            "ChatScreen 整页 imePadding（微信式把聊天页顶起来，列表随之缩短）",
        )
    )

    # 4. 键盘弹出时贴住最新消息
    # 判断必须在整页 imePadding() 之前读取：imePadding 会消费 ime insets，
    # 子树里的 WindowInsets.isImeVisible 恒为 false，滚动逻辑会静默失效。
    results.append(
        _check(
            "WindowInsets.isImeVisible" in chat_screen,
            "ChatScreen 在 imePadding() 之前读取键盘可见性",
        )
    )
    results.append(
        _check(
            "WindowInsets.isImeVisible" not in message_list,
            "ChatMessageList 内不再读 ime（会被外层 imePadding 消费成 false）",
        )
    )
    results.append(
        _check(
            "isImeVisible && uiState.messages.isNotEmpty()" in chat_screen,
            "键盘弹出时滚动到最新消息（微信/QQ 行为）",
        )
    )

    # 5. 没有留下未使用 import
    unused: list[str] = []
    for path in (INPUT_AREA, CHAT_INPUT_BARS, CHAT_SCREEN, CHAT_MEDIA_PICKERS, CHAT_MESSAGE_LIST):
        for line in find_unused_imports(path):
            unused.append(f"{path.name}: {line}")
    results.append(
        _check(
            not unused,
            "相关文件无未使用 import"
            + ("" if not unused else "，实际：\n    " + "\n    ".join(unused)),
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
    print("全部通过：底部只剩麦克风与\"+\"，键盘弹出时输入栏上移并贴住最新消息。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
