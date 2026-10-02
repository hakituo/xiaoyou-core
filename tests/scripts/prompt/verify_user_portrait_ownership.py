"""验证「用户日记录」在注入角色 prompt 时带上了明确的用户归属。

背景
----
2026-09-17 用户报障：他 19:10 起床，19:54 找Ling聊天，Ling回「刚睡醒，一下睡到
七点多」——角色把**用户**的午睡窗口认成了**自己**的睡眠。
根因是两份渲染器把用户日记录渲染成无署名的 `- Sleep: 13:11 → 19:10`
（标题还是英文泛称 `【Today's Portrait】`），再与角色自身状态合并进同一个
`【环境】` 块，模型无从区分。

本脚本检查：
1. 两份渲染器（DailyActivityManager / WorkspaceSnapshotBuilder）标题与每行都带用户归属；
2. 注入侧 `_build_user_status_and_daily` 带【归属说明】护栏，且不再出现旧文案；
3. `_extract_known_sleep_time_fact` 认得两套现行文案（「用户睡眠: HH:MM → HH:MM」
   与「用户昨晚睡觉: HH:MM」），且不让「通常入睡」（中位数）和设备实测行冒充当天锚点；
4. 设备实测睡眠行（2026-09-18 新增）：跨天带两端日期，无数据时整行不出现。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.prompt.verify_user_portrait_ownership
"""

from unittest.mock import MagicMock, patch

from core.agents.chat_agent_components.persona_system.prompt.components.user_bio import (
    _extract_known_sleep_time_fact,
    build_user_bio_context_for_chat,
)
from core.services.daily.manager import get_daily_manager
from core.services.workspace.snapshot import WorkspaceSnapshotBuilder

# 旧文案：任何一处重新出现都算回归
_LEGACY_MARKERS = (
    "【Today's Portrait】",
    "【今日日程摘要】",
    "【睡眠事实锚点】",
    "- Sleep:",
    "- Wakeup:",
    "- Meals:",
    "- Health:",
)

_SAMPLE_RECORD = {
    "date": "2026-09-17",
    "sleep_cycle": {
        "sleep": "13:11",
        "wakeup": "19:10",
        "duration": "5h59m",
    },
    "meals": [{"type": "meal", "content": "已吃", "time": "08:20"}],
    "study": {"sessions": [{"topic": "英语词汇", "time": "09:53"}]},
    "activities": [{"content": "在写代码", "time": "20:00"}],
    "health": [{"symptom": "恶心", "time": "00:09"}],
    "mood": {"mood": "平静", "detail": "还行"},
}


def _assert_ownership(label: str, text: str) -> None:
    """断言渲染结果带用户归属，且没有旧的无署名文案。"""
    assert text.startswith("【用户今日画像】"), f"{label}: 标题缺少用户归属\n{text}"
    for marker in _LEGACY_MARKERS:
        assert marker not in text, f"{label}: 旧文案回归 -> {marker}"
    _assert_ownership_lines(label, text)
    print(f"[OK] {label} 归属完整，共 {len(text.splitlines())} 行")


def _assert_ownership_lines(label: str, text: str) -> None:
    """断言「用户今日画像」块内的每个数据行都带用户前缀。

    只管日记录那一块：其余块（如【当前用户状态】）的归属写在块标题上，
    不该按行强求前缀。
    """
    inside = False
    for line in text.splitlines():
        if line.startswith("【"):
            inside = line.startswith("【用户今日画像】")
            continue
        if inside and line.startswith("- "):
            assert line.startswith("- 用户"), f"{label}: 该行缺少用户前缀 -> {line}"


def verify_daily_manager_render() -> None:
    """真实日记录渲染（只读，不写盘）。"""
    text = get_daily_manager().get_today_summary()
    _assert_ownership("DailyActivityManager.get_today_summary", text)
    print(text)


