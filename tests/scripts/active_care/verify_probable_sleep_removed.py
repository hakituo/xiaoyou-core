"""验证 probable_sleep 机制已彻底移除（2026-07-30）

背景：
probable_sleep 是基于"用户长时间无响应"推断入睡的机制，会覆盖 UIE 正确记录的
作息数据。已于 2026-07-30 彻底移除，夜间降频现在依赖 goodnight/sleep_hint。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_probable_sleep_removed
"""

import asyncio
import inspect

import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def test_no_probable_sleep_reason_constant():
    """测试1: constants.py 中不应再有 PROBABLE_SLEEP_REASON 常量"""
    from core.services.active_care.shared import constants
    assert not hasattr(constants, "PROBABLE_SLEEP_REASON"), \
        "constants.py 中仍存在 PROBABLE_SLEEP_REASON 常量"
    print("[OK] 测试1 (PROBABLE_SLEEP_REASON 常量已移除)")


def test_no_probable_sleep_reduced_mode_instruction_import():
    """测试2: 不应再能 import PROBABLE_SLEEP_REDUCED_MODE_INSTRUCTION"""
    from core.services.active_care.shared import constants
    assert not hasattr(constants, "PROBABLE_SLEEP_REDUCED_MODE_INSTRUCTION"), \
        "constants.py 仍导出 PROBABLE_SLEEP_REDUCED_MODE_INSTRUCTION"
    print("[OK] 测试2 (PROBABLE_SLEEP_REDUCED_MODE_INSTRUCTION 已移除)")


def test_sync_probable_sleep_to_daily_record_removed():
    """测试3: SleepSessionManager 不应再有 _sync_probable_sleep_to_daily_record 方法"""
    from core.services.active_care.core.sleep_session_manager import SleepSessionManager
    assert not hasattr(SleepSessionManager, "_sync_probable_sleep_to_daily_record"), \
        "SleepSessionManager 仍存在 _sync_probable_sleep_to_daily_record 方法"
    print("[OK] 测试3 (_sync_probable_sleep_to_daily_record 方法已移除)")


def test_startup_infer_sleep_from_gap_removed():
    """测试4: StartupHandler 不应再有 startup_infer_sleep_from_gap 方法"""
    from core.services.active_care.core.startup_handler import StartupHandler
    assert not hasattr(StartupHandler, "startup_infer_sleep_from_gap"), \
        "StartupHandler 仍存在 startup_infer_sleep_from_gap 方法"
    print("[OK] 测试4 (startup_infer_sleep_from_gap 方法已移除)")


def test_try_infer_probable_sleep_only_handles_sleep_hint():
    """测试5: _try_infer_probable_sleep 方法保留但只处理 sleep_hint

    方法名保留以兼容调用签名，但不再进入 probable_sleep 模式。
    """
    from core.services.active_care.core.sleep_session_manager import SleepSessionManager
    method = getattr(SleepSessionManager, "_try_infer_probable_sleep", None)
    assert method is not None, "_try_infer_probable_sleep 方法应保留（兼容调用签名）"

    # 检查方法源码不应包含 PROBABLE_SLEEP_REASON 或进入 probable_sleep 模式的逻辑
    source = inspect.getsource(method)
    assert "PROBABLE_SLEEP_REASON" not in source, \
        "_try_infer_probable_sleep 源码不应再引用 PROBABLE_SLEEP_REASON"
    assert '"probable_sleep"' not in source, \
        "_try_infer_probable_sleep 源码不应再包含 'probable_sleep' 字符串字面量"
    assert "SLEEP_HINT_REASON" in source, \
        "_try_infer_probable_sleep 源码应保留 SLEEP_HINT_REASON 处理"
    print("[OK] 测试5 (_try_infer_probable_sleep 只处理 sleep_hint)")


def test_user_response_handler_no_probable_sleep_branch():
    """测试6: user_response_handler 不应再有 probable_sleep 分支"""
    from core.services.active_care.core import user_response_handler
    source = inspect.getsource(user_response_handler)
    # 允许出现在注释中，但不允许在条件判断中
    assert '"probable_sleep"' not in source or \
           source.count('"probable_sleep"') == source.count("# probable_sleep"), \
        "user_response_handler 不应再有 probable_sleep 条件分支（注释除外）"
    print("[OK] 测试6 (user_response_handler 无 probable_sleep 条件分支)")


def test_action_builder_no_probable_sleep():
    """测试7: action_builder 不应再有 probable_sleep 条件分支"""
    from core.services.active_care.decision import action_builder
    source = inspect.getsource(action_builder)
    # 统计非注释行的 probable_sleep 引用
    code_lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert '"probable_sleep"' not in code_text, \
        "action_builder 代码中不应再有 'probable_sleep' 字符串字面量"
    print("[OK] 测试7 (action_builder 无 probable_sleep 条件分支)")


