"""验证「缺少明确时间的作息修正」不会再伪造当前时间（2026-09-18 事故回归）。

事故
----
用户对角色说：「？那是睡觉的时间不是起床的时间」。
这句话含「不是」→ 命中 ``has_correction_intent``；BERT 判成 CORRECT_WAKEUP；
但句子里没有任何时间，旧实现把 ``None`` 传进 ``record_wakeup``，
而 ``record_wakeup`` 会用「当前时间」兜底，于是当天日记录被写成
``wakeup=01:19（user_manual）``——user_manual 是最高优先级，三星健康和聊天推断
都盖不掉，角色随后一直照着这条假数据说「你 01:19 才醒」。

本脚本检查：
1. 无明确时间的修正语句（fast 路径 / 语义意图路径）都不落库；
2. 否定语境里出现的时间（「我不是 23:30 睡的」）同样不落库；
3. 有明确时间的正常修正仍然生效（不误伤）。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.daily.verify_sleep_correction_guard
"""

import shutil
import tempfile

from core.services.daily import correction
from core.services.daily.manager import DailyActivityManager
from core.utils.singleton import SingletonFactory
from core.utils.time_utils import today_str

# 事故原句：含修正词「不是」，但整句没有任何时间
_ACCIDENT_TEXT = "？那是睡觉的时间不是起床的时间"

_FIELDS = ("sleep", "wakeup", "sleep_source", "wakeup_source")


def _sleep_cycle_snapshot(manager: DailyActivityManager) -> dict:
    sc = manager.get_record(today_str())["sleep_cycle"]
    return {key: sc.get(key) for key in _FIELDS}


def main() -> None:
    temp_dir = tempfile.mkdtemp(prefix="sleep_correction_guard_")
    manager = DailyActivityManager()
    manager.root_dir = temp_dir
    # 不触碰真实 Active Care 状态（correction 内部会同步作息到那边）
    original_wakeup_sync = correction._sync_wakeup_to_active_care
    original_sleep_sync = correction._sync_sleep_to_active_care
    correction._sync_wakeup_to_active_care = lambda *args, **kwargs: None
    correction._sync_sleep_to_active_care = lambda *args, **kwargs: None
    try:
        before = _sleep_cycle_snapshot(manager)

        # 1) fast 路径：不带时间的修正语句不得写库
        assert correction.apply_fast_correction(_ACCIDENT_TEXT, manager) is False
        assert _sleep_cycle_snapshot(manager) == before, "fast 路径不应写入作息"

        # 2) 语义意图路径：同样不得写库
        assert (
            correction._apply_correction_by_intent(
                _ACCIDENT_TEXT, manager, "CORRECT_WAKEUP"
            )
            is False
        )
        assert (
            correction._apply_correction_by_intent(
                _ACCIDENT_TEXT, manager, "CORRECT_SLEEP"
            )
            is False
        )
        assert _sleep_cycle_snapshot(manager) == before, "语义意图路径不应写入作息"

        # 3) 否定语境里出现的时间同样不能落库（「我不是 23:30 睡的」）
        #    那个时间是用户在否认记录，不是要改成的新值。
        assert correction.apply_fast_correction("我不是 23:30 睡的", manager) is False
        assert (
            correction._apply_correction_by_intent(
                "我不是 23:30 睡的", manager, "CORRECT_SLEEP"
            )
            is False
        )
        assert _sleep_cycle_snapshot(manager) == before, "否定语境不应写入作息"

        # 4) 有明确时间的正常修正仍然生效
        assert correction.apply_fast_correction("记错了，我 23:30 睡的", manager) is True
        assert manager.get_record(today_str())["sleep_cycle"]["sleep"] == "23:30"

        assert (
            correction._apply_correction_by_intent(
                "我其实是 08:53 起的", manager, "CORRECT_WAKEUP"
            )
            is True
        )
        sc = manager.get_record(today_str())["sleep_cycle"]
        assert sc["wakeup"] == "08:53", sc
        assert sc["wakeup_source"] == "user_manual", sc

        print("[OK] 无时间的作息修正不再写库（含事故原句）")
        print("[OK] 否定语境里的时间不再落库")
        print("[OK] 有明确时间的正常修正仍然生效")
    finally:
        correction._sync_wakeup_to_active_care = original_wakeup_sync
        correction._sync_sleep_to_active_care = original_sleep_sync
        SingletonFactory._instances = {}
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