def verify_snapshot_render() -> None:
    """工作区快照渲染（纯函数，喂样例记录）。"""
    text = WorkspaceSnapshotBuilder()._render_daily_summary(
        _SAMPLE_RECORD, fallback_sleep="23:30"
    )
    _assert_ownership("WorkspaceSnapshotBuilder._render_daily_summary", text)
    assert "- 用户睡眠: 13:11 → 19:10 (5h59m)" in text, text
    # 健康行会按时效再分「较早记录」，这里只锁定归属前缀，不锁死时效措辞
    assert any(
        line.startswith("- 用户健康") and "恶心" in line for line in text.splitlines()
    ), text
    print(text)


def verify_injection_side() -> None:
    """注入侧：护栏存在、标题改名、旧文案不出现。"""
    status_manager = MagicMock()
    status_manager.get_status_summary.return_value = "当前无特殊状态"

    daily_manager = MagicMock()
    # 桩数据用现行文案（当天有记录时是「用户睡眠: HH:MM → HH:MM」，
    # 与「用户昨晚睡觉」是互斥分支，不会同时出现）。
    daily_manager.get_today_summary.return_value = (
        "【用户今日画像】\n"
        "- 用户睡眠: 13:11 → 19:10 (5h59m)\n"
    )

    with patch(
        "core.services.workspace.status_manager.get_user_status_manager",
        return_value=status_manager,
    ), patch(
        "core.services.daily.manager.get_daily_manager",
        return_value=daily_manager,
    ):
        text = build_user_bio_context_for_chat("test-user")

    assert "【归属说明】" in text, text
    assert "【用户今日日程摘要】" in text, text
    assert "【用户睡眠事实锚点】" in text, text
    assert "last_night_bedtime=13:11" in text, text
    for marker in _LEGACY_MARKERS:
        assert marker not in text, f"注入侧旧文案回归 -> {marker}"
    # 该用例原本用于保证锚点是事实、不是唠叨，别把说教词带回来
    for coaching in ("禁止追问", "禁止问", "现在困吗", "必须"):
        assert coaching not in text, f"注入侧出现说教词 -> {coaching}"
    print("[OK] 注入侧护栏与标题正确")
    print(text)


def verify_injection_side_real_data() -> None:
    """真实数据端到端：不 mock，确认角色 prompt 里那段确实带护栏与用户前缀。

    前面的注入侧用例用的是桩数据，只能证明拼接逻辑；这一项走真实的状态管理器
    与真实日记录，确保线上跑起来时【环境】块里也是带归属的版本。
    """
    text = build_user_bio_context_for_chat("default_user")
    assert "【归属说明】" in text, text
    for marker in _LEGACY_MARKERS:
        assert marker not in text, f"真实注入里旧文案回归 -> {marker}"
    # 只校验日记录那一块：其余块（如【当前用户状态】）的归属写在块标题上，
    # 逐行强求「用户」前缀会误报，这里按块判断。
    _assert_ownership_lines("真实注入 / 用户今日画像", text)
    print("[OK] 真实数据注入侧带齐归属护栏")

    # 回归防线：get_today_summary() 不收 user_id，传了会抛 TypeError 被 except 吞掉，
    # 日记录那一段（以及【用户睡眠事实锚点】）就会静默消失。这里必须验到画像确实进来了。
    assert "【用户今日画像】" in text, text
    print(text)


def verify_sleep_anchor_extraction() -> None:
    """睡眠事实锚点：认得两套现行文案，但不被「通常入睡」和设备行冒充。"""
    assert _extract_known_sleep_time_fact("- 用户昨晚睡觉: 23:30") == "23:30"
    assert _extract_known_sleep_time_fact("昨晚睡觉：01:23") == "01:23"
    # 2026-09-18：日记录里 sleep+wakeup 齐全时渲染成「用户睡眠: HH:MM → HH:MM」，
    # 旧正则只认「睡觉」，锚点长年抽不出来（等于这条护栏形同虚设）。
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10 → 01:19 (12h9m)") == "13:10"
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10") == "13:10"
    pattern_only = (
        "【用户作息规律】用户通常起床: 07:30（07:00~08:30）；"
        "用户通常入睡: 23:30（23:00~00:30）（仅供参考，不是今天的实际时间）"
    )
    assert _extract_known_sleep_time_fact(pattern_only) == "", (
        "作息规律（中位数）不能冒充当天就寝事实"
    )
    device_line = (
        "- 用户睡眠（三星健康实测，优先于聊天推断）: 09-17 13:11 → 19:10（5h59m）"
    )
    assert _extract_known_sleep_time_fact(device_line) == "", (
        "设备实测行可能带往期日期，不能当「昨晚」锚点"
    )
    print("[OK] 睡眠事实锚点抽取边界正确（含新文案/设备行）")


