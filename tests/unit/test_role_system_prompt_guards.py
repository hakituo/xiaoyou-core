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


def test_qq_prompt_has_guard_and_no_bracket_action_rules():
    agent = _DummyAgent()
    prompt = get_dynamic_system_prompt(
        agent,
        user_id="group_1_2",
        mode="chat",
        message="你在干嘛",
    )

    assert "QQ Platform Final Constraints" in prompt
    assert "任何括号里的描述" not in prompt


def test_non_qq_prompt_does_not_recommend_bracket_emotes():
    agent = _DummyAgent()
    prompt = get_dynamic_system_prompt(
        agent,
        user_id="test_user",
        mode="chat",
        message="你在干嘛",
    )

    assert "表达情绪优先用 [害羞]/[呲牙]/[无奈]" not in prompt
    assert "表达情绪优先用 [害羞]/[亲亲]/[比心]" not in prompt


def test_non_qq_wants_long_does_not_recommend_kaomoji():
    agent = _DummyAgent()
    prompt = get_dynamic_system_prompt(
        agent,
        user_id="test_user",
        mode="chat",
        message="详细说下怎么做",
    )

    assert "不用表情/颜文字" in prompt


def test_prompt_contains_time_consistency_hard_guard():
    agent = _DummyAgent()
    prompt = get_dynamic_system_prompt(
        agent,
        user_id="private_1",
        mode="chat",
        message="现在几点了",
    )

    assert "【时间一致性硬约束】" in prompt
    assert "必须直接基于该锚点作答" in prompt
