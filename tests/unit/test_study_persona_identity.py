"""学习行为不能替换当前角色；纠正身份的闲聊不能成为学习知识点。"""

from types import SimpleNamespace

import pytest

from core.agents.chat_agent_components.persona_system.prompt import data
from core.agents.chat_agent_components.persona_system.prompt.mode_control import (
    determine_mode,
    get_natural_dialogue_policy,
)
from core.services.study.mode_detector import is_study_mode
from core.services.study.signal_detector import detect_learning_signal


@pytest.mark.parametrize("filename", [
    "core_ling.json", "core_aveline.json", "core_custom.json",
    "study/Aveline_Study.json",
])
def test_learning_keeps_selected_persona_template(monkeypatch, filename):
    """包括显式选择的学习人设，模板始终服从当前选择。"""
    selected = "当前角色完整身份和说话习惯：" + filename

    def load_template(*, persona_filename):
        assert persona_filename == filename
        return selected, {}

    monkeypatch.setattr(data, "get_template_data", load_template)
    monkeypatch.setattr(data, "get_aveline_system_prompt_template", lambda: "Aveline 默认身份模板")
    agent = SimpleNamespace(config=SimpleNamespace(system_prompt="默认助手"))
    for mode in ("chat", "study"):
        assert data.get_base_template(agent, mode, "test", "用户", filename) == selected


@pytest.mark.parametrize("message", [
    "请好好看你人设是什么样的",
    "你的身份是什么？不要 OOC",
    "你的名字是什么",
    "解释一下你刚才的话",
    "我今天的心情是什么样的",
    "我没明白你的人设是什么",
    "为什么你今天不开心",
])
def test_personal_dialogue_is_not_a_learning_topic(message):
    signal = detect_learning_signal(message)
    assert not signal.is_learning
    assert not signal.concepts
    assert not is_study_mode(message)


@pytest.mark.parametrize("message", [
    "为什么 F = -kx 里面有负号？",
    "解释一下你说的导数",
    "什么是闭包",
    "什么是自我认知",
])
def test_knowledge_questions_still_enable_learning(message):
    assert detect_learning_signal(message).is_learning
    assert is_study_mode(message)


def test_study_mode_retains_teaching_policy():
    agent = SimpleNamespace(_is_study_mode=is_study_mode)
    assert determine_mode(agent, "进入学习模式") == "study"
    policy = get_natural_dialogue_policy("study", False, False, False, 0)
    assert "保持当前角色的身份" in policy
    assert "先复述你理解的卡点，再给下一步" in policy


def test_contextual_learning_feedback_remains_available():
    """不带概念的作答与困惑仍由教学记录器结合最近知识点处理。"""
    assert detect_learning_signal("我没听懂").is_learning
    assert detect_learning_signal("我选 B").is_learning
