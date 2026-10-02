"""chat_history 渠道判定与来源标注的单测。

覆盖三件事：
1. ``resolve_event_channel`` 的三级判据（platform → imported → QQ 车道名）；
2. 历史清洗只给「与当前渠道不同」的记录打后缀，且重复清洗不叠加；
3. 聊天记录检索工具的格式化结果带来源后缀。
"""
from __future__ import annotations

import pytest

from core.utils.data.chat_channel import (
    CHANNEL_APP,
    channel_display_name,
    cross_channel_labels,
    current_channel_name,
    get_current_platform,
    reset_current_platform,
    resolve_event_channel,
    set_current_platform,
    source_suffix,
    strip_model_channel_marks,
    strip_source_suffix,
)


@pytest.fixture(autouse=True)
def _reset_current_channel():
    """ContextVar 不隔离用例，必须显式还原，否则会污染后续用例。"""
    token = set_current_platform("")
    yield
    reset_current_platform(token)


# ----------------------------------------------------------------------
# 判据
# ----------------------------------------------------------------------


def test_platform_字段优先于其他判据():
    assert resolve_event_channel({"metadata": {"platform": "qq"}}) == "qq"
    assert resolve_event_channel({"platform": "obsidian"}) == "obsidian"
    # 顶层与 metadata 同时存在时以顶层为准
    assert (
        resolve_event_channel({"platform": "obsidian", "metadata": {"platform": "qq"}})
        == "obsidian"
    )


def test_pairs_导入器只写_imported_时归_qq():
    """pairs 导入器不写 platform，只写 imported —— 只靠 platform 会漏一万多条。"""
    event = {"metadata": {"source": "pairs_txt_import", "imported": True}}
    assert resolve_event_channel(event) == "qq"


def test_source_kind_也能判定导入来源():
    event = {"metadata": {"source_kind": "user_supplied", "imported": True}}
    assert resolve_event_channel(event) == "qq"


def test_无_platform_的_qq_车道记录靠_readable_title_兜底():
    event = {"readable_title": "Ling / QQ对话", "metadata": {"source": "chat_agent"}}
    assert resolve_event_channel(event) == "qq"


def test_app_实时记录判为_app():
    # Android / HTTP 路径写的是空串 platform
    assert resolve_event_channel({"metadata": {"platform": ""}}) == CHANNEL_APP
    assert resolve_event_channel({"metadata": {"source": "chat_agent"}}) == CHANNEL_APP
    assert resolve_event_channel({}) == CHANNEL_APP
    # 车道名不含 QQ 的不能误判
    assert resolve_event_channel({"readable_title": "Lin / 主线对话"}) == CHANNEL_APP


def test_展示名映射():
    assert channel_display_name("app") == "App"
    assert channel_display_name("qq") == "QQ"
    assert channel_display_name("qq_official") == "QQ"
    assert channel_display_name("obsidian") == "Obsidian"


# ----------------------------------------------------------------------
# 后缀生成与幂等
# ----------------------------------------------------------------------


def test_同渠道不打后缀_异渠道打后缀():
    qq_event = {"metadata": {"platform": "qq"}}
    app_event = {"metadata": {"platform": ""}}
    assert source_suffix(qq_event, "qq") == ""
    assert source_suffix(qq_event, "app") == "（来自QQ）"
    assert source_suffix(app_event, "app") == ""
    assert source_suffix(app_event, "qq") == "（来自App）"


def test_strip_source_suffix_只剥末尾标注():
    assert strip_source_suffix("晚安（来自QQ）") == "晚安"
    assert strip_source_suffix("晚安") == "晚安"
    # 正文中间的括号不动
    assert strip_source_suffix("（来自QQ）是昨天说的") == "（来自QQ）是昨天说的"


def test_strip_model_channel_marks_剥掉模型自造的渠道标注():
    # 全角 / 半角括号，句尾
    assert strip_model_channel_marks("晚安（来自QQ）") == "晚安"
    assert strip_model_channel_marks("晚安(来自App)") == "晚安"
    assert strip_model_channel_marks("晚安（来自 手机）") == "晚安"
    # 句首与句中
    assert strip_model_channel_marks("（来自QQ）晚安") == "晚安"
    assert strip_model_channel_marks("嗯，然后（来自App）晚安") == "嗯，然后晚安"
    # 句尾裸写，含后面的标点
    assert strip_model_channel_marks("晚安，来自QQ") == "晚安，"
    assert strip_model_channel_marks("晚安。来自App。") == "晚安。"
    # 幂等
    once = strip_model_channel_marks("晚安（来自QQ）")
    assert strip_model_channel_marks(once) == once


