"""按 provider 自动注入 prompt caching 标记的契约测试。

覆盖三件事：
1. 判定表：哪些上游要加标记、加哪种（OpenRouter 文档口径）
2. 标记落点：断点打在静态 system 与倒数第二条，动态尾巴不碰
3. 防误伤：自动缓存的上游与其它 provider 的 payload 必须保持原样
"""

from __future__ import annotations

from core.llm.openai_compat import DeepSeekClient, OpenAIClient
from core.llm.openai_compat.cache_markers import (
    STYLE_BLOCK,
    STYLE_NONE,
    STYLE_TOP_LEVEL,
    apply_cache_markers,
    mark_cache_breakpoints,
    pick_breakpoint_indices,
    resolve_cache_strategy,
    sticky_session_id,
)


OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK = "https://api.deepseek.com/chat/completions"


def _messages() -> list:
    """贴近主聊天路径的布局：静态 system + 历史 + 最后一条动态 user"""
    return [
        {"role": "system", "content": "你是玲，一个静态人设"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
        {"role": "user", "content": "当前时间：2026-09-19 07:00\n\n【用户消息】\n在吗"},
    ]


# ---------------------------------------------------------------- 判定表


def test_anthropic_on_openrouter_uses_top_level():
    strategy = resolve_cache_strategy(OPENROUTER, "anthropic/claude-opus-4.6")
    assert strategy.style == STYLE_TOP_LEVEL
    assert strategy.provider == "anthropic"
    assert "自动缓存" in strategy.reason


def test_anthropic_accepts_cloud_prefixed_model_path():
    strategy = resolve_cache_strategy(
        OPENROUTER, "cloud:openrouter:anthropic/claude-opus-4.6"
    )
    assert strategy.style == STYLE_TOP_LEVEL


def test_gemini_needs_block_breakpoints():
    strategy = resolve_cache_strategy(OPENROUTER, "google/gemini-3.8-flash")
    assert strategy.style == STYLE_BLOCK
    assert strategy.provider == "google"


def test_qwen_whitelist_only():
    assert resolve_cache_strategy(OPENROUTER, "qwen/qwen3-max").style == STYLE_BLOCK
    assert resolve_cache_strategy(OPENROUTER, "deepseek/deepseek-v3.2").style == STYLE_BLOCK
    # 快照端点不支持显式缓存
    assert resolve_cache_strategy(OPENROUTER, "qwen/qwen3.5-plus-02-15").style == STYLE_NONE


def test_auto_cached_providers_get_nothing():
    """DeepSeek / Grok / Moonshot 上游自动缓存，塞标记反而可能被当成未知字段"""
    for model in ("deepseek/deepseek-v4-flash", "x-ai/grok-4.20", "moonshotai/kimi-k2.6",
                  "openai/gpt-5.6", "minimax/minimax-m3:free"):
        assert resolve_cache_strategy(OPENROUTER, model).style == STYLE_NONE, model


def test_direct_providers_are_untouched():
    """直连厂商不走 OpenRouter 规则，即使模型名带 anthropic/ 前缀也不能误加"""
    assert resolve_cache_strategy(DEEPSEEK, "anthropic/claude-opus-4.6").style == STYLE_NONE
    assert resolve_cache_strategy(None, "anthropic/claude-opus-4.6").style == STYLE_NONE
    assert resolve_cache_strategy("https://open.bigmodel.cn/api/paas/v4", "glm-5.1").style == STYLE_NONE


def test_direct_anthropic_api_supported():
    strategy = resolve_cache_strategy("https://api.anthropic.com/v1/messages", "claude-opus-4.6")
    assert strategy.style == STYLE_TOP_LEVEL


def test_anthropic_defaults_to_1h_ttl():
    """多角色轮流对话：1 小时 TTL 才不会切去聊别的角色回来就要重写缓存"""
    assert resolve_cache_strategy(OPENROUTER, "anthropic/claude-opus-4.6").ttl == "1h"
    assert resolve_cache_strategy(OPENROUTER, "anthropic/claude-opus-4.6", ttl="1h").ttl == "1h"
    # 未知 TTL 退化为 5 分钟，不把脏值发给上游
    assert resolve_cache_strategy(OPENROUTER, "anthropic/claude-opus-4.6", ttl="30m").ttl == ""
    # 想省写缓存的钱可以显式退回 5 分钟
    assert resolve_cache_strategy(OPENROUTER, "anthropic/claude-opus-4.6", ttl="5m").ttl == ""


def test_1h_ttl_is_anthropic_only():
    """Gemini 固定 5 分钟且"不刷新"，Alibaba Qwen 也只有 5 分钟，发 1h 没意义"""
    assert resolve_cache_strategy(OPENROUTER, "google/gemini-3.8-flash").ttl == ""
    assert resolve_cache_strategy(OPENROUTER, "qwen/qwen3-max").ttl == ""
    assert resolve_cache_strategy(DEEPSEEK, "deepseek-v4-flash").ttl == ""


# ---------------------------------------------------------------- 断点落点


def test_breakpoints_land_on_system_and_second_last():
    marked = mark_cache_breakpoints(_messages())
    # 首条 system 被拆成块并打点
    assert isinstance(marked[0]["content"], list)
    assert marked[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # 倒数第二条（历史末尾）打点
    assert marked[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # 最后一条（当前时间/环境/记忆/用户消息）不动
    assert marked[3] == _messages()[3]
    # 中间那条普通历史不打点
    assert marked[1] == _messages()[1]


def test_breakpoints_respect_ttl():
    marked = mark_cache_breakpoints(_messages(), ttl="1h")
    assert marked[0]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_breakpoint_count_is_capped():
    long_history = [{"role": "system", "content": "人设"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}轮"}
        for i in range(10)
    ]
    assert len(pick_breakpoint_indices(long_history)) <= 2


def test_empty_and_tool_only_messages_are_skipped():
    messages = [
        {"role": "system", "content": ""},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "user", "content": "问题"},
    ]
    marked = mark_cache_breakpoints(messages)
    # 空 system 无法承载断点，保持原样
    assert marked[0]["content"] == ""
    # content 为 None 的 assistant（纯 tool_calls）不能被拆块
    assert marked[1]["content"] is None


def test_existing_block_content_is_preserved():
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "人设"}]},
        {"role": "user", "content": [{"type": "text", "text": "看图"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}]},
        {"role": "user", "content": "说点什么"},
    ]
    marked = mark_cache_breakpoints(messages)
    assert marked[0]["content"][0]["text"] == "人设"
    assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # 第二条是倒数第二，断点落在最后一个块（图片块）上，前面的块保持原样
    assert marked[1]["content"][0] == {"type": "text", "text": "看图"}
    assert marked[1]["content"][-1]["type"] == "image_url"