def test_decision_no_probable_sleep():
    """测试8: decision.py 不应再有 probable_sleep 条件分支"""
    from core.services.active_care.decision import decision
    source = inspect.getsource(decision)
    code_lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert '"probable_sleep"' not in code_text, \
        "decision.py 代码中不应再有 'probable_sleep' 字符串字面量"
    print("[OK] 测试8 (decision.py 无 probable_sleep 条件分支)")


def test_all_modules_importable():
    """测试9: 所有修改过的模块应能正常导入"""
    import core.services.active_care.core.sleep_session_manager
    import core.services.active_care.core.startup_handler
    import core.services.active_care.core.user_response_handler
    import core.services.active_care.decision.action_builder
    import core.services.active_care.decision.decision
    import core.services.active_care.core.sleep_policy
    import core.services.active_care.detection.gate_scorer
    import core.services.active_care.peer_chat.peer_chat_scheduler
    import core.services.life_simulation.service_state_helpers
    import core.services.active_care.checker.sleep_session_compat
    import core.services.active_care.shared.constants
    import core.services.active_care.prompt.prompt_context_builders
    import core.services.active_care.checker.checker_event_handler
    import core.services.active_care.core.proactive_checker
    print("[OK] 测试9 (所有模块导入正常)")


def test_sleep_hint_still_works():
    """测试10: sleep_hint 机制应保留且正常工作

    sleep_hint（用户暗示"不回就是睡了"）有用户明确意图支撑，应保留。
    """
    from core.services.active_care.shared.constants import SLEEP_HINT_REASON
    assert SLEEP_HINT_REASON == "sleep_hint", \
        f"SLEEP_HINT_REASON 应为 'sleep_hint', 但得到: {SLEEP_HINT_REASON!r}"
    print("[OK] 测试10 (sleep_hint 机制保留)")


def test_goodnight_still_works():
    """测试11: goodnight 机制应保留且正常工作"""
    from core.services.active_care.shared.constants import build_quiet_mode_instruction
    # goodnight 分支应返回非空指令
    result = build_quiet_mode_instruction(
        quiet_mode_active=False,
        reduced_mode_active=True,
        reduced_mode_reason="goodnight",
    )
    assert result, f"goodnight 模式应返回非空指令, 但得到: {result!r}"
    print("[OK] 测试11 (goodnight 机制保留)")


def test_sync_sleep_to_daily_record_still_exists():
    """测试12: sync_sleep_to_daily_record 函数应保留（goodnight 退出时仍需调用）"""
    from core.services.active_care.shared.constants import sync_sleep_to_daily_record
    assert callable(sync_sleep_to_daily_record), \
        "sync_sleep_to_daily_record 函数应保留供 goodnight 使用"
    print("[OK] 测试12 (sync_sleep_to_daily_record 函数保留供 goodnight 使用)")


def test_peer_chat_scheduler_no_probable_sleep():
    """测试13: peer_chat_scheduler 的 is_user_sleeping 不应再检查 probable_sleep"""
    from core.services.active_care.peer_chat.peer_chat_scheduler import PeerChatScheduler
    source = inspect.getsource(PeerChatScheduler.is_user_sleeping)
    code_lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert '"probable_sleep"' not in code_text, \
        "is_user_sleeping 不应再检查 probable_sleep"
    assert "sleep_hint" in code_text, \
        "is_user_sleeping 应保留 sleep_hint 检查"
    print("[OK] 测试13 (peer_chat_scheduler 无 probable_sleep)")


def test_service_state_helpers_no_probable_sleep():
    """测试14: service_state_helpers 不应再检查 probable_sleep"""
    from core.services.life_simulation import service_state_helpers
    source = inspect.getsource(service_state_helpers)
    code_lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert '"probable_sleep"' not in code_text, \
        "service_state_helpers 不应再检查 probable_sleep"
    print("[OK] 测试14 (service_state_helpers 无 probable_sleep)")


def main():
    print("=" * 60)
    print("probable_sleep 机制移除验证（2026-07-30）")
    print("=" * 60)
    test_no_probable_sleep_reason_constant()
    test_no_probable_sleep_reduced_mode_instruction_import()
    test_sync_probable_sleep_to_daily_record_removed()
    test_startup_infer_sleep_from_gap_removed()
    test_try_infer_probable_sleep_only_handles_sleep_hint()
    test_user_response_handler_no_probable_sleep_branch()
    test_action_builder_no_probable_sleep()
    test_decision_no_probable_sleep()
    test_all_modules_importable()
    test_sleep_hint_still_works()
    test_goodnight_still_works()
    test_sync_sleep_to_daily_record_still_exists()
    test_peer_chat_scheduler_no_probable_sleep()
    test_service_state_helpers_no_probable_sleep()
    print("=" * 60)
    print("全部 14 个测试通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
