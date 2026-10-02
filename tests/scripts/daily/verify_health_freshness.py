"""验证健康记录的时效标注（2026-09-17 修复）。

修复背景：
- daily_record 的 health 条目只有 symptom / detail / time，但画像渲染时
  只输出症状名、把 time 丢掉了，于是「00:09 记的恶心」到晚上 19:50
  仍被当成「用户现在还难受」，四个角色都据此询问病情。
- 健康症状是瞬时事件，不该被当成一整天的持续状态。

修复内容：
1. `core/services/daily/manager.py` 新增 `split_health_entries()`：
   按 `HEALTH_FRESH_WINDOW_HOURS`（6 小时）把条目拆成「当前」与「较早」，
   两组都补上记录时刻，较早组还标出距现在的小时数。
2. `DailyActivityManager.get_today_summary()` 分别渲染两组，
   并在出现较早记录时附一句「不代表他现在还在难受」的时效说明。
3. `core/services/workspace/snapshot.py::_render_daily_summary()` 复用同一套
   拆分逻辑；渲染历史日期（非当前画像）时关闭时效标注。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.daily.verify_health_freshness
"""

import json
import os
from datetime import datetime
from unittest.mock import patch

from core.services.daily.manager import (
    HEALTH_FRESH_WINDOW_HOURS,
    DailyActivityManager,
    split_health_entries,
)
from core.utils.data_paths import get_user_daily_records_dir
from core.utils.time_utils import today_str


def _make_manager(root_dir):
    with patch(
        "core.services.daily.manager.get_user_daily_records_dir",
        return_value=root_dir,
    ):
        return DailyActivityManager()


def test_stale_symptom_no_longer_reads_as_current(tmp_path):
    """测试1: 凌晨记的恶心在晚上必须被标成「较早」，而不是当前状态"""
    manager = _make_manager(tmp_path)
    record = {
        "date": "2026-09-17",
        "health": [{"symptom": "恶心", "detail": "", "time": "00:09"}],
    }
    with patch.object(manager, "_load_record", return_value=record), patch(
        "core.services.daily.manager.get_current_time",
        return_value=datetime(2026, 9, 17, 19, 50),
    ):
        summary = manager.get_today_summary()

    assert "较早记录，可能已缓解" in summary, summary
    assert "恶心（00:09，约19小时前）" in summary, summary
    assert "不要据此询问病情" in summary, summary
    # 不能再出现「用户健康: 恶心」这种不带时刻的当前状态写法
    assert "- 用户健康: 恶心\n" not in summary
    print("[OK] 测试1 (凌晨的恶心在晚上被标为较早记录)")


def test_fresh_symptom_stays_current(tmp_path):
    """测试2: 窗口内的症状仍按当前状态呈现，且带上时刻"""
    manager = _make_manager(tmp_path)
    record = {
        "date": "2026-09-17",
        "health": [{"symptom": "胃痛", "detail": "", "time": "19:30"}],
    }
    with patch.object(manager, "_load_record", return_value=record), patch(
        "core.services.daily.manager.get_current_time",
        return_value=datetime(2026, 9, 17, 20, 30),
    ):
        summary = manager.get_today_summary()

    assert "用户健康: 胃痛（19:30）" in summary, summary
    assert "较早记录" not in summary, summary
    print("[OK] 测试2 (窗口内症状保留为当前状态并带时刻)")


def test_window_boundary(tmp_path):
    """测试3: 恰好 6 小时算当前，多 1 分钟算较早（边界值）"""
    on_edge, _ = split_health_entries(
        [{"symptom": "头晕", "time": "10:00"}],
        now=datetime(2026, 9, 17, 10 + HEALTH_FRESH_WINDOW_HOURS, 0),
    )
    assert on_edge == ["头晕（10:00）"], on_edge

    past_edge, earlier = split_health_entries(
        [{"symptom": "头晕", "time": "10:00"}],
        now=datetime(2026, 9, 17, 10 + HEALTH_FRESH_WINDOW_HOURS, 1),
    )
    assert past_edge == [], past_edge
    assert len(earlier) == 1, earlier
    print("[OK] 测试3 (6 小时边界：恰好算当前，超出算较早)")


