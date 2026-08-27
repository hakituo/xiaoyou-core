# -*- coding: utf-8 -*-
"""背单词复习提醒器（轻量定时检查）。

每天在固定时间检查「今天该复习的词总数」（= 昨天 daily 错词 + FSRS 已到期词），
若达到阈值则触发提醒。提醒通道留接口（notify_callback），具体推送到哪里
（App 内通知 / 微信 / QQ）由调用方注入，本模块不耦合任何通道。

用法：
    from core.tools.study.english.vocab_review_reminder import VocabReviewReminder
    reminder = VocabReviewReminder()
    reminder.start(notify_callback=my_send_func)   # 注入推送函数
    reminder.stop()
"""

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APS_AVAILABLE = True
except ImportError:
    BackgroundScheduler = CronTrigger = None
    _APS_AVAILABLE = False

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("VocabReviewReminder")

# ============ 可调参数 ============
# 每日检查时间（配置时区，默认 20:00）
CHECK_HOUR = 20
CHECK_MINUTE = 0
# 达到该数量才提醒（避免没几个词也打扰）
DUE_THRESHOLD = 10
# ================================


class VocabReviewReminder:
    """背单词复习提醒器：定时统计待复习量，超阈值触发提醒。"""

    def __init__(self):
        self._scheduler = None
        self._notify_callback = None
        self._running = False
        # 上次提醒日期，避免同一天重复提醒
        self._last_reminded_date = ""

    def _get_due_count(self) -> int:
        """统计今天该复习的词总数（昨天错词 + FSRS 到期词）。"""
        try:
            from core.tools.study.english.vocabulary_manager import (
                get_vocabulary_manager,
            )

            mgr = get_vocabulary_manager()
            words = mgr.get_daily_words(0)
            return len(words)
        except Exception as e:
            logger.warning(f"统计待复习词失败: {e}")
            return 0

    def _build_message(self, due_count: int) -> str:
        today_str = get_current_time().strftime("%Y-%m-%d")
        return (
            f"📚 今天有 {due_count} 个单词待复习（{today_str}）。"
            f"趁还记得去 app 里过一遍吧～"
        )

    def _check_and_notify(self):
        """定时任务主体：统计 → 判断阈值 → 触发提醒。"""
        try:
            today_str = get_current_time().strftime("%Y-%m-%d")
            # 同一天只提醒一次
            if self._last_reminded_date == today_str:
                return

            due_count = self._get_due_count()
            logger.info(f"背单词提醒检查：今日待复习 {due_count} 个（阈值 {DUE_THRESHOLD}）")

            if due_count >= DUE_THRESHOLD:
                msg = self._build_message(due_count)
                if self._notify_callback:
                    try:
                        self._notify_callback(msg, due_count)
                        logger.info(f"已触发背单词复习提醒（{due_count} 个）")
                    except Exception as e:
                        logger.error(f"背单词提醒推送失败: {e}")
                else:
                    logger.info(f"[提醒器] 未配置推送通道，跳过实际推送：{msg}")
                self._last_reminded_date = today_str
        except Exception as e:
            logger.error(f"背单词提醒检查异常: {e}", exc_info=True)

    def start(self, notify_callback=None):
        """启动定时检查。

        Args:
            notify_callback: 推送函数，签名 (message: str, due_count: int) -> None
        """
        if self._running:
            return
        if not _APS_AVAILABLE:
            logger.warning("APScheduler 不可用，背单词提醒器未启动")
            return

        self._notify_callback = notify_callback
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._check_and_notify,
            CronTrigger(hour=CHECK_HOUR, minute=CHECK_MINUTE),
            id="vocab_review_reminder",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            f"背单词复习提醒器已启动（每天 {CHECK_HOUR:02d}:{CHECK_MINUTE:02d} "
            f"检查，阈值 {DUE_THRESHOLD}）"
        )

    def stop(self):
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
        self._scheduler = None
        self._running = False
        logger.info("背单词复习提醒器已停止")

    def trigger_now(self, notify_callback=None):
        """手动触发一次检查（调试/测试用）。"""
        if notify_callback:
            self._notify_callback = notify_callback
        self._last_reminded_date = ""  # 强制允许本次提醒
        self._check_and_notify()


_reminder_instance = None


def get_vocab_review_reminder():
    global _reminder_instance
    if _reminder_instance is None:
        _reminder_instance = VocabReviewReminder()
    return _reminder_instance
