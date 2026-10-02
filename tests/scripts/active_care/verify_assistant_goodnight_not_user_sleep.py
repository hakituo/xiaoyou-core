"""验证"助手说晚安"不再被判定为用户入睡（2026-08-16 修复）

背景：
此前 active_care 会把"助手（Aveline/Ling）按作息入睡时发的晚安"通过
extract_latest_assistant_goodnight 检测后强制写入用户睡眠会话（reduced_mode=sleep），
导致 nightly_processor.check_user_sleeping() 误判用户入睡 → 提前生成日记；
peer_chat 的 is_user_sleeping() 也会被误判 → 错误门禁。
而用户实际可能在继续聊天（如 23:10 角色说晚安、23:57 仍在对话，日记却在 23:21 生成）。

修复：移除"助手晚安 → 用户睡眠会话"的整条信号链：
- proactive_checker 不再检测/注入助手晚安；
- _try_enter_goodnight_on_intent 一律以配置开关为准，不再区分是否助手晚安。
用户是否入睡只依据用户真实行为（用户说晚安 / sleep_hint + 沉默）。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_assistant_goodnight_not_user_sleep
"""

import asyncio
import inspect
import sys
import time
from pathlib import Path
from typing import Any, Dict

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


class _FakeStorage:
    """记录 save_proactive_state 调用的假存储层"""

    def __init__(self):
        self.saved: list = []

    async def save_proactive_state(self, updates: Dict, immediate: bool = False) -> Dict:
        self.saved.append(dict(updates))
        return dict(updates)


def _make_manager(config_values: Dict[str, Any]) -> tuple:
    """构造一个只依赖 config 回调的 SleepSessionManager 实例"""
    from core.services.active_care.core.sleep_session_manager import SleepSessionManager

    storage = _FakeStorage()

    def get_config_value(attr: str, default: Any) -> Any:
        return config_values.get(attr, default)

    manager = SleepSessionManager(
        intent_detector=None,
        sleep_policy=None,
        storage=storage,
        get_config_value=get_config_value,
        checker=None,
    )
    return manager, storage


