"""主动消息角色白名单过滤。

白名单权威源是 character_runtime.yaml 的 autonomous_roles（core/character/runtime_roles.py），
app.yaml 的 life_simulation.active_care_enabled_roles 是旧部署的兼容回退。
当前接入主动关怀的只有 Aveline / Ye（ye）；Ling（ling）与Lin（lin）仍是已注册
角色、能正常对话，但不主动给用户发消息；未接入的角色（如 rushuang、yeye、xiaolu）
同样不允许主动发消息。
晚安/早安在 SleepManager 已过滤，常规 checker 触发与回归消息统一在
executor.trigger_message_with_result 入口兜底。
"""

import pytest

from core.services.active_care.core.executor import ActiveCareExecutor
from core.services.active_care.core.trigger_result import TriggerOutcome


def test_persona_token_mapped_to_role_id():
    assert ActiveCareExecutor._is_active_care_enabled_persona("core_aveline.json")
    # Ye已于 2026-10-01 从主动消息中移除：能正常对话，但不主动发消息
    assert not ActiveCareExecutor._is_active_care_enabled_persona("core_ye.json")
    # 分层人设：入口文件名是 lin/core_lin.json，客户端按 core_lin.json 传参。
    assert not ActiveCareExecutor._is_active_care_enabled_persona("core_lin.json")
    assert not ActiveCareExecutor._is_active_care_enabled_persona("core_ling.json")
    assert not ActiveCareExecutor._is_active_care_enabled_persona("core_rushuang.json")


@pytest.mark.asyncio
async def test_trigger_message_blocks_non_whitelisted_persona():
    """未接入白名单的角色在入口处直接拦截，不进入生成与分发。"""
    executor = ActiveCareExecutor.__new__(ActiveCareExecutor)
    result = await executor.trigger_message_with_result(
        sys_prompt_type="checking",
        user_input_mock="[ACTIVE_CARE_TRIGGER]",
        persona_filename="core_rushuang.json",
    )

    assert result.delivered is False
    assert result.outcome is TriggerOutcome.ROLE_NOT_ENABLED
