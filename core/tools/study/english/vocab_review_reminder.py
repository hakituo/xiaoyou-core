# -*- coding: utf-8 -*-
"""背单词催背提醒器（多时段定时检查）。

每天在固定时刻（默认 12 / 16 / 20 / 22 点）检查「今天背完没有」：
- 背完了 → 这次和之后都不再打扰；
- 没背完 → 推一条通知，点进去直达背单词页（深链 target=vocab）。

与旧实现的区别（旧实现实际上一条通知都发不出来）：
1. 旧版只有 20:00 一个时刻，且同一个自然日只提醒一次；现在按配置的
   多个时刻逐个催（12 点没背 16 点继续催），每个时刻最多一次。
2. 旧版判据是"待复习词数 >= 10"，跟"今天背没背"无关 —— 昨天背完、
   今天 FSRS 又到期几个词也会照催；现在用
   `get_today_review_status()` 的 `completed`，背完就闭嘴。
3. 旧版没有注入 notify_callback，定时到了只打一行日志"未配置推送通道"；
   现在内置默认推送（NotificationManager 入队 + WebSocket 广播），
   调用方也可以用 start(notify_callback=...) 覆盖。

用法：
    from core.tools.study.english.vocab_review_reminder import get_vocab_review_reminder
    get_vocab_review_reminder().start()             # 用内置推送通道
    get_vocab_review_reminder().start(my_callback)  # 自定义通道
    get_vocab_review_reminder().stop()
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APS_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境没装 APScheduler
    BackgroundScheduler = CronTrigger = None
    _APS_AVAILABLE = False

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("VocabReviewReminder")

# 默认提醒时刻（24 小时制），配置优先级更高：study.vocab_reminder_hours
DEFAULT_CHECK_HOURS = (12, 16, 20, 22)


class VocabReviewReminder:
    """背单词催背提醒器：多个时刻检查今日完成情况，没背完就催。"""

    def __init__(self):
        self._scheduler = None
        self._notify_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self._running = False
        # 已经提醒过的 (日期, 时刻)，避免同一时刻重复触发（如进程重启补跑）
        self._reminded: Set[Tuple[str, int]] = set()
        self._lock = threading.Lock()

    # ---------------- 配置与状态 ----------------

    @staticmethod
    def _check_hours() -> List[int]:
        """读取配置的提醒时刻，读不到就用默认四个时刻。"""
        try:
            from config.integrated_config import get_settings

            return get_settings().study.get_vocab_reminder_hours()
        except Exception as e:
            logger.debug(f"读取背单词提醒时刻失败，使用默认 {DEFAULT_CHECK_HOURS}: {e}")
            return list(DEFAULT_CHECK_HOURS)

    @staticmethod
    def _min_due() -> int:
        try:
            from config.integrated_config import get_settings

            return int(get_settings().study.vocab_reminder_min_due)
        except Exception:
            return 1

    @staticmethod
    def _study_enabled() -> bool:
        try:
            from config.integrated_config import get_settings

            return bool(get_settings().study.enabled)
        except Exception:
            return False

    def _get_today_status(self) -> Dict[str, Any]:
        """今日背单词完成情况。

        `completed` 是权威判据：StudyService 会话结束会写"完成词汇复习"，
        或者今日已复习且队列已清空，都算完成。
        """
        from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

        return get_vocabulary_manager().get_today_review_status()

    def _current_slot(self) -> int:
        """当前时间落在哪个提醒时刻（非提醒时刻返回 -1）。"""
        now = get_current_time()
        for hour in self._check_hours():
            # 定时任务整点触发，容忍 0~59 分钟内的进程重启补跑
            if now.hour == hour:
                return hour
        return -1

    # ---------------- 提醒主体 ----------------

    def _build_message(self, remaining: int, reviewed: int) -> str:
        if reviewed > 0:
            return f"今天背了 {reviewed} 个词，还有 {remaining} 个没背完，趁现在过一遍吧～"
        return f"今天还有 {remaining} 个单词没背，点一下马上开始～"

    def _default_notify(self, message: str, detail: Dict[str, Any]) -> None:
        """内置推送通道：入队 + WebSocket 广播（target=vocab，点击直达背单词页）。

        走模块属性调用（而不是 `from ... import push_app_notification`）：
        提醒器跑在 APScheduler 的后台线程里，用同步版丢回主循环广播。
        """
        from core.services.notification import app_push

        app_push.push_app_notification(
            title="该背单词啦",
            content=message,
            target=app_push.TARGET_VOCAB,
            data={
                "type": "vocab_reminder",
                "remaining_words": detail.get("remaining_words", 0),
                "reviewed_words": detail.get("reviewed_words", 0),
            },
            notification_type="vocab_reminder",
        )

    def check_and_notify(self, hour: Optional[int] = None) -> bool:
        """检查并（在需要时）催背。

        Args:
            hour: 指定时刻，缺省取当前小时。定时任务传触发时刻，
                  避免进程卡顿导致"16 点的任务按 17 点算"。

        Returns:
            是否真的发了提醒。
        """
        try:
            if not self._study_enabled():
                return False

            now = get_current_time()
            today_str = now.strftime("%Y-%m-%d")
            slot = hour if hour is not None else self._current_slot()
            if slot is None or slot < 0:
                return False

            with self._lock:
                if (today_str, slot) in self._reminded:
                    return False
                # 先占位再推送：推送失败也别在这一分钟里反复重试刷屏
                self._reminded.add((today_str, slot))

            status = self._get_today_status()
            if status.get("completed"):
                logger.info(
                    "背单词催背检查(%02d:00)：今天已经背完，跳过提醒", slot
                )
                return False

            remaining = int(status.get("remaining_words") or 0)
            reviewed = int(status.get("reviewed_words") or 0)
            if remaining < self._min_due():
                logger.info(
                    "背单词催背检查(%02d:00)：待背 %d 个，低于阈值 %d，不打扰",
                    slot, remaining, self._min_due(),
                )
                return False

            message = self._build_message(remaining, reviewed)
            detail = {"remaining_words": remaining, "reviewed_words": reviewed}
            callback = self._notify_callback or self._default_notify
            callback(message, detail)
            logger.info(
                "已触发背单词催背提醒(%02d:00)：已背 %d / 待背 %d",
                slot, reviewed, remaining,
            )
            return True
        except Exception as e:
            logger.error(f"背单词催背检查异常: {e}", exc_info=True)
            return False

    # 兼容旧方法名
    def _check_and_notify(self) -> None:  # pragma: no cover - 旧入口
        self.check_and_notify()

    # ---------------- 生命周期 ----------------

    def start(self, notify_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        """启动定时检查。

        Args:
            notify_callback: 推送函数，签名 (message: str, detail: dict) -> None；
                             不传则用内置通道（WebSocket + 通知队列）。
        """
        if self._running:
            return
        if not _APS_AVAILABLE:
            logger.warning("APScheduler 不可用，背单词催背提醒器未启动")
            return

        if notify_callback is not None:
            self._notify_callback = notify_callback
        hours = self._check_hours()
        self._scheduler = BackgroundScheduler()
        for hour in hours:
            self._scheduler.add_job(
                self.check_and_notify,
                CronTrigger(hour=hour, minute=0),
                args=[hour],
                id=f"vocab_review_reminder_{hour}",
                replace_existing=True,
            )
        self._scheduler.start()
        self._running = True
        logger.info(
            "背单词催背提醒器已启动（每天 %s 检查，背完就不再打扰）",
            "、".join(f"{h:02d}:00" for h in hours),
        )

    def stop(self):
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
        self._scheduler = None
        self._running = False
        logger.info("背单词催背提醒器已停止")

    def trigger_now(self, hour: Optional[int] = None, force: bool = True):
        """手动触发一次检查（调试/测试用）。

        Args:
            hour: 指定按哪个时刻判定；缺省用当前小时。
            force: 是否忽略"该时刻已提醒过"的限制。
        """
        if force:
            today_str = get_current_time().strftime("%Y-%m-%d")
            slot = hour if hour is not None else self._current_slot()
            with self._lock:
                self._reminded.discard((today_str, slot))
        return self.check_and_notify(hour=hour)


_reminder_instance = None
_instance_lock = threading.Lock()


def get_vocab_review_reminder() -> VocabReviewReminder:
    global _reminder_instance
    if _reminder_instance is None:
        with _instance_lock:
            if _reminder_instance is None:
                _reminder_instance = VocabReviewReminder()
    return _reminder_instance
