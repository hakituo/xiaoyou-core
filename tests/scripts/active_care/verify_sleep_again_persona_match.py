"""验证半夜睡回去消息的 persona 与 QQ receiver 期望一致，不会再被静默丢弃。

背景：2026-08-03 发现半夜睡回去消息（sleep_again_proactive）后端日志显示
"已实时送达"，但用户实际收不到。根因是 activity_return/instruction.py 的
_ROLE_PERSONA_MAP 错误地映射到 core_aveline.json，导致 executor 构建的
conversation_id 后缀为 __persona__core_aveline，而 QQ receiver 在 dual QQ
模式下校验 persona 后缀是否匹配 adapter 的 persona_filename
（期望 __persona__aveline_qq_master），不匹配则静默丢弃。

修复后验证点：
1. activity_return.instruction.resolve_persona_filename 返回 QQ 人设文件
2. 三个模块（goodnight / good_morning / activity_return）的 persona 映射一致
3. 用 QQ receiver 的 build_persona_conversation_id 构建的 expected_cid
   与 activity_return 产出的 conversation_id 后缀匹配（不会被丢弃）
4. send_activity_return_message 传给 executor 的 persona_filename 是 QQ 人设

运行：D:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_sleep_again_persona_match.py
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 sys.path
_PROJECT_ROOT = "D:\\AI\\xiaoyou-core"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _check_persona_mapping() -> int:
    """验证三个模块的 persona 映射一致且都是 QQ 人设。"""
    _section("1. 三模块 persona 映射一致性")
    from core.services.active_care.goodnight_proactive import (
        _resolve_persona_filename as resolve_gn,
    )
    from core.services.active_care.good_morning_proactive import (
        _resolve_persona_filename as resolve_gm,
    )
    from core.services.character_daily.activity_return.instruction import (
        resolve_persona_filename as resolve_ar,
    )

    fails = 0
    for role, expected in (
        ("aveline", "qq/Aveline_QQ_Master.json"),
        ("ling", "qq/Ling_QQ_Master.json"),
    ):
        gn = resolve_gn(role)
        gm = resolve_gm(role)
        ar = resolve_ar(role)
        if gn == gm == ar == expected:
            print(f"  PASS: {role} → {expected}（三模块一致）")
        else:
            print(f"  FAIL: {role} 三模块不一致: gn={gn!r} gm={gm!r} ar={ar!r} expected={expected!r}")
            fails += 1
    return fails


def _check_receiver_accepts() -> int:
    """验证 QQ receiver 的 build_persona_conversation_id 会接受 activity_return 的 persona。"""
    _section("2. QQ receiver 不会丢弃 activity_return 消息")
    from clients.bots.qq.utils import build_persona_conversation_id
    from core.services.character_daily.activity_return.instruction import (
        resolve_persona_filename,
    )

    fails = 0
    user_id = "private_123456789"
    for role, adapter_persona in (
        ("aveline", "qq/Aveline_QQ_Master.json"),
        ("ling", "qq/Ling_QQ_Master.json"),
    ):
        # activity_return 解析出的 persona（修复后应为 QQ 人设）
        ar_persona = resolve_persona_filename(role)
        # executor 用这个 persona 构建的 conversation_id（即消息携带的 target_id）
        target_cid = build_persona_conversation_id(user_id, ar_persona)
        # QQ receiver 用 adapter 自己的 persona_filename 构建的期望 cid
        expected_cid = build_persona_conversation_id(user_id, adapter_persona)
        if target_cid == expected_cid:
            print(f"  PASS: {role} target={target_cid} == expected={expected_cid}（receiver 接受）")
        else:
            print(f"  FAIL: {role} persona 不匹配会被丢弃: target={target_cid} expected={expected_cid}")
            fails += 1
    return fails


async def _check_send_activity_return_uses_qq_persona() -> int:
    """验证 send_activity_return_message 传给 executor 的是 QQ persona。"""
    _section("3. send_activity_return_message 传 QQ persona 给 executor")

    mock_executor = MagicMock()
    mock_executor.trigger_message = AsyncMock(return_value=True)
    mock_ac = MagicMock()
    mock_ac.executor = mock_executor

    fails = 0
    with patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ):
        from core.services.character_daily.activity_return import (
            send_activity_return_message,
        )
        # 模拟半夜睡回去场景（与 goodnight_proactive is_sleep_again=True 一致）
        result = await send_activity_return_message(
            conversation_id="",
            role_id="aveline",
            activity="sleeping",
            return_type="sleep",
            source="sleep_manager_sleep_again",
            sys_prompt_type="sleep_again_proactive",
            user_input_mock="[CHARACTER_SLEEP_AGAIN]",
            thought="character_aveline_sleep_again_by_recovery",
        )

    if not result.get("delivered"):
        print(f"  FAIL: 未送达 result={result}")
        return 1

    call_kwargs = mock_executor.trigger_message.call_args.kwargs
    persona = call_kwargs.get("persona_filename")
    if persona == "qq/Aveline_QQ_Master.json":
        print(f"  PASS: sleep_again 传 QQ persona={persona}（不会再被 receiver 丢弃）")
    else:
        print(f"  FAIL: sleep_again 传错 persona={persona!r}，应为 qq/Aveline_QQ_Master.json")
        fails += 1

    if call_kwargs.get("client_type") == "qq":
        print(f"  PASS: client_type=qq")
    else:
        print(f"  FAIL: client_type={call_kwargs.get('client_type')!r} 应为 qq")
        fails += 1
    return fails


async def main() -> int:
    print("验证：半夜睡回去消息 persona 与 QQ receiver 匹配（不会再被静默丢弃）")
    print(f"项目根目录: {_PROJECT_ROOT}")

    total = 0
    total += _check_persona_mapping()
    total += _check_receiver_accepts()
    total += await _check_send_activity_return_uses_qq_persona()

    _section("总结")
    if total == 0:
        print("  全部通过——sleep_again 消息不会再被 QQ receiver 因 persona 不匹配而丢弃")
    else:
        print(f"  {total} 项失败")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
