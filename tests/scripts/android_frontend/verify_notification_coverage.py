"""验证 Android 端的通知覆盖：Active Care 与"角色后台回我消息"。

背景（修复前的真实断链）：
- 后端 Active Care 以 `{"type":"proactive_message","subtype":"active_care",...}` 广播
  （core/services/aveline/proactive_messaging.py），但 Android 的 parseMessage 没有这个分支，
  整条消息落到 WebSocketMessage.Unknown 被静默丢弃 —— 既不通知也不上屏，所以用户完全收不到提醒。
- AI 的普通回复（TextMessage / ResponseChunk + ResponseDone）只上屏落库，从不发通知；
  App 退到后台时用户没有任何感知。

本脚本守护修复后的覆盖范围：
1. ProactiveMessage 类型存在且被 parseMessage 正确映射（含 conversation_id / message_id）；
2. 协调器处理 ProactiveMessage 并提醒（双角色剧本除外、按 message_id 去重）；
3. AI 回复在 App 处于后台时提醒（前台已上屏，不再重复打扰）；
4. notification 分支解析后端的 target / session_id，深链不再只能靠启发式；
5. 相关文件没有未使用 import。

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/android_frontend/verify_notification_coverage.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_MAIN = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)
WS_MESSAGE = APP_MAIN / "data/remote/api/WebSocketMessage.kt"
WS_MANAGER = APP_MAIN / "data/remote/api/WebSocketManager.kt"
WS_COORDINATOR = APP_MAIN / "services/foreground/WebSocketCommandCoordinator.kt"
# 深链与角色 id 解析在 2026-09-24 拆到 NotificationDeepLink.kt，检查点跟着搬家
WS_DEEP_LINK = APP_MAIN / "services/foreground/NotificationDeepLink.kt"

IMPORT_RE = re.compile(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$")
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
    print("通知覆盖验证（Active Care / 后台回复）")
    print("=" * 70)

    ws_message = WS_MESSAGE.read_text(encoding="utf-8")
    ws_manager = WS_MANAGER.read_text(encoding="utf-8")
    ws_coordinator = WS_COORDINATOR.read_text(encoding="utf-8")
    ws_deep_link = WS_DEEP_LINK.read_text(encoding="utf-8")

    # 1. 消息类型 + 解析
    results.append(
        _check("data class ProactiveMessage(" in ws_message, "WebSocketMessage 定义 ProactiveMessage")
    )
    results.append(
        _check(
            re.search(
                r"data class ProactiveMessage\([^)]*\)\s*:\s*WebSocketMessage\(\)",
                ws_message,
            )
            is not None,
            "ProactiveMessage 是 WebSocketMessage 的子类型（when 分支才能匹配）",
        )
    )
    results.append(
        _check(
            '"proactive_message" -> WebSocketMessage.ProactiveMessage(' in ws_manager,
            "parseMessage 把 type=proactive_message 映射为 ProactiveMessage（原来落 Unknown 被丢弃）",
        )
    )
    for field in ("content", "conversation_id", "message_id", "is_peer_script"):
        results.append(
            _check(
                f'json.optString("{field}")' in ws_manager or f'json.optBoolean("{field}"' in ws_manager,
                f"parseMessage 解析 proactive_message 的 {field} 字段",
            )
        )

    # 2. 协调器处理主动消息
    results.append(
        _check(
            "is WebSocketMessage.ProactiveMessage -> handleProactiveMessage(message)" in ws_coordinator,
            "协调器分发 ProactiveMessage 到 handleProactiveMessage",
        )
    )
    results.append(
        _check("private fun handleProactiveMessage(" in ws_coordinator, "handleProactiveMessage 已实现")
    )
    results.append(
        _check(
            "if (message.isPeerScript) return" in ws_coordinator,
            "双角色剧本不按\"角色找我\"提醒",
        )
    )
    results.append(
        _check(
            'replayGuard.isReplay("proactive:$messageId")' in ws_coordinator,
            "主动消息按 message_id 去重（重连重放不重复提醒）",
        )
    )

    # 3. 后台回复提醒
    results.append(
        _check(
            "is WebSocketMessage.ResponseChunk -> streamingBuffer.append(message.content)" in ws_coordinator,
            "流式回复按 chunk 累积正文（ResponseDone 本身不带内容）",
        )
    )
    results.append(
        _check(
            "is WebSocketMessage.ResponseDone -> {" in ws_coordinator,
            "流式回复结束时会触发提醒判断",
        )
    )
    results.append(
        _check(
            "notifyReplyIfBackground(message.text)" in ws_coordinator,
            "非流式整条回复也会触发提醒判断",
        )
    )
    results.append(
        _check(
            "private fun notifyReplyIfBackground(" in ws_coordinator
            and "AppForegroundTracker.isForeground" in ws_coordinator,
            "回复提醒仅在 App 处于后台时弹出（前台已上屏，不重复打扰）",
        )
    )
    results.append(
        _check(
            "import com.aveline.ai.mobile.utils.AppForegroundTracker" in ws_coordinator,
            "复用已有的 AppForegroundTracker（不另造前后台判断）",
        )
    )

    # 4. 通知深链不再只靠启发式
    results.append(
        _check(
            'target = json.optString("target").ifEmpty { null }' in ws_manager,
            "notification 解析后端下发的 target",
        )
    )
    results.append(
        _check(
            'sessionId = json.optString("session_id").ifEmpty { null }' in ws_manager,
            "notification 解析后端下发的 session_id",
        )
    )
    results.append(
        _check(
            "fun chatDeepLink(" in ws_deep_link
            and "roleIdFromConversationId(message.conversationId)" in ws_deep_link,
            "主动消息按 conversation_id 生成直达会话的深链",
        )
    )

    # 5. 未使用 import
    unused: list[str] = []
    for path in (WS_MESSAGE, WS_MANAGER, WS_COORDINATOR, WS_DEEP_LINK):
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
    print("全部通过：Active Care 与后台回复都会提醒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