def test_clock_skew_and_missing_time(tmp_path):
    """测试4: 时刻晚于当前（跨零点）按刚记录；缺时刻不吞症状"""
    fresh, earlier = split_health_entries(
        [{"symptom": "恶心", "time": "23:50"}],
        now=datetime(2026, 9, 17, 0, 5),
    )
    assert fresh == ["恶心（23:50）"], fresh
    assert earlier == [], earlier

    fresh2, earlier2 = split_health_entries(
        [{"symptom": "感冒"}], now=datetime(2026, 9, 17, 20, 0)
    )
    assert fresh2 == ["感冒"], fresh2
    assert earlier2 == [], earlier2
    print("[OK] 测试4 (跨零点与缺时刻的降级处理)")


def test_snapshot_uses_same_split(tmp_path):
    """测试5: 工作区快照复用同一套拆分逻辑，不再输出无时刻的健康行"""
    from core.services.workspace.snapshot import WorkspaceSnapshotBuilder

    builder = WorkspaceSnapshotBuilder()
    record = {
        "health": [{"symptom": "恶心", "detail": "", "time": "00:09"}],
    }
    with patch(
        "core.services.daily.manager.get_current_time",
        return_value=datetime(2026, 9, 17, 20, 0),
    ):
        text = builder._render_daily_summary(record)

    assert "较早记录，可能已缓解" in text, text
    assert "恶心（00:09，约19小时前）" in text, text
    print("[OK] 测试5 (工作区快照同步生效)")


def test_snapshot_historical_date_skips_annotation():
    """测试6: 渲染历史日期时关闭时效标注，保留原始症状名"""
    from core.services.workspace.snapshot import WorkspaceSnapshotBuilder

    builder = WorkspaceSnapshotBuilder()
    record = {"health": [{"symptom": "感冒", "detail": "", "time": "15:39"}]}
    text = builder._render_daily_summary(
        record, annotate_health_freshness=False
    )

    assert "用户健康: 感冒" in text, text
    assert "较早记录" not in text, text
    print("[OK] 测试6 (历史日期不做时效二次标注)")


def test_real_record_rendering_is_informational():
    """测试7（信息性）: 打印真实今日记录的渲染结果，便于人工核对"""
    today = today_str()
    path = os.path.join(
        str(get_user_daily_records_dir()),
        str(int(today[:4])),
        str(int(today[5:7])),
        str(int(today[8:10])),
        "daily_record.json",
    )
    if not os.path.exists(path):
        print("[SKIP] 测试7 (今日暂无 daily_record.json)")
        return
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not raw.get("health"):
        print("[SKIP] 测试7 (今日无 health 记录)")
        return
    print(f"[INFO] 今日 health 原始数据: {json.dumps(raw['health'], ensure_ascii=False)}")
    print("[INFO] 渲染结果:")
    for line in DailyActivityManager().get_today_summary().splitlines():
        print(f"       {line}")
    print("[OK] 测试7 (真实记录渲染完成，请人工核对时效标注)")


def main():
    import tempfile

    print("=" * 60)
    print("健康记录时效标注验证（2026-09-17 修复）")
    print("=" * 60)
    with tempfile.TemporaryDirectory() as tmp:
        test_stale_symptom_no_longer_reads_as_current(tmp)
        test_fresh_symptom_stays_current(tmp)
    test_window_boundary(None)
    test_clock_skew_and_missing_time(None)
    test_snapshot_uses_same_split(None)
    test_snapshot_historical_date_skips_annotation()
    test_real_record_rendering_is_informational()
    print("=" * 60)
    print("全部 7 个测试通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