def verify_device_sleep_line() -> None:
    """设备实测睡眠行：只读快照、跨天带两端日期、过期/无数据时不出现。"""
    from datetime import timedelta

    from core.services.daily import manager as manager_module
    from core.utils.time_utils import get_current_time

    # 桩数据一律基于「当前时间」构造，避免写死日期后过几天就红（禁止 flaky）
    now = get_current_time()
    recent_day = now - timedelta(days=1)
    same_day_window = {
        "start": recent_day.replace(hour=13, minute=11, second=0, microsecond=0),
        "end": recent_day.replace(hour=19, minute=10, second=0, microsecond=0),
        "sleep_minutes": 331,
        "sleep_score": 36,
    }
    with patch(
        "core.services.health_sync.store.read_latest_sleep_window",
        return_value=same_day_window,
    ):
        line = manager_module.render_device_sleep_line()
    expected_start = same_day_window["start"].strftime("%m-%d %H:%M")
    assert line.startswith("- 用户睡眠（三星健康实测"), line
    assert f"{expected_start} → 19:10" in line, line
    assert "5h59m" in line, line
    assert "实际睡眠 5h31m" in line, line
    assert "得分 36" in line, line
    assert _extract_known_sleep_time_fact(line) == "", line

    # sleep_minutes 缺失/脏值时只跳过这一小段，不能拖垮整行
    # （2026-09-18 复审抓到过一次缩进错误，导致「实际睡眠」永不输出）
    for broken_value in (None, "abc"):
        broken_window = dict(same_day_window, sleep_minutes=broken_value)
        with patch(
            "core.services.health_sync.store.read_latest_sleep_window",
            return_value=broken_window,
        ):
            broken_line = manager_module.render_device_sleep_line()
        assert broken_line.startswith("- 用户睡眠（三星健康实测"), broken_line
        assert "实际睡眠" not in broken_line, broken_line

    # 跨天窗口：两端都要带日期，不能被读成「今天」
    cross_day_window = {
        "start": (now - timedelta(days=2)).replace(
            hour=23, minute=20, second=0, microsecond=0
        ),
        "end": (now - timedelta(days=1)).replace(
            hour=7, minute=5, second=0, microsecond=0
        ),
        "sleep_minutes": 465,
        "sleep_score": None,
    }
    with patch(
        "core.services.health_sync.store.read_latest_sleep_window",
        return_value=cross_day_window,
    ):
        cross_line = manager_module.render_device_sleep_line()
    expected_span = (
        f"{cross_day_window['start'].strftime('%m-%d %H:%M')} → "
        f"{cross_day_window['end'].strftime('%m-%d %H:%M')}"
    )
    assert expected_span in cross_line, cross_line

    # 快照过期（超过时效窗口）时整行不出现，避免几天前的作息被当成昨晚
    stale_window = {
        "start": now - timedelta(days=10),
        "end": now - timedelta(days=10) + timedelta(hours=7),
        "sleep_minutes": 400,
        "sleep_score": 70,
    }
    with patch(
        "core.services.health_sync.store.read_latest_sleep_window",
        return_value=stale_window,
    ):
        assert manager_module.render_device_sleep_line() == ""

    with patch(
        "core.services.health_sync.store.read_latest_sleep_window",
        return_value=None,
    ):
        assert manager_module.render_device_sleep_line() == ""
    print("[OK] 设备实测睡眠行渲染与锚点边界正确")


def main() -> None:
    verify_daily_manager_render()
    verify_snapshot_render()
    verify_injection_side()
    verify_injection_side_real_data()
    verify_sleep_anchor_extraction()
    verify_device_sleep_line()
    print("\n全部通过：用户数据在角色 prompt 中已带明确归属。")


if __name__ == "__main__":
    main()
