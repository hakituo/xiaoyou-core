"""验证会话列表移除常驻刷新按钮后仍能自动加载。

背景：消息页右上角曾常驻一个手动刷新按钮（ModuleHeader 里的 Icons.Default.Refresh +
ModuleHeaderActionContainer）。但会话列表本来就是自动的——ConversationListViewModel.init
启动时拉一次，且 watch persona_local_meta 变化（改昵称/改头像）后自动重渲染，
常驻按钮既多余又占着标题栏位置。删除按钮时一并移除了 ConversationListScreen 的
onRefresh 参数。

本脚本防止两类回归：
1. 按钮被重新加回来；
2. 按钮删了，但自动加载链路（init -> refresh）也被误删，列表变成空白。

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/android_frontend/verify_conversation_list_autoload.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRESENTATION = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/presentation"
)
CONVERSATION_SCREEN = PRESENTATION / "conversations/ConversationListScreen.kt"
CONVERSATION_VIEW_MODEL = PRESENTATION / "conversations/ConversationListViewModel.kt"
NAV_GRAPH = PRESENTATION / "navigation/NavGraph.kt"

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
DELEGATE_IMPORTS = (
    "import androidx.compose.runtime.getValue",
    "import androidx.compose.runtime.setValue",
)


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def find_unused_imports(path: Path) -> list[str]:
    """返回文件里未被引用的 import 行（按 import 末段标识符整词匹配正文）。"""
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
    print("会话列表自动加载验证（常驻刷新按钮已移除）")
    print("=" * 70)

    screen = CONVERSATION_SCREEN.read_text(encoding="utf-8")
    view_model = CONVERSATION_VIEW_MODEL.read_text(encoding="utf-8")
    nav_graph = NAV_GRAPH.read_text(encoding="utf-8")

    # 1. 常驻刷新按钮及其调用链已移除
    results.append(
        _check("Icons.Default.Refresh" not in screen, "ConversationListScreen 不再有常驻刷新图标")
    )
    results.append(
        _check(
            "ModuleHeaderActionContainer" not in screen,
            "ConversationListScreen 的 ModuleHeader 不再挂 actions 容器",
        )
    )
    results.append(
        _check("onRefresh" not in screen, "ConversationListScreen 已移除常驻 onRefresh 参数")
    )

    # 1b. 但必须保留"按需重试"入口：常驻按钮删掉后，首次加载失败（启动瞬间后端未就绪）
    # 若没有任何重试路径，错误条一关就永久卡在空列表。
    results.append(
        _check("onReload" in screen, "空态保留 onReload 按需重试入口")
    )
    results.append(
        _check(
            "TextButton(onClick = onReload)" in screen,
            "空态的『重新加载』按钮已绑定 onReload",
        )
    )
    results.append(
        _check(
            "加载失败：$loadError" in screen,
            "空态会把加载失败原因显示出来（便于定位是接口失败还是真的没有 persona）",
        )
    )

    # 2. NavGraph 不再向会话列表传 onRefresh（其它页面仍有 onRefresh，只在调用块内判断）
    call_start = nav_graph.find("ConversationListScreen(")
    call_block = nav_graph[call_start : call_start + 1200] if call_start >= 0 else ""
    results.append(
        _check(
            call_start >= 0 and "onRefresh" not in call_block.split("onOpenChat")[0],
            "NavGraph 调用 ConversationListScreen 时不再传 onRefresh",
        )
    )

    # 3. 自动加载链路仍在：init 里调用 refresh()，且 refresh() 有实现
    init_at = view_model.find("init {")
    init_block = view_model[init_at : init_at + 400] if init_at >= 0 else ""
    results.append(_check(init_at >= 0, "ConversationListViewModel 仍有 init 块"))
    results.append(
        _check("refresh()" in init_block, "ConversationListViewModel.init 仍会自动调用 refresh()")
    )
    results.append(
        _check("fun refresh()" in view_model, "ConversationListViewModel.refresh() 实现保留")
    )
    results.append(
        _check(
            "observeAll()" in init_block,
            "本地 meta（昵称/头像）变化仍会自动重渲染列表",
        )
    )

    # 3b. 副链路失败不能拖垮整个列表：预览重建 / active persona 都必须降级而非让 refresh 整体失败
    results.append(
        _check(
            "重建会话预览失败（不阻断列表）" in view_model,
            "会话预览重建失败时降级，不把整张列表变空",
        )
    )
    results.append(
        _check(
            "获取 active persona 失败（列表仍照常展示）" in view_model,
            "active persona 接口失败时降级，不把整张列表变空",
        )
    )

    # 3c. NavGraph 需要把 onReload 接到 viewModel.refresh
    results.append(
        _check("onReload = viewModel::refresh" in nav_graph, "NavGraph 把 onReload 接到 refresh()")
    )

    # 4. 移除按钮后没有留下未使用 import
    unused = find_unused_imports(CONVERSATION_SCREEN)
    results.append(
        _check(
            not unused,
            "ConversationListScreen 无未使用 import"
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
    print("全部通过：常驻刷新按钮已移除，会话列表仍自动加载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
