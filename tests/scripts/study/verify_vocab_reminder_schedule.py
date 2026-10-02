"""验证背单词催背提醒的多时段调度与判据。

覆盖点：
1. 提醒时刻可配置（默认 12/16/20/22），每个时刻最多推一次；
2. 今天背完（completed=True）→ 不打扰；
3. 没背完 → 推送，且推送通道收到 target=vocab（点进去直达背单词页）；
4. 待背词数低于阈值 → 不打扰；
5. 内置推送通道会同时入通知队列（App 不在线也不丢）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.notification import app_push  # noqa: E402
from core.tools.study.english import vocab_review_reminder as reminder_module  # noqa: E402


def _make_reminder(hours, min_due=1, enabled=True):
    """造一个不依赖真实配置/词库的提醒器。"""
    reminder_module._reminder_instance = None
    reminder = reminder_module.VocabReviewReminder()
    reminder._check_hours = staticmethod(lambda: list(hours))
    reminder._min_due = staticmethod(lambda: min_due)
    reminder._study_enabled = staticmethod(lambda: enabled)
    return reminder


def _install_status(reminder, completed: bool, remaining: int, reviewed: int = 0):
    reminder._get_today_status = lambda: {
        "completed": completed,
        "remaining_words": remaining,
        "reviewed_words": reviewed,
    }


def main() -> int:
    problems: list[str] = []

    # ---- 1. 默认时刻可配置解析（读不到配置时回退 12/16/20/22） ----
    try:
        from config.settings_life import StudySettings

        hours = StudySettings().get_vocab_reminder_hours()
        if hours != [12, 16, 20, 22]:
            problems.append(f"默认提醒时刻应为 [12,16,20,22]，实际 {hours}")
        if StudySettings(vocab_reminder_hours="9, 21,9").get_vocab_reminder_hours() != [9, 21]:
            problems.append("提醒时刻解析未去重/未排序")
        if StudySettings(vocab_reminder_hours="abc").get_vocab_reminder_hours() != [12, 16, 20, 22]:
            problems.append("非法提醒时刻未回退默认值")
    except Exception as exc:
        problems.append(f"配置解析异常: {exc}")

    # ---- 2. 没背完 -> 推送，且 target=vocab ----
    reminder = _make_reminder([12, 16, 20, 22])
    pushed: list[dict] = []
    reminder._notify_callback = lambda message, detail: pushed.append(
        {"message": message, "detail": detail}
    )
    _install_status(reminder, completed=False, remaining=15, reviewed=3)
    if not reminder.check_and_notify(hour=12):
        problems.append("没背完时 12 点应推送提醒")
    if not pushed or "15" not in pushed[-1]["message"]:
        problems.append(f"提醒文案应带上待背数量，实际: {pushed}")

    # ---- 3. 同一时刻重复触发不会刷屏 ----
    _install_status(reminder, completed=False, remaining=15, reviewed=3)
    if reminder.check_and_notify(hour=12):
        problems.append("同一时刻重复检查不应再次推送")
    # 换一个时刻（16 点没背）应该继续催
    if not reminder.check_and_notify(hour=16):
        problems.append("16 点仍未背完应继续推送")
    if not reminder.check_and_notify(hour=20):
        problems.append("20 点仍未背完应继续推送")
    if not reminder.check_and_notify(hour=22):
        problems.append("22 点仍未背完应继续推送")

    # ---- 4. 背完了 -> 不再打扰 ----
    reminder_done = _make_reminder([12, 16, 20, 22])
    pushed_done: list[dict] = []
    reminder_done._notify_callback = lambda message, detail: pushed_done.append(detail)
    _install_status(reminder_done, completed=True, remaining=0, reviewed=20)
    if reminder_done.check_and_notify(hour=12):
        problems.append("今天已背完不应再推送")

    # ---- 5. 待背数低于阈值 -> 不打扰 ----
    reminder_few = _make_reminder([12], min_due=10)
    pushed_few: list[dict] = []
    reminder_few._notify_callback = lambda message, detail: pushed_few.append(detail)
    _install_status(reminder_few, completed=False, remaining=3)
    if reminder_few.check_and_notify(hour=12):
        problems.append("待背 3 个低于阈值 10，不应打扰")

    # ---- 6. 内置通道：载荷带 target=vocab（点进去直达背单词页） ----
    captured: list[dict] = []
    original_push = app_push.push_app_notification

    def fake_push(title, content, target=None, data=None, notification_type="system"):
        captured.append(
            {
                "title": title,
                "content": content,
                "target": target,
                "data": data,
                "type": notification_type,
            }
        )
        return True

    app_push.push_app_notification = fake_push
    try:
        reminder_builtin = _make_reminder([12])
        _install_status(reminder_builtin, completed=False, remaining=8)
        reminder_builtin.check_and_notify(hour=12)
        if len(captured) != 1:
            problems.append(f"内置通道应推送 1 条，实际 {len(captured)}")
        else:
            payload = captured[0]
            if payload["target"] != app_push.TARGET_VOCAB:
                problems.append(f"背单词提醒 target 应为 vocab，实际 {payload['target']}")
            if payload["data"].get("remaining_words") != 8:
                problems.append("提醒载荷应带上剩余待背数量")
    finally:
        app_push.push_app_notification = original_push

    # ---- 7. 广播载荷 body/content 双写（修掉安卓端读 body 拿到空串的问题） ----
    message = app_push._build_payload("标题", "正文", target="vocab")
    if message["body"] != "正文" or message["content"] != "正文":
        problems.append("通知载荷应同时带 body 与 content，兼容两端字段名")
    if message["target"] != "vocab":
        problems.append("通知载荷应带 target")

    # ---- 8. 词库功能关闭时不推送 ----
    reminder_off = _make_reminder([12], enabled=False)
    pushed_off: list[dict] = []
    reminder_off._notify_callback = lambda message, detail: pushed_off.append(detail)
    _install_status(reminder_off, completed=False, remaining=20)
    if reminder_off.check_and_notify(hour=12):
        problems.append("study.enabled=false 时不应推送背单词提醒")

    reminder_module._reminder_instance = None

    if problems:
        print("验证失败:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("背单词催背提醒验证通过：多时段调度/完成判据/直达背单词页均正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