# ---------------------------------------------------------------- payload 注入


def test_anthropic_payload_gets_top_level_marker_and_session_id():
    payload = {"model": "anthropic/claude-opus-4.6", "messages": _messages()}
    apply_cache_markers(payload, base_url=OPENROUTER)

    assert payload["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert len(payload["session_id"]) <= 256
    # 自动缓存模式下消息本体保持原样
    assert payload["messages"] == _messages()


def test_gemini_payload_gets_block_markers():
    payload = {"model": "google/gemini-3.8-flash", "messages": _messages()}
    apply_cache_markers(payload, base_url=OPENROUTER)

    assert "cache_control" not in payload  # 块级模式不写请求级字段
    assert isinstance(payload["messages"][0]["content"], list)
    assert payload["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["session_id"]


def test_auto_cached_payload_only_gets_session_id():
    payload = {"model": "deepseek/deepseek-v4-flash", "messages": _messages()}
    apply_cache_markers(payload, base_url=OPENROUTER)

    assert "cache_control" not in payload
    assert payload["messages"] == _messages()
    assert payload["session_id"]


def test_non_openrouter_payload_is_untouched():
    payload = {"model": "deepseek-v4-flash", "messages": _messages()}
    apply_cache_markers(payload, base_url=DEEPSEEK)

    assert payload == {"model": "deepseek-v4-flash", "messages": _messages()}


def test_markers_can_be_disabled_per_call():
    payload = {"model": "anthropic/claude-opus-4.6", "messages": _messages()}
    apply_cache_markers(payload, base_url=OPENROUTER, markers=False)
    assert "cache_control" not in payload
    assert payload["session_id"]


def test_session_id_is_stable_per_conversation():
    first = sticky_session_id(_messages())
    again = sticky_session_id(_messages())
    assert first == again

    changed = sticky_session_id(
        [{"role": "system", "content": "你是Ye，另一个人设"}] + _messages()[1:]
    )
    assert changed != first


def test_session_id_ignores_churn_after_system():
    """working_set / 历史 / 当前消息变化都不应打断 sticky 绑定

    否则同一个角色每轮都可能被丢到没缓存的 provider 上（首条非 system 是资料召回，
    内容每轮都在变）。
    """
    base = sticky_session_id(_messages())
    # 只换 system 之后的第二条（working_set）
    swapped_working_set = [
        _messages()[0],
        {"role": "user", "content": "另一批召回资料"},
        *_messages()[2:],
    ]
    assert sticky_session_id(swapped_working_set) == base

    # 换最后一条（当前时间 / 环境 / 用户消息）
    swapped_tail = [*_messages()[:-1], {"role": "user", "content": "当前时间：别的时刻"}]
    assert sticky_session_id(swapped_tail) == base


def test_different_characters_get_different_session_ids():
    """不同角色的人设不同 → 落到不同 provider，各自保暖互不挤占"""
    aveline = sticky_session_id([{"role": "system", "content": "你是艾薇琳"}, *_messages()[1:]])
    ling = sticky_session_id([{"role": "system", "content": "你是玲"}, *_messages()[1:]])
    assert aveline != ling


# ---------------------------------------------------------------- 客户端接线


def test_openai_client_injects_for_openrouter_base_url():
    client = OpenAIClient(api_key="k", base_url=OPENROUTER, model="anthropic/claude-opus-4.6")
    payload = client._build_payload(_messages(), stream=False)
    assert payload["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert payload["session_id"]


def test_openai_client_honours_per_call_overrides():
    client = OpenAIClient(api_key="k", base_url=OPENROUTER, model="anthropic/claude-opus-4.6")
    payload = client._build_payload(_messages(), stream=False, cache_ttl="1h")
    assert payload["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    off = client._build_payload(_messages(), stream=False, cache_markers=False)
    assert "cache_control" not in off


def test_deepseek_client_payload_has_no_markers():
    """直连 DeepSeek 上游自动缓存，payload 必须一字不改"""
    client = DeepSeekClient(api_key="k")
    payload = client._build_payload(_messages(), stream=False)
    assert "cache_control" not in payload
    assert "session_id" not in payload
    assert payload["messages"] == [
        {"role": "system", "content": "你是玲，一个静态人设"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
        {"role": "user", "content": "当前时间：2026-09-19 07:00\n\n【用户消息】\n在吗"},
    ]
