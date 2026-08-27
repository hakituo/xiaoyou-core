"""日常仪式管理模块 - 管理晨间打卡和睡前小结等日常仪式"""


from core.utils.logger import get_logger
from datetime import datetime
from core.utils.time_utils import get_current_time, now_str
from typing import Optional

logger = get_logger(__name__)


class RitualManager:
    """管理日常仪式，如晨间打卡和睡前小结"""

    def __init__(self):
        self.triggered_today = {"morning_checkin": False, "bedtime_summary": False}
        self._last_reset_date = now_str("%Y-%m-%d")

    def check_rituals(self, active_minutes: int) -> Optional[str]:
        """检查是否应该触发日常仪式"""
        now = get_current_time()
        today = now.strftime("%Y-%m-%d")

        if today != self._last_reset_date:
            self.triggered_today = {k: False for k in self.triggered_today}
            self._last_reset_date = today

        morning_ritual = self._check_morning_ritual(now)
        if morning_ritual:
            return morning_ritual

        bedtime_ritual = self._check_bedtime_ritual(now, active_minutes)
        if bedtime_ritual:
            return bedtime_ritual

        return None

    def _check_morning_ritual(self, now: datetime) -> Optional[str]:
        """检查晨间打卡仪式 (6:00 - 9:00)"""
        if 6 <= now.hour < 9 and not self.triggered_today["morning_checkin"]:
            self.triggered_today["morning_checkin"] = True

            study_msg = self._fetch_study_task()
            return f"晨间打卡：'今日适合穿你喜欢的浅蓝衬衫'{study_msg}"

        return None

    def _check_bedtime_ritual(
        self, now: datetime, active_minutes: int
    ) -> Optional[str]:
        """检查睡前小结仪式 (22:00 - 23:00)"""
        if 22 <= now.hour < 23 and not self.triggered_today["bedtime_summary"]:
            self.triggered_today["bedtime_summary"] = True
            if active_minutes > 0:
                return f"睡前小结：'今日互动{active_minutes}分钟，算力99%存你说的话'"
            else:
                return "睡前小结：'夜色温柔，静候明日重逢'"

        return None

    def _fetch_study_task(self) -> str:
        """获取今日学习任务"""
        try:
            from core.services.study.service import get_study_service

            service = get_study_service()
            summary = service.get_daily_study_summary_data()
            if summary:
                vocab = summary.get("vocab", {})
                return f"\n今日学习目标：复习 {vocab.get('to_review', 0)} 个单词。"
        except Exception as e:
            logger.error(f"Failed to fetch study summary for ritual: {e}")

        return ""
