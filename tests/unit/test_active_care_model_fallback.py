"""Active Care 模型主链与失败回退测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from config.model_config import (
    get_active_care_primary_models,
    get_fallback_model_for_active_care,
)
from core.llm.cloud_router import CloudRouterLLMModule
from core.services.active_care.core.response_generator import ActiveCareResponseGenerator
from core.services.active_care.decision import decision_tools
from clients.bots.handlers.resources import _is_free_model


PRIMARY_MODEL = "cloud:minimax:MiniMax-M3"
FREE_MODEL = "cloud:openrouter:openrouter/free"
FALLBACK_MODEL = PRIMARY_MODEL


def test_active_care_model_config_uses_official_m3_directly():
    """Active Care 主链直接走官方 M3，不再让 M3替免费模型重做。"""
    assert get_active_care_primary_models() == {PRIMARY_MODEL}
    assert get_fallback_model_for_active_care() == ""


def test_free_router_is_hidden_from_manual_model_list():
    """免费聚合路由仍应沿用免费模型的手动选择隐藏策略。"""
    assert _is_free_model({"model": "openrouter/free"})
    assert _is_free_model({"path": FREE_MODEL})


@pytest.mark.asyncio
async def test_cloud_router_falls_back_on_debug_error_and_keeps_call_options():
    """免费路由把 404 包成 DEBUG_ERROR 时也必须触发官方 M3 回退。"""
    primary = AsyncMock()
    primary.chat.return_value = "[DEBUG_ERROR] Error: API returned 404"
    fallback = AsyncMock()
    fallback.chat.return_value = {"status": "success", "response": "晚安"}

    router = object.__new__(CloudRouterLLMModule)

    def select_client(model_path, kwargs):
        selected = dict(kwargs)
        selected["model_path"] = model_path
        selected["model"] = model_path.split(":", 2)[-1]
        return (fallback if model_path == FALLBACK_MODEL else primary), selected

    router._select_client = select_client
    result = await router.chat(
        [{"role": "user", "content": "test"}],
        model_path=FREE_MODEL,
        temperature=0.3,
        max_new_tokens=80,
        tools=[{"type": "function"}],
    )

    assert result == {"status": "success", "response": "晚安"}
    fallback.chat.assert_awaited_once()
    fallback_kwargs = fallback.chat.await_args.kwargs
    assert fallback_kwargs["model_path"] == FALLBACK_MODEL
    assert fallback_kwargs["temperature"] == 0.3
    assert fallback_kwargs["max_new_tokens"] == 80
    assert fallback_kwargs["tools"] == [{"type": "function"}]


@pytest.mark.asyncio
async def test_cloud_router_treats_reasoning_only_as_failure():
    """免费模型只返回内部推理时必须转官方 M3，推理文本不得下发。"""
    primary = AsyncMock()
    primary.chat.return_value = {
        "response": "",
        "reasoning_only": True,
        "reasoning_text": "我需要根据角色设定分析用户状态",
    }
    fallback = AsyncMock()
    fallback.chat.return_value = {"status": "success", "response": "我先睡了，晚安。"}

    router = object.__new__(CloudRouterLLMModule)

    def select_client(model_path, kwargs):
        selected = dict(kwargs)
        selected["model_path"] = model_path
        return (fallback if model_path == FALLBACK_MODEL else primary), selected

    router._select_client = select_client
    result = await router.chat(
        [{"role": "user", "content": "test"}],
        model_path=FREE_MODEL,
    )

    assert result == {"status": "success", "response": "我先睡了，晚安。"}
    assert "角色设定" not in str(result)
    fallback.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_care_never_extracts_reasoning_only_as_message():
    """即使官方模型异常只回推理，Active Care 也必须丢弃而不是下发。"""
    llm = AsyncMock()
    llm.chat.return_value = {
        "response": "",
        "reasoning_only": True,
        "reasoning_text": "用户当前处于空闲状态，我应该分析角色设定",
    }
    generator = ActiveCareResponseGenerator(settings=object())

    with patch(
        "core.services.active_care.core.response_generator.get_llm_module",
        return_value=llm,
    ):
        result = await generator.generate(
            model_user_input="test",
            sys_prompt="test",
            model_hint=PRIMARY_MODEL,
        )

    assert result["content"] == ""
    assert result["error"] == "reasoning_only_no_fallback"
    assert "角色设定" not in result["content"]
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "leaked_response",
    [
        (
            'The user is asking me to generate a proactive message as "Ye". '
            "I need to respond as the configured character and keep it concise."
        ),
        (
            'The user said "早安" a few minutes ago. Now I need to send an active '
            "care message. Let me analyze the situation: I already asked about food."
        ),
        "用户当前处于空闲状态，我需要根据角色设定来回应。作为Ye，我应该保持自然。",
    ],
)
async def test_active_care_drops_cot_misplaced_in_response(leaked_response):
    """模型把 CoT 错放进 response 时必须丢弃，原文不得进入发送内容。"""
    llm = AsyncMock()
    llm.chat.return_value = {"status": "success", "response": leaked_response}
    generator = ActiveCareResponseGenerator(settings=object())

    with patch(
        "core.services.active_care.core.response_generator.get_llm_module",
        return_value=llm,
    ):
        result = await generator.generate(
            model_user_input="test",
            sys_prompt="test",
            model_hint=PRIMARY_MODEL,
        )

    assert result["content"] == ""
    assert result["error"] == "reasoning_only_no_fallback"
    assert leaked_response not in result["content"]
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_decision_tool_wrapper_awaits_llm_result():
    """决策工具封装不得把 coroutine 对象当作模型正文返回。"""
    llm = AsyncMock()
    llm.chat.return_value = {"response": "ok"}

    with patch.object(decision_tools, "get_llm_module", return_value=llm):
        result = await decision_tools.llm_chat_with_tools(
            [{"role": "user", "content": "test"}],
            temperature=0.2,
            max_new_tokens=30,
            model_path=PRIMARY_MODEL,
        )

    assert result == {"response": "ok"}
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_generation_timeout_does_not_retry_same_official_model():
    """官方 M3 超时时直接失败，不重复调用同一个模型。"""
    generator = ActiveCareResponseGenerator(settings=object())

    result = await generator._handle_llm_timeout(
        [{"role": "user", "content": "test"}],
        temperature=0.3,
        max_tokens=40,
        model_path=PRIMARY_MODEL,
    )

    assert result["content"] == ""
    assert result["error"] == "llm_timeout"