def test_strip_model_channel_marks_不误伤正文():
    # 非渠道词不剥
    assert strip_model_channel_marks("晚安") == "晚安"
    assert strip_model_channel_marks("（来自QQ）是昨天说的") == "是昨天说的"
    # 括号里不是「来自…」开头的不动
    assert strip_model_channel_marks("（轻轻揉了揉眼睛）困了") == "（轻轻揉了揉眼睛）困了"
    # 「来自QQ音乐」这类带后续词的不是标注
    assert strip_model_channel_marks("这首歌来自QQ音乐") == "这首歌来自QQ音乐"
    # 句子中间的裸写不带分隔符，不剥
    assert strip_model_channel_marks("这条消息来自App") == "这条消息来自App"


def test_cross_channel_labels_去重保序且不含当前渠道():
    events = [
        {"metadata": {"platform": "qq"}},
        {"metadata": {"platform": ""}},
        {"metadata": {"platform": "qq"}},
        {"metadata": {"platform": "obsidian"}},
    ]
    assert cross_channel_labels(events, "app") == ["QQ", "Obsidian"]
    assert cross_channel_labels(events, "qq") == ["App", "Obsidian"]


# ----------------------------------------------------------------------
# 历史清洗
# ----------------------------------------------------------------------


def _event(role: str, content: str, platform: str, **extra):
    return {
        "role": role,
        "content": content,
        "timestamp": 1_754_683_200.0,
        "metadata": {"platform": platform},
        **extra,
    }


def test_清洗只给异渠道历史打后缀():
    from core.agents.chat_agent_components.context_budget.history_fetch import (
        sanitize_history_messages,
    )

    history = [
        _event("user", "昨天说的那句", "qq"),
        _event("assistant", "刚在这里说的", ""),
    ]
    cleaned = sanitize_history_messages(history, current_platform="app")
    assert cleaned[0]["content"].endswith("（来自QQ）")
    assert not cleaned[1]["content"].endswith("（来自QQ）")
    assert not cleaned[1]["content"].endswith("（来自App）")


def test_清洗幂等_重复调用不叠加后缀():
    from core.agents.chat_agent_components.context_budget.history_fetch import (
        sanitize_history_messages,
    )

    history = [_event("user", "昨天说的那句", "qq")]
    once = sanitize_history_messages(history, current_platform="app")
    twice = sanitize_history_messages(once, current_platform="app")
    assert twice[0]["content"].count("（来自QQ）") == 1


def test_清洗在_qq_渠道下不给_qq_历史打后缀():
    from core.agents.chat_agent_components.context_budget.history_fetch import (
        sanitize_history_messages,
    )

    cleaned = sanitize_history_messages(
        [_event("user", "QQ 上说的", "qq")], current_platform="qq"
    )
    assert "（来自" not in cleaned[0]["content"]


def test_清洗未显式传渠道时读_contextvar():
    from core.agents.chat_agent_components.context_budget.history_fetch import (
        sanitize_history_messages,
    )

    set_current_platform("qq")
    cleaned = sanitize_history_messages([_event("user", "App 上说的", "")])
    assert cleaned[0]["content"].endswith("（来自App）")
    assert get_current_platform() == "qq"
    assert current_channel_name() == "QQ"


# ----------------------------------------------------------------------
# 检索工具格式化
# ----------------------------------------------------------------------


def test_检索结果带来源后缀():
    from core.tools.search_chat_history_tool import SearchChatHistoryTool

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
    assert "QQ 上的旧对话（来自QQ）" in text
    assert "App 上的新对话（来自" not in text


def test_检索结果在_qq_渠道下反过来标_app():
    from core.tools.search_chat_history_tool import SearchChatHistoryTool

    set_current_platform("qq")
    tool = SearchChatHistoryTool()
    text = tool._format_results(  # noqa: SLF001
        [
            {
                "role": "user",
                "content": "App 上的旧对话",
                "created_at": "2025-08-01 20:00:00",
                "metadata": {"platform": ""},
            }
        ]
    )
    assert "App 上的旧对话（来自App）" in text
