"""验证主对话 prompt 对 HTTP（安卓）与 QQ 通道都注入「当前时间」与「当前渠道」。

背景：用户反馈 QQ 对话有时间戳注入，安卓端疑似没有。
本脚本直接调用 build_complete_message_list，分别模拟：
  - HTTP 通道（安卓）：is_qq_session=False，history 来自客户端 history_override
  - QQ 通道：is_qq_session=True
断言两条路径的最终 user 消息前缀都包含「当前时间」。

同时验证渠道标注的配套逻辑：
  - 「当前渠道」按本轮 platform 注入（App / QQ），历史里带「（来自QQ）」后缀的
    记录才有解释句，纯同渠道历史不多说一句；
  - 安卓 history_override 带 timestamp 时，历史消息要补 [今天/昨天/X天前 HH:MM] 前缀，
    否则模型分不清"我吃饭了"是几小时前说的，会出现"凌晨还在问吃完没有"。
"""

import asyncio
from contextlib import ExitStack
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.persona_system.prompt import (  # noqa: E402
    assembler,
    dynamic_injections,
)
from core.agents.chat_agent_components.persona_system.prompt.data import PromptData  # noqa: E402
from core.utils.data.chat_channel import (  # noqa: E402
    reset_current_platform,
    set_current_platform,
)


def patch_prompt_helper(stack, name, **kwargs):
    """拼装小函数分散在 assembler / dynamic_injections 两个命名空间，两边都打补丁。

    动态注入块解耦后从 assembler 搬到了 dynamic_injections，调用点换了命名空间；
    两边都打，脚本就不用关心某个函数住在哪。
    """
    for module in (assembler, dynamic_injections):
        if hasattr(module, name):
            stack.enter_context(patch.object(module, name, **kwargs))


def _build_messages(*, is_qq_session: bool, history_messages: list, platform: str = ""):
    """构造一条主对话消息（复用 verify_fixed_prefix 的 mock 集合）。"""
    data = PromptData()
    data.fixed_prefix = "固定规则"
    data.sensitive_prefix = ""
    data.base_template = "[V1角色卡]"
    data.persona_dynamic_prompt = "[动态状态]"
    data.mode = "chat"
    data.is_qq_source = is_qq_session
    data.persona_filename = "fixture.json"
    data.resolved_user_name = "测试用户"
    token = set_current_platform(platform)
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(assembler, "get_prompt_data", return_value=data)
        )
        patch_prompt_helper(stack, "is_bionic_character", return_value=False)
        patch_prompt_helper(stack, "filter_tool_names", return_value=[])
        stack.enter_context(patch("core.llm.llm_logger.log_llm_call_stats"))
        for name in (
            "get_special_day_prompt",
            "get_upcoming_birthday_prompt",
            "get_authoritative_calendar_prompt",
            "build_time_context",
            "build_emotion_context",
            "build_food_context",
            "build_study_context",
            "build_mentioned_people_injection",
            "get_tool_injection",
        ):
            patch_prompt_helper(stack, name, return_value="")
        stack.enter_context(
            patch(
                "config.integrated_config.get_settings",
                return_value=SimpleNamespace(
                    self_improvement=SimpleNamespace(enabled=False)
                ),
            )
        )
        try:
            return assembler.build_complete_message_list(
                agent=SimpleNamespace(tool_registry=None),
                message="今天天气怎么样",
                history_messages=history_messages,
                is_qq_session=is_qq_session,
            )
        finally:
            reset_current_platform(token)


def verify_both_channels_inject_timestamp() -> None:
    # 安卓 HTTP 通道：历史来自客户端 history_override（role/content 纯文本）
    http_history = [
        {"role": "assistant", "content": "上一条回复"},
        {"role": "user", "content": "用户之前问的话"},
    ]
    # QQ 通道：历史来自后端记忆池
    qq_history = [{"role": "assistant", "content": "上一条回复"}]

    http_msgs = _build_messages(
        is_qq_session=False, history_messages=http_history, platform=""
    )
    qq_msgs = _build_messages(
        is_qq_session=True, history_messages=qq_history, platform="qq"
    )

    print("== HTTP messages 结构 ==")
    for m in http_msgs:
        print(f"  role={m['role']!r} content={m['content'][:120]!r}")
    print("== QQ messages 结构 ==")
    for m in qq_msgs:
        print(f"  role={m['role']!r} content={m['content'][:120]!r}")

    http_user = http_msgs[-1]["content"]
    qq_user = qq_msgs[-1]["content"]

    assert "当前时间：" in http_user, f"HTTP 通道未注入时间戳: {http_user[:200]}"
    assert "当前时间：" in qq_user, f"QQ 通道未注入时间戳: {qq_user[:200]}"
    assert "【用户消息】\n今天天气怎么样" in http_user
    assert "【用户消息】\n今天天气怎么样" in qq_user

    print(f"[PASS] HTTP 通道 user 前缀: {http_user[:80]!r}")
    print(f"[PASS] QQ 通道 user 前缀: {qq_user[:80]!r}")