def test_proactive_checker_no_assistant_goodnight_injection():
    """测试1: proactive_checker 不应再把助手晚安注入为用户入睡信号"""
    from core.services.active_care.core import proactive_checker

    source = inspect.getsource(proactive_checker)
    # 代码行中（去掉注释）不应再调用 extract_latest_assistant_goodnight 或设置 is_assistant_goodnight
    code_lines = [ln for ln in source.split("\n") if not ln.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    assert "extract_latest_assistant_goodnight" not in code_text, \
        "proactive_checker 代码中不应再调用 extract_latest_assistant_goodnight"
    assert "is_assistant_goodnight = True" not in code_text, \
        "proactive_checker 不应再设置 is_assistant_goodnight = True"
    print("[OK] 测试1 (proactive_checker 不再注入助手晚安为用户入睡信号)")


def test_enter_goodnight_no_assistant_bypass():
    """测试2: _try_enter_goodnight_on_intent 不再有"助手晚安绕过配置"分支"""
    from core.services.active_care.core.sleep_session_manager import SleepSessionManager

    method = getattr(SleepSessionManager, "_try_enter_goodnight_on_intent", None)
    assert method is not None, "_try_enter_goodnight_on_intent 方法应存在"
    source = inspect.getsource(method)
    assert "if not is_assistant_goodnight:" not in source, \
        "_try_enter_goodnight_on_intent 不应再有 is_assistant_goodnight 绕过配置的分支"
    assert "enable_auto_goodnight_reduced_mode" in source, \
        "_try_enter_goodnight_on_intent 应一律检查 enable_auto_goodnight_reduced_mode 配置"
    print("[OK] 测试2 (_try_enter_goodnight_on_intent 一律受配置开关控制)")


def test_config_disabled_no_entry_even_for_assistant_goodnight():
    """测试3: 配置关闭时，即便传入 is_assistant_goodnight=True 也不进入睡眠会话

    这是本次修复的核心：助手晚安不再能强制写入用户睡眠会话。
    """
    async def _run():
        manager, storage = _make_manager(
            {"active_care_enable_auto_goodnight_reduced_mode": False}
        )
        now = time.time()
        state_data = {"some_key": "value"}
        result = await manager._try_enter_goodnight_on_intent(
            now, dict(state_data),
            inferred_goodnight=True, inferred_goodmorning=False,
            inferred_ts=now - 10, is_assistant_goodnight=True,
        )
        assert result == state_data, "配置关闭时不应修改状态"
        assert not storage.saved, "配置关闭时不应调用 save_proactive_state"
        print("[OK] 测试3 (配置关闭 + 助手晚安标记 → 不进入睡眠会话)")

    asyncio.run(_run())


def test_config_enabled_user_goodnight_still_enters():
    """测试4: 配置开启 + 用户真实晚安（inferred_goodnight）→ 仍正常进入睡眠会话

    回归保护：不能因为修复而破坏"用户真的说晚安"这一正常触发路径。
    """
    async def _run():
        manager, storage = _make_manager(
            {"active_care_enable_auto_goodnight_reduced_mode": True}
        )
        now = time.time()
        result = await manager._try_enter_goodnight_on_intent(
            now, {"some_key": "value"},
            inferred_goodnight=True, inferred_goodmorning=False,
            inferred_ts=now - 10, is_assistant_goodnight=False,
        )
        assert storage.saved, "配置开启且用户说晚安时应进入睡眠会话"
        assert result.get("reduced_mode_active") is True, \
            "应写入 reduced_mode_active=True"
        assert result.get("reduced_mode_label") == "sleep", \
            "reduced_mode_label 应为 sleep"
        assert result.get("reduced_mode_reason") == "goodnight", \
            "reduced_mode_reason 应为 goodnight"
        print("[OK] 测试4 (配置开启 + 用户真实晚安 → 正常进入睡眠会话)")

    asyncio.run(_run())


def test_user_goodmorning_blocks_entry():
    """测试5: 配置开启 + 检测到早安 → 不进入睡眠会话（不应覆盖清醒状态）"""
    async def _run():
        manager, storage = _make_manager(
            {"active_care_enable_auto_goodnight_reduced_mode": True}
        )
        now = time.time()
        await manager._try_enter_goodnight_on_intent(
            now, {"some_key": "value"},
            inferred_goodnight=True, inferred_goodmorning=True,
            inferred_ts=now - 10, is_assistant_goodnight=False,
        )
        assert not storage.saved, "检测到早安时不应进入睡眠会话"
        print("[OK] 测试5 (早安信号阻止进入睡眠会话)")

    asyncio.run(_run())


def test_all_modified_modules_importable():
    """测试6: 所有修改过的模块应能正常导入"""
    from core.services.active_care.core import proactive_checker
    from core.services.active_care.core import sleep_session_manager
    from core.services.active_care import goodnight_proactive
    from core.services.life_simulation import sleep_manager

    modules = (proactive_checker, sleep_session_manager, goodnight_proactive, sleep_manager)
    assert all(m is not None for m in modules), "修改过的模块应能正常导入"
    print("[OK] 测试6 (修改过的模块均可正常导入)")


def main() -> int:
    tests = [
        test_proactive_checker_no_assistant_goodnight_injection,
        test_enter_goodnight_no_assistant_bypass,
        test_config_disabled_no_entry_even_for_assistant_goodnight,
        test_config_enabled_user_goodnight_still_enters,
        test_user_goodmorning_blocks_entry,
        test_all_modified_modules_importable,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - 汇总所有异常
            failed += 1
            print(f"[ERROR] {t.__name__}: {e!r}")
    print("-" * 60)
    if failed:
        print(f"验证失败：{failed}/{len(tests)} 项未通过")
        return 1
    print(f"验证通过：{len(tests)}/{len(tests)} 项全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
