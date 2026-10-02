r"""验证数字健康超限关怀的两层抑制：冷却落盘 + 对话中不打扰。

背景：
- 冷却原本是类属性（纯内存），dev reload / 进程重启后清零，
  导致 Android 每 15 分钟同步一次就重发一条（实测同一「哔哩哔哩」15 分钟内连发两条）。
- 数字健康是硬事件直通 executor.trigger_message，绕过了 MDP/checker，
  缺 active care 主循环里那层「用户刚说过话就别插嘴」的门控。

运行：
    D:\projects\xiaoyou\venv_core\Scripts\python.exe -m tests.scripts.active_care.verify_digital_wellbeing_care_throttle
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

_FAILED: list[str] = []


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    print(f"  [FAIL] {msg}" + (f" -> {detail}" if detail else ""))
    _FAILED.append(msg)


def _new_service(tmpdir: Path):
    from core.services.digital_wellbeing.service import DigitalWellbeingService

    svc = DigitalWellbeingService(base_dir=tmpdir / "digital_wellbeing")
    # 固定一个超限应用，避开真实用量读盘
    svc.get_exceeded_apps = lambda **kwargs: [
        {
            "package_name": "com.bilibili.app.in",
            "app_name": "哔哩哔哩",
            "limit_ms": 3_600_000,
            "usage_ms": 7_200_000,
            "ratio": 2.0,
            # Android 端上报的是 Instant.toString()，形如 2026-08-14T12:34:56.789Z
            "last_used_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    ]
    return svc


def _fake_executor():
    """假的 active care executor，记录是否真的触发了发送。"""
    calls: list[str] = []

    async def _trigger(**kwargs):
        calls.append(kwargs.get("sys_prompt_type", ""))
        return True

    return calls, AsyncMock(side_effect=_trigger)


def test_cooldown_survives_new_instance() -> None:
    print("\n=== 测试 1: 冷却落盘，重建实例/重启后仍生效 ===")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        svc = _new_service(tmpdir)
        calls, executor = _fake_executor()

        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor, "storage": None})()
            first = asyncio.run(svc.maybe_notify_exceeded_via_active_care(target_date="2026-09-19"))

        if first == ["哔哩哔哩"]:
            _ok("首次超限发送关怀")
        else:
            _fail("首次未发送关怀", str(first))

        # 换一个全新实例（等价于进程重启），冷却必须仍然生效
        svc2 = _new_service(tmpdir)
        calls2, executor2 = _fake_executor()
        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor2, "storage": None})()
            second = asyncio.run(
                svc2.maybe_notify_exceeded_via_active_care(target_date="2026-09-19")
            )

        if second == []:
            _ok("重建实例后冷却仍然拦住（状态来自磁盘）")
        else:
            _fail("重启后冷却失效，会重复打扰", str(second))

        state_file = tmpdir / "digital_wellbeing" / "care_state_2026-09-19.json"
        if state_file.exists():
            _ok(f"冷却记录已落盘 {state_file.name}")
        else:
            _fail("冷却记录未落盘")


def test_skip_while_user_is_chatting() -> None:
    print("\n=== 测试 2: 用户刚在对话里发言 -> 跳过关怀 ===")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        svc = _new_service(tmpdir)
        calls, executor = _fake_executor()

        storage = type(
            "St",
            (),
            {
                "get_proactive_state": AsyncMock(
                    return_value={"last_user_interaction_ts": time.time() - 60}
                )
            },
        )()

        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor, "storage": storage})()
            notified = asyncio.run(
                svc.maybe_notify_exceeded_via_active_care(target_date="2026-09-19")
            )

        if notified == []:
            _ok("用户 60s 前刚发言 -> 未插播关怀")
        else:
            _fail("对话中仍然插播了关怀", str(notified))

        if calls == []:
            _ok("未触发 executor.trigger_message")
        else:
            _fail("仍触发了发送", str(calls))


def test_send_after_chat_went_quiet() -> None:
    print("\n=== 测试 3: 对话已安静超过静默窗口 -> 正常发送 ===")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        svc = _new_service(tmpdir)
        calls, executor = _fake_executor()

        quiet_seconds = svc._chat_quiet_seconds()
        storage = type(
            "St",
            (),
            {
                "get_proactive_state": AsyncMock(
                    return_value={"last_user_interaction_ts": time.time() - quiet_seconds - 120}
                )
            },
        )()

        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor, "storage": storage})()
            notified = asyncio.run(
                svc.maybe_notify_exceeded_via_active_care(target_date="2026-09-19")
            )

        if notified == ["哔哩哔哩"]:
            _ok(f"静默窗口 {quiet_seconds}s 已过 -> 正常发送")
        else:
            _fail("静默窗口过后仍被拦住", str(notified))


def test_one_message_per_sync() -> None:
    print("\n=== 测试 4: 多个应用同时超限 -> 一次同步只发一条（挑最过分的） ===")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        svc = _new_service(tmpdir)
        # 抖音超 3 倍、B站超 2 倍：应该只提醒抖音
        svc.get_exceeded_apps = lambda **kwargs: [
            {
                "package_name": "com.bilibili.app.in",
                "app_name": "哔哩哔哩",
                "limit_ms": 3_600_000,
                "usage_ms": 7_200_000,
                "ratio": 2.0,
                "last_used_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            {
                "package_name": "com.ss.android.ugc.aweme",
                "app_name": "抖音",
                "limit_ms": 3_600_000,
                "usage_ms": 10_800_000,
                "ratio": 3.0,
                "last_used_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        ]
        calls, executor = _fake_executor()
        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor, "storage": None})()
            notified = asyncio.run(
                svc.maybe_notify_exceeded_via_active_care(target_date="2026-09-19")
            )

        if notified == ["抖音"]:
            _ok("一次同步只发一条，且选中超限比例最高的抖音")
        else:
            _fail("一次同步发了多条或挑错了应用", str(notified))


def test_global_gap_across_apps() -> None:
    print("\n=== 测试 5: 全局节流 -> 换一个应用也不会紧接着再来一条 ===")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        svc = _new_service(tmpdir)
        calls, executor = _fake_executor()
        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor, "storage": None})()
            asyncio.run(svc.maybe_notify_exceeded_via_active_care(target_date="2026-09-19"))

        # 换成另一个应用，且它自己没有冷却记录
        svc2 = _new_service(tmpdir)
        svc2.get_exceeded_apps = lambda **kwargs: [
            {
                "package_name": "com.ss.android.ugc.aweme",
                "app_name": "抖音",
                "limit_ms": 3_600_000,
                "usage_ms": 10_800_000,
                "ratio": 3.0,
                "last_used_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        ]
        calls2, executor2 = _fake_executor()
        with patch("core.services.active_care.core.service.get_active_care_service") as get_svc:
            get_svc.return_value = type("S", (), {"executor": executor2, "storage": None})()
            second = asyncio.run(
                svc2.maybe_notify_exceeded_via_active_care(target_date="2026-09-19")
            )

        if second == []:
            _ok(f"全局节流（{svc2._CARE_GLOBAL_GAP_SECONDS}s）拦住了跨应用的连发")
        else:
            _fail("换个应用仍能紧接着再发一条", str(second))


def main() -> int:
    print("=" * 64)
    print("数字健康超限关怀：冷却落盘 + 对话中不打扰 验证")
    print("=" * 64)
    test_cooldown_survives_new_instance()
    test_skip_while_user_is_chatting()
    test_send_after_chat_went_quiet()
    test_one_message_per_sync()
    test_global_gap_across_apps()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项：" + "、".join(_FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