def verify_channel_injection() -> None:
    """「当前渠道」按本轮 platform 注入；只在历史真跨渠道时才补解释句。

    没有这一行，模型看到「（来自QQ）」后缀也不知道「没标的」是本渠道还是未知来源。
    """
    same_channel = _build_messages(
        is_qq_session=False,
        history_messages=[{"role": "user", "content": "本地说的"}],
        platform="",
    )
    app_user = same_channel[-1]["content"]
    assert "当前渠道：App" in app_user, f"App 通道未注入当前渠道: {app_user[:200]}"
    assert "不是当前渠道" not in app_user, "纯同渠道历史不该出现跨渠道解释句"

    qq_session = _build_messages(
        is_qq_session=True,
        history_messages=[{"role": "user", "content": "QQ 上说的"}],
        platform="qq",
    )
    qq_user = qq_session[-1]["content"]
    assert "当前渠道：QQ" in qq_user, f"QQ 通道未注入当前渠道: {qq_user[:200]}"
    assert "不是当前渠道" not in qq_user, "纯同渠道历史不该出现跨渠道解释句"

    mixed = _build_messages(
        is_qq_session=False,
        history_messages=[
            {"role": "user", "content": "QQ 上说的", "metadata": {"platform": "qq"}},
            {"role": "assistant", "content": "App 上说的", "metadata": {"platform": ""}},
        ],
        platform="",
    )
    mixed_user = mixed[-1]["content"]
    assert "当前渠道：App" in mixed_user, f"跨渠道历史未注入当前渠道: {mixed_user[:200]}"
    assert "来自QQ，不是当前渠道" in mixed_user, (
        f"历史里有 QQ 记录但没补解释句: {mixed_user[:300]}"
    )

    print("[PASS] 当前渠道按 platform 注入，跨渠道历史才补解释句")


def _build_override_history(history_override):
    """走 build_conversation_history 的 history_override 分支，捕获喂给 LLM 的历史。"""
    from core.agents.chat_agent_components.context import build_conversation_history

    class _DummyMemoryManager:
        lock = None
        short_term_memory = []

        def get_history(self, scope=None):
            return []

    class _DummyAgent:
        def __init__(self):
            self.mm = _DummyMemoryManager()
            self.vocab_manager = None
            self.llm_module = None
            self.dependency_manager = None
            self.defect_manager = None

        def _get_memory_manager(self, user_id):
            return self.mm

        def _is_study_mode(self, message, model_hint=None):
            return False

        def _get_dynamic_system_prompt(self, user_id=None, active_tools=None, mode=None, message=None):
            return "sys"

    captured = {}

    def _fake_build_complete(agent, user_id=None, message=None, user_name=None,
                             history_messages=None, state_context=None,
                             sensitive_injections=None, is_qq_session=False,
                             is_sensitive_mode=False, extra_dynamic_context=None,
                             memory_manager=None, persona_filename=None,
                             active_tools=None):
        captured["history_messages"] = history_messages
        return []

    with patch(
        "core.agents.chat_agent_components.persona_system.prompt.build_complete_message_list",
        _fake_build_complete,
    ):
        asyncio.run(
            build_conversation_history(
                _DummyAgent(),
                "shared__persona__test",
                "今天天气怎么样",
                model_hint="local",
                history_override=history_override,
                active_tools_override=[],
            )
        )
    return captured["history_messages"]


def verify_override_history_gets_timestamp_prefix():
    """安卓 history_override 带 timestamp 时，历史消息要补 [今天/昨天/X天前 HH:MM] 前缀。"""
    # 模拟安卓端上传：20:00 说吃饭、20:05 AI 回复、凌晨 04:00 用户又问了一句。
    # timestamp 用固定秒级时间戳（已由后端 router 归一化），断言只校验格式，不依赖真实时钟。
    ts_evening = 1_754_683_200.0  # 固定锚点，仅用于格式断言
    ts_evening_plus = ts_evening + 300.0
    ts_dawn = ts_evening + 8 * 3600.0

    override_with_ts = [
        {"role": "user", "content": "我吃饭了", "timestamp": ts_evening},
        {"role": "assistant", "content": "好的，慢慢吃", "timestamp": ts_evening_plus},
        {"role": "user", "content": "你睡了吗", "timestamp": ts_dawn},
    ]
    history = _build_override_history(override_with_ts)
    assert len(history) == 3, f"预期 3 条历史，实际 {len(history)}"

    prefix_re = re.compile(r"^\[(?:今天|昨天|\d+天前) \d{2}:\d{2}\] ")
    for msg, raw in zip(history, override_with_ts):
        content = msg["content"]
        assert prefix_re.match(content), f"历史消息缺少相对时间前缀: {content!r}"
        # 去掉前缀后正文不变（sanitize 只补前缀，不吞内容）
        assert content.split("] ", 1)[1] == raw["content"], f"正文被改写: {content!r}"
    print(f"[PASS] override 历史带 timestamp 时补相对时间前缀: "
          f"{[m['content'][:28] for m in history]}")

    # 旧客户端不带 timestamp：不补前缀、不报错（向后兼容）
    history_no_ts = _build_override_history(
        [{"role": "user", "content": "我吃饭了"}, {"role": "assistant", "content": "好的"}]
    )
    assert [m["content"] for m in history_no_ts] == ["我吃饭了", "好的"]
    print("[PASS] 旧客户端不带 timestamp 时历史原样透传（向后兼容）")


def main() -> None:
    verify_both_channels_inject_timestamp()
    verify_channel_injection()
    verify_override_history_gets_timestamp_prefix()
    print(
        "时间戳与渠道注入一致性验证通过：HTTP（安卓）/ QQ 均注入当前时间与当前渠道，"
        "override 历史补相对时间前缀"
    )


if __name__ == "__main__":
    main()
