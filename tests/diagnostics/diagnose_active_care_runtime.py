#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Active Care 运行时诊断脚本

通过 API 接口检查 Active Care 的运行状态，找出不发消息的原因。
"""
import sys
import os
import json
import time

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

PASS = 0
FAIL = 0
WARN = 0


def _pass(msg: str):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def _fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def _warn(msg: str):
    global WARN
    WARN += 1
    print(f"  ⚠️  {msg}")


def check_active_care_service_singleton():
    """检查 Active Care 服务单例状态"""
    print("\n[1] Active Care 服务单例检查")

    try:
        from core.services.active_care.core.service import get_active_care_service, _active_care_service

        service = get_active_care_service()
        if service is None:
            _fail("get_active_care_service() 返回 None")
            return None

        _pass(f"服务单例存在: {type(service).__name__}")

        print(f"    _enable_proactive_checker = {service._enable_proactive_checker}")
        print(f"    checker = {service.checker}")
        print(f"    _running = {service._running}")
        print(f"    last_intent = {service.last_intent}")
        print(f"    consecutive_non_responses = {service.consecutive_non_responses}")

        if service._enable_proactive_checker:
            _pass("enable_proactive_checker = True")
        else:
            _fail("enable_proactive_checker = False（ProactiveChecker 不会工作！）")

        if service.checker is not None:
            _pass("ProactiveChecker 已创建")
        else:
            _fail("ProactiveChecker 为 None（主动消息管道完全瘫痪！）")

        if service._running:
            _pass("服务正在运行")
        else:
            _warn("服务未运行（可能尚未初始化）")

        return service
    except Exception as e:
        _fail(f"导入或检查失败: {e}")
        return None


def check_proactive_checker_state(service):
    """检查 ProactiveChecker 状态"""
    print("\n[2] ProactiveChecker 状态检查")

    if service is None or service.checker is None:
        _fail("ProactiveChecker 不存在，跳过检查")
        return

    checker = service.checker
    now = time.time()

    print(f"    next_decision_ts = {checker.next_decision_ts}")
    print(f"    next_decision_in = {max(0, int(checker.next_decision_ts - now))}s")
    print(f"    last_skip_reason = {getattr(checker, 'last_skip_reason', 'N/A')}")
    print(f"    last_check_phase = {getattr(checker, 'last_check_phase', 'N/A')}")
    print(f"    last_intent = {getattr(checker, 'last_intent', 'N/A')}")

    next_in = max(0, checker.next_decision_ts - now)
    if next_in > 3600:
        _warn(f"下次决策在 {int(next_in)}s 后（超过1小时，可能被过度退避）")
    elif next_in > 0:
        _pass(f"下次决策在 {int(next_in)}s 后")
    else:
        _pass("下次决策已到期，应该立即执行")


def check_proactive_state_storage(service):
    """检查持久化状态"""
    print("\n[3] 持久化状态检查")

    if service is None:
        _fail("服务不存在，跳过")
        return

    try:
        import asyncio

        async def _check():
            state = await service.storage.get_proactive_state()
            return state

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    state = pool.submit(asyncio.run, _check()).result()
            else:
                state = loop.run_until_complete(_check())
        except RuntimeError:
            state = asyncio.run(_check())

        now = time.time()

        last_sent_ts = float(state.get("last_sent_ts") or 0.0)
        last_user_ts = float(state.get("last_user_interaction_ts") or 0.0)
        reduced_mode = bool(state.get("reduced_mode_active"))
        reduced_reason = str(state.get("reduced_mode_reason") or "")
        last_goodnight_ts = float(state.get("last_goodnight_ts") or 0.0)
        last_goodmorning_ts = float(state.get("last_goodmorning_ts") or 0.0)
        consecutive_non_responses = int(state.get("consecutive_non_responses") or 0)

        print(f"    last_sent_ts = {last_sent_ts} ({int(now - last_sent_ts)}s 前)" if last_sent_ts > 0 else "    last_sent_ts = 0 (从未发送)")
        print(f"    last_user_interaction_ts = {last_user_ts} ({int(now - last_user_ts)}s 前)" if last_user_ts > 0 else "    last_user_interaction_ts = 0 (无记录)")
        print(f"    reduced_mode_active = {reduced_mode}")
        print(f"    reduced_mode_reason = {reduced_reason}")
        print(f"    last_goodnight_ts = {last_goodnight_ts}")
        print(f"    last_goodmorning_ts = {last_goodmorning_ts}")
        print(f"    consecutive_non_responses = {consecutive_non_responses}")

        if last_sent_ts > 0:
            elapsed_since_sent = now - last_sent_ts
            if elapsed_since_sent > 7200:
                _warn(f"距上次发送已过 {int(elapsed_since_sent)}s（超过2小时）")
            else:
                _pass(f"距上次发送 {int(elapsed_since_sent)}s")
        else:
            _warn("从未发送过主动消息")

        if reduced_mode:
            _warn(f"减少模式激活: {reduced_reason}（可能阻止发送）")

        if consecutive_non_responses > 2:
            _warn(f"连续无响应次数: {consecutive_non_responses}（退避系数: {1.35 ** consecutive_non_responses:.2f}x）")

        sleep_session = last_goodnight_ts > 0 and last_goodmorning_ts < last_goodnight_ts
        if sleep_session:
            _warn("睡眠会话激活中（可能阻止发送）")

    except Exception as e:
        _fail(f"读取持久化状态失败: {e}")


def check_config_values(service):
    """检查关键配置值"""
    print("\n[4] 关键配置值检查")

    if service is None:
        _fail("服务不存在，跳过")
        return

    try:
        from core.utils.config_accessor import get_active_care_config
        from config.integrated_config import get_settings

        settings = get_settings()

        configs = {
            "active_care_enabled": get_active_care_config("active_care_enabled", default=True, settings=settings),
            "active_care_min_gap_seconds": get_active_care_config("active_care_min_gap_seconds", default=600, settings=settings),
            "active_care_require_active_client": get_active_care_config("active_care_require_active_client", default=True, settings=settings),
            "active_care_default_next_check_seconds": get_active_care_config("active_care_default_next_check_seconds", default=300, settings=settings),
            "active_care_daily_limit": get_active_care_config("active_care_daily_limit", default=20, settings=settings),
            "active_care_user_quiet_seconds": get_active_care_config("active_care_user_quiet_seconds", default=300, settings=settings),
            "active_care_focus_user_quiet_seconds": get_active_care_config("active_care_focus_user_quiet_seconds", default=1800, settings=settings),
            "active_care_focus_low_disturb_gap_seconds": get_active_care_config("active_care_focus_low_disturb_gap_seconds", default=7200, settings=settings),
        }

        for key, value in configs.items():
            print(f"    {key} = {value}")

        if not configs["active_care_enabled"]:
            _fail("active_care_enabled = False（Active Care 被禁用！）")
        else:
            _pass("active_care_enabled = True")

        if configs["active_care_require_active_client"]:
            _warn("active_care_require_active_client = True（无客户端时不会发送）")
        else:
            _pass("active_care_require_active_client = False（即使无客户端也会发送）")

        min_gap = int(configs["active_care_min_gap_seconds"] or 600)
        if min_gap > 900:
            _warn(f"min_gap_seconds = {min_gap}s（超过15分钟，可能过长）")
        else:
            _pass(f"min_gap_seconds = {min_gap}s")

    except Exception as e:
        _fail(f"读取配置失败: {e}")


def check_client_status(service):
    """检查客户端连接状态"""
    print("\n[5] 客户端连接状态检查")

    if service is None:
        _fail("服务不存在，跳过")
        return

    try:
        from core.utils.client_utils import has_active_client
        active = has_active_client()
        if active:
            _pass("有活跃客户端连接")
        else:
            _warn("无活跃客户端连接（require_active_client=True 时不会发送）")
    except Exception as e:
        _warn(f"检查客户端状态失败: {e}")


def check_runtime_status(service):
    """检查 get_runtime_status 返回值"""
    print("\n[6] get_runtime_status 检查")

    if service is None:
        _fail("服务不存在，跳过")
        return

    try:
        status = service.get_runtime_status()
        print(f"    {json.dumps(status, indent=2, ensure_ascii=False, default=str)}")

        if not status.get("running"):
            _fail("服务未运行")
        else:
            _pass("服务正在运行")

        if not status.get("checker_enabled"):
            _fail("checker_enabled = False")
        else:
            _pass("checker_enabled = True")

        if status.get("last_skip_reason") and status["last_skip_reason"] not in ("none", "decision_executed"):
            _warn(f"上次跳过原因: {status['last_skip_reason']}")

    except Exception as e:
        _fail(f"get_runtime_status 失败: {e}")


def check_proactive_loop_task(service):
    """检查主动循环任务状态"""
    print("\n[7] 主动循环任务状态检查")

    if service is None:
        _fail("服务不存在，跳过")
        return

    try:
        proactive_task = getattr(service, "_proactive_task", None)
        startup_task = getattr(service, "_startup_task", None)
        maintenance_task = getattr(service, "_maintenance_task", None)

        if proactive_task is not None and not proactive_task.done():
            _pass("主动循环任务正在运行")
        elif proactive_task is not None and proactive_task.done():
            _fail("主动循环任务已完成（应该持续运行）")
            try:
                exc = proactive_task.exception()
                if exc:
                    _fail(f"主动循环任务异常: {exc}")
            except (asyncio.InvalidStateError, asyncio.CancelledError):
                pass
        else:
            _fail("主动循环任务未创建")

        if startup_task is not None:
            if startup_task.done():
                _pass("启动检查任务已完成")
            else:
                _warn("启动检查任务仍在运行")

        if maintenance_task is not None and not maintenance_task.done():
            _pass("维护循环任务正在运行")
        else:
            _warn("维护循环任务未运行")

    except Exception as e:
        _warn(f"检查任务状态失败: {e}")


def main():
    print("=" * 60)
    print("Active Care 运行时诊断脚本")
    print("=" * 60)

    service = check_active_care_service_singleton()
    check_proactive_checker_state(service)
    check_proactive_state_storage(service)
    check_config_values(service)
    check_client_status(service)
    check_runtime_status(service)
    check_proactive_loop_task(service)

    print("\n" + "=" * 60)
    total = PASS + FAIL + WARN
    print(f"结果: ✅ {PASS} 通过, ❌ {FAIL} 失败, ⚠️ {WARN} 警告")
    print("=" * 60)

    if FAIL > 0:
        print("\n🚨 发现关键问题！Active Care 可能无法正常发送消息。")
        print("   最可能的原因：")
        print("   1. enable_proactive_checker 未启用（单例竞态条件）")
        print("   2. 无活跃客户端（require_active_client=True）")
        print("   3. 睡眠会话或专注模式阻止发送")
        print("   4. 连续无响应退避过长")
        sys.exit(1)
    elif WARN > 0:
        print("\n⚠️  存在警告，Active Care 可能间歇性不发送消息。")
        sys.exit(0)
    else:
        print("\n🎉 所有检查通过！Active Care 应该正常工作。")
        sys.exit(0)


if __name__ == "__main__":
    main()
