"""Active Care 手动强制发送路由测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from routers.v1.system import force_send_active_care


@pytest.mark.asyncio
async def test_force_send_passes_explicit_persona_and_reports_delivery():
    """真实回归入口必须把目标 persona 传给执行器并返回实际投递结果。"""
    executor = SimpleNamespace(
        trigger_message=AsyncMock(return_value=True),
    )
    service = SimpleNamespace(
        executor=executor,
        get_runtime_status=lambda: {"running": True},
    )

    with patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=service,
    ):
        result = await force_send_active_care(
            {
                "prompt_type": "checking",
                "user_input_mock": "[ACTIVE_CARE_TRIGGER]",
                "client_type": "qq",
                "persona_filename": "core_ye.json",
            }
        )

    executor.trigger_message.assert_awaited_once()
    assert (
        executor.trigger_message.await_args.kwargs["persona_filename"]
        == "core_ye.json"
    )
    assert result["status"] == "success"
    assert result["data"]["delivered"] is True
    assert result["data"]["persona_filename"] == "core_ye.json"
