"""人物/角色提取的 LLM 回复解析回归测试。

背景（errors_20260924）：
1. prompt 模板为兼容 str.format 把示例 JSON 写成双大括号，而 SYSTEM 段根本不参与
   format，模型照抄示例就输出 `{{"people": []}}`，json.loads 直接失败刷 ERROR 日志。
2. 角色更新批次里对话内容触发模型安全拒答，返回的是英文道歉文案（非 JSON），
   同样被当成解析失败记 ERROR。
"""

from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
    PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT,
    ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT,
)
from core.character.people.external_profile_service import (
    ExternalPeopleProfileService,
)
from core.character.people.role_update_service import RoleProfileUpdateService
from core.utils.json_utils import looks_like_refusal, unwrap_redundant_brackets

REFUSAL_TEXT = (
    "I can't help with this request. The dialogue sexualizes a character described "
    "as a high school student, and involves extreme degrading content."
)

PEOPLE_WITH_ITEM = '{{"people": [{{"name": "李小明", "confidence": 0.9}}]}}'
ROLE_WITH_ITEM = '{{"role_updates": [{{"role": "aveline", "facts": []}}]}}'


# ─────────────────────────────────────────────────────────
# 1. prompt 常量必须是可直接抄的单层 JSON
# ─────────────────────────────────────────────────────────

def test_system_prompts_have_no_escaped_double_braces():
    """SYSTEM 段不参与 .format()，示例里的 {{ }} 会原样发给模型。"""
    for name, prompt in (
        ("PEOPLE_PROFILE_EXTRACTION", PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT),
        ("ROLE_UPDATE_EXTRACTION", ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT),
    ):
        assert "{{" not in prompt, f"{name}_SYSTEM_PROMPT 仍含转义双括号 {{"
        assert "}}" not in prompt, f"{name}_SYSTEM_PROMPT 仍含转义双括号 }}"
        assert '"people": []' in prompt or '"role_updates": []' in prompt


def test_system_prompt_examples_are_valid_json():
    """示例 JSON 片段本身要能被解析（模型会照抄）。"""
    people_example = '{"people": []}'
    role_example = '{"role_updates": []}'
    assert people_example in PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT
    assert role_example in ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT
    assert '"role_updates"' in ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────
# 2. json_utils 新增的健壮性工具
# ─────────────────────────────────────────────────────────

def test_unwrap_redundant_brackets():
    assert unwrap_redundant_brackets('{{"people": []}}') == '{"people": []}'
    assert unwrap_redundant_brackets('{{"people": [{{"name": "李小明"}}]}}') == (
        '{"people": [{"name": "李小明"}]}'
    )
    # 本来就是合法 JSON 的（哪怕以 }} 结尾）绝不能动
    assert unwrap_redundant_brackets('{"a": {"b": 1}}') == '{"a": {"b": 1}}'
    assert unwrap_redundant_brackets('[[1, 2]]') == '[[1, 2]]'
    assert unwrap_redundant_brackets("") == ""
    assert unwrap_redundant_brackets("不是 JSON") == "不是 JSON"


def test_looks_like_refusal():
    assert looks_like_refusal(REFUSAL_TEXT)
    assert looks_like_refusal("抱歉，我无法处理这段对话内容。")
    # 含 JSON 的一律不算拒答，避免误杀正文里出现 "I can't" 的合法结果
    assert not looks_like_refusal('{"people": [{"value": "I can\'t help"}]}')
    assert not looks_like_refusal("")
    assert not looks_like_refusal('{"people": []}')


# ─────────────────────────────────────────────────────────
# 3. 两个服务的 parse_response
# ─────────────────────────────────────────────────────────

def test_external_parse_response_handles_double_braces():
    assert ExternalPeopleProfileService.parse_response('{{"people": []}}') == []
    people = ExternalPeopleProfileService.parse_response(PEOPLE_WITH_ITEM)
    assert len(people) == 1
    assert people[0]["name"] == "李小明"


def test_external_parse_response_still_handles_plain_and_fenced_json():
    assert ExternalPeopleProfileService.parse_response('{"people": []}') == []
    people = ExternalPeopleProfileService.parse_response(
        '```json\n{"people": [{"name": "张三", "confidence": 0.8}]}\n```'
    )
    assert [p["name"] for p in people] == ["张三"]
    assert ExternalPeopleProfileService.parse_response("") == []


def test_external_parse_response_returns_empty_on_refusal():
    """拒答不是解析 bug，不该抛异常，返回空列表即可。"""
    assert ExternalPeopleProfileService.parse_response(REFUSAL_TEXT) == []


def test_role_update_parse_response_handles_double_braces():
    assert RoleProfileUpdateService.parse_response('{{"role_updates": []}}') == []
    updates = RoleProfileUpdateService.parse_response(ROLE_WITH_ITEM)
    assert len(updates) == 1
    assert updates[0]["role"] == "aveline"


def test_role_update_parse_response_returns_empty_on_refusal():
    assert RoleProfileUpdateService.parse_response(REFUSAL_TEXT) == []
    assert RoleProfileUpdateService.parse_response("") == []
