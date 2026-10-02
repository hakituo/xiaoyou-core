"""验证「聊天记录渠道标注」：判据覆盖存量数据、清洗标注、检索结果标注。

背景：QQ 导出的历史、QQ bot 实时对话、App 实时对话写进的是**同一个**
conversation_id / 同一份记忆池，模型读历史时混在一起读，却没有任何来源信息，
分不清「这条是 QQ 上说的」还是「刚刚在 App 里说的」。

本脚本验证四件事：
1. 判据覆盖：真实存量事件里每一条都能判出来源，且已知桶的量级符合预期
   （platform / imported / QQ 车道名三级兜底都命中）；
2. 清洗标注：App 渠道下 QQ 记录带「（来自QQ）」、App 记录不带，且重复清洗不叠加；
3. 检索标注：search_chat_history 的格式化结果带来源后缀；
4. 反向标注：QQ 渠道下 App 记录带「（来自App）」。

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\chat_history\\verify_chat_channel_labeling.py
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.context_budget.history_fetch import (  # noqa: E402
    sanitize_history_messages,
)
from core.tools.search_chat_history_tool import SearchChatHistoryTool  # noqa: E402
from core.utils.data.chat_channel import (  # noqa: E402
    CHANNEL_APP,
    get_current_platform,
    reset_current_platform,
    resolve_event_channel,
    set_current_platform,
)

#: 判据必须能覆盖的存量桶：(车道, source) → 期望渠道。取自真实数据统计。
_EXPECTED_BUCKETS = {
    ("主线对话", "dated_chat_transcript_import"): "qq",
    ("主线对话", "chat_agent"): None,  # 混合：platform=qq 与空串都有，按事件单独判定
    ("QQ对话", "pairs_txt_import"): "qq",
    ("QQ对话", "user"): "qq",
    ("QQ对话", "active_care"): "qq",
    ("主线对话", "active_care"): None,
}


def _iter_real_events():
    """遍历 companion_data 下的真实 chat_history 事件，产出 (车道, source, 渠道)。"""
    pattern = str(PROJECT_ROOT / "companion_data" / "*" / "chat_history" / "*" / "*" / "*" / "*" / "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        lane = Path(path).parent.name
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                source = str((event.get("metadata") or {}).get("source") or "")
                yield lane, source, resolve_event_channel(event)


def verify_real_data_coverage() -> None:
    """真实存量事件：每条都判得出渠道，且已知桶落在期望渠道上。"""
    buckets: dict[tuple[str, str], dict[str, int]] = {}
    total = 0
    for lane, source, channel in _iter_real_events():
        total += 1
        buckets.setdefault((lane, source), {})
        buckets[(lane, source)][channel] = buckets[(lane, source)].get(channel, 0) + 1

    if total == 0:
        print("  [SKIP] 未找到 companion_data 下的 chat_history（CI 环境正常）")
        return

    for key, expected in _EXPECTED_BUCKETS.items():
        found = buckets.get(key)
        assert found, f"存量数据里缺少预期桶 {key}，判据口径可能已变"
        if expected is not None:
            assert set(found) == {expected}, f"{key} 期望全为 {expected}，实际 {found}"

    # App 桶与 QQ 桶都必须非空：判据退化成一侧就会在这里报红
    app_events = sum(c.get(CHANNEL_APP, 0) for c in buckets.values())
    qq_events = sum(c.get("qq", 0) for c in buckets.values())
    assert app_events > 0, "没有任何事件判为 App，判据可能把所有记录都归到了 QQ"
    assert qq_events > 0, "没有任何事件判为 QQ，判据可能失效"
    print(
        f"  [PASS] 存量 {total} 条事件全部判出来源："
        f"QQ {qq_events} 条 / App {app_events} 条，已知桶口径一致"
    )


def _event(role: str, content: str, platform: str) -> dict:
    return {
        "role": role,
        "content": content,
        "timestamp": 1_754_683_200.0,
        "metadata": {"platform": platform},
    }


def verify_history_labeling() -> None:
    """App 渠道下清洗历史：QQ 记录带后缀，App 记录不带，且幂等。"""
    token = set_current_platform("")
    try:
        history = [
            _event("user", "QQ 上说的那句", "qq"),
            _event("assistant", "QQ 上回的那句", "qq"),
            _event("user", "刚在 App 里说的", ""),
        ]
        cleaned = sanitize_history_messages(history, current_platform="app")
        assert cleaned[0]["content"].endswith("（来自QQ）"), cleaned[0]["content"]
        assert cleaned[1]["content"].endswith("（来自QQ）"), cleaned[1]["content"]
        assert "（来自" not in cleaned[2]["content"], cleaned[2]["content"]

        twice = sanitize_history_messages(cleaned, current_platform="app")
        assert twice[0]["content"].count("（来自QQ）") == 1, "重复清洗叠加了后缀"
        print("  [PASS] App 渠道：QQ 历史标（来自QQ），App 历史零噪音，重复清洗幂等")

        # 反向：QQ 渠道下 App 记录要标出来
        reverse = sanitize_history_messages(
            [_event("user", "刚在 App 里说的", "")], current_platform="qq"
        )
        assert reverse[0]["content"].endswith("（来自App）"), reverse[0]["content"]
        print("  [PASS] QQ 渠道：App 历史标（来自App）")

        # 未显式传渠道时读 ContextVar
        set_current_platform("qq")
        from_ctx = sanitize_history_messages([_event("user", "刚在 App 里说的", "")])
        assert from_ctx[0]["content"].endswith("（来自App）"), from_ctx[0]["content"]
        assert get_current_platform() == "qq"
        print("  [PASS] 未显式传渠道时按 ContextVar 判定")
    finally:
        reset_current_platform(token)


def verify_search_tool_labeling() -> None:
    """检索工具返回的格式化文本带来源后缀。"""
    token = set_current_platform("app")
    try:
        tool = SearchChatHistoryTool()
        events = [
            {
                "role": "user",
                "content": "QQ 上的旧对话",
                "created_at": "2025-08-01 20:00:00",
                "metadata": {"platform": "qq"},
            },
            {
                "role": "assistant",
                "content": "App 上的新对话",
                "created_at": "2026-09-27 20:00:00",
                "metadata": {"platform": ""},
            },
        ]
        text = tool._format_results(events)  # noqa: SLF001
        assert "QQ 上的旧对话（来自QQ）" in text, text
        assert "App 上的新对话（来自" not in text, text

        peer_text = tool._format_peer_results(events, "Ling")  # noqa: SLF001
        assert "QQ 上的旧对话（来自QQ）" in peer_text, peer_text
        print("  [PASS] search_chat_history 普通检索 / peer 检索结果都带来源后缀")
    finally:
        reset_current_platform(token)


def main() -> None:
    print("== 1. 存量数据判据覆盖 ==")
    verify_real_data_coverage()
    print("== 2. 历史清洗标注 ==")
    verify_history_labeling()
    print("== 3. 检索结果标注 ==")
    verify_search_tool_labeling()
    print("\n渠道标注验证通过：判据覆盖存量数据，历史与检索结果都能标出跨渠道来源")


if __name__ == "__main__":
    main()
