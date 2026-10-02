"""角色系统提示守卫测试

提示模板重构后，风格约束已移到人设配置与上下文注入中，这里只守住
代码路径注入的平台能力与事实约束，不再断言被模板迁移掉的旧文案。
"""

from core.agents.chat_agent_components.persona import get_dynamic_system_prompt


class _DummyConfig:
    def __init__(self):
        self.system_prompt = "你是一个助手，请用中文回答用户问题。"


class _DummyAgent:
    def __init__(self):
        self.config = _DummyConfig()
        self.llm_module = None
        self.memory_echoes = None

    def _is_study_mode(self, message: str) -> bool:
        return False

    def _get_memory_manager(self, cid: str):
        raise RuntimeError("no memory")


def _build_prompt(user_id: str, message: str) -> str:
    return get_dynamic_system_prompt(
        _DummyAgent(),
        user_id=user_id,
        mode="chat",
        message=message,
    )


def test_qq_prompt_has_platform_capability_and_no_bracket_action_rules():
    """QQ 会话注入平台发送能力说明，且不再注入括号动作描写规则"""
    prompt = _build_prompt("group_1_2", "你在干嘛")

    assert "【QQ 气泡发送能力】" in prompt
    assert "任何括号里的描述" not in prompt


def test_non_qq_prompt_does_not_recommend_bracket_emotes():
    """非 QQ 会话不注入表情包式表达建议"""
    prompt = _build_prompt("test_user", "你在干嘛")

    assert "表达情绪优先用 [害羞]/[呲牙]/[无奈]" not in prompt
    assert "表达情绪优先用 [害羞]/[亲亲]/[比心]" not in prompt


def test_non_qq_wants_long_does_not_recommend_kaomoji():
    """长回复诉求下仍不注入颜文字建议（风格约束由人设配置负责）"""
    prompt = _build_prompt("test_user", "详细说下怎么做")

    assert "颜文字" not in prompt


def test_prompt_contains_authoritative_calendar_anchor():
    """所有会话都注入权威日历事实锚点，纠正历史与记忆里的过期日期"""
    prompt = _build_prompt("private_1", "现在几点了")

    assert "【权威日历事实锚点】" in prompt
    assert "以本锚点为准" in prompt
