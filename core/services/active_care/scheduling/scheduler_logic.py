import random
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from core.utils.logger import get_logger
from config.integrated_config import get_settings
from core.services.active_care.shared.constants import (
    JITTER_LOW_RATIO,
    JITTER_HIGH_RATIO,
    INTERVAL_MIN_SECONDS,
    EMOTION_INTERVAL_MULTIPLIERS,
    calculate_non_response_backoff,
)

logger = get_logger("ACTIVE_CARE_SCHEDULER")


class ActiveCareSchedulerLogic:
    def __init__(self):
        self.settings = get_settings()

    def calculate_dynamic_interval(
        self,
        bio_state: Dict[str, Any] = None,
        emotion_state: Any = None,
        consecutive_non_responses: int = 0,
        quiet_mode: bool = False,
    ) -> int:
        active_interval = int(
            getattr(self.settings.life_simulation, "active_check_interval", 300)
        )
        quiet_interval = int(
            getattr(self.settings.life_simulation, "quiet_check_interval", 600)
        )

        base_interval = quiet_interval if quiet_mode else active_interval

        backoff_multiplier = calculate_non_response_backoff(consecutive_non_responses)
        if backoff_multiplier > 1.0:
            logger.debug(
                "Active Care: Applying backoff %.2fx due to %d non-responses",
                backoff_multiplier, consecutive_non_responses,
            )

        if quiet_mode:
            final_quiet = int(base_interval * backoff_multiplier)
            return max(INTERVAL_MIN_SECONDS, int(final_quiet * random.uniform(JITTER_LOW_RATIO, JITTER_HIGH_RATIO)))

        multiplier = 1.0 * backoff_multiplier

        if bio_state:
            life = bio_state.get("life", {})
            energy = float(life.get("energy", 50))
            hunger = float(life.get("hunger", 50))
            is_sick = bool(bio_state.get("is_sick", False)) or bool(
                life.get("is_sick", False)
            )

            if is_sick:
                multiplier *= 2.0
            elif energy < 30:
                multiplier *= 1.5
            elif energy > 80:
                multiplier *= 0.8

            if hunger > 80:
                multiplier *= 0.7

        if emotion_state:
            primary = getattr(emotion_state, "primary_emotion", None)
            if hasattr(primary, "value"):
                primary = primary.value
            primary = str(primary).lower() if primary else "neutral"

            intensity = float(getattr(emotion_state, "intensity", 0.5))

            emo_config = EMOTION_INTERVAL_MULTIPLIERS.get(primary)
            if emo_config:
                base_mod, intensity_mod = emo_config
                multiplier *= base_mod + (intensity_mod * intensity)

        jitter = random.uniform(JITTER_LOW_RATIO, JITTER_HIGH_RATIO)
        multiplier *= jitter

        final_interval = int(base_interval * multiplier)

        max_interval = max(active_interval, quiet_interval) * 2
        final_interval = max(INTERVAL_MIN_SECONDS, min(final_interval, max_interval))

        return final_interval

    def parse_hhmm(self, hhmm: str) -> Optional[int]:
        from core.utils.time_utils import parse_hhmm as _parse_hhmm
        return _parse_hhmm(hhmm)

    def is_in_range_minutes(self, now_min: int, start_min: int, end_min: int) -> bool:
        if start_min == end_min:
            return True
        if start_min < end_min:
            return start_min <= now_min < end_min
        return now_min >= start_min or now_min < end_min

    def next_range_end_dt(
        self, now_dt: datetime, start_min: int, end_min: int
    ) -> datetime:
        now_min = now_dt.hour * 60 + now_dt.minute
        if start_min < end_min:
            return now_dt.replace(
                hour=end_min // 60, minute=end_min % 60, second=0, microsecond=0
            )
        if now_min >= start_min:
            nxt = now_dt + timedelta(days=1)
            return nxt.replace(
                hour=end_min // 60, minute=end_min % 60, second=0, microsecond=0
            )
        return now_dt.replace(
            hour=end_min // 60, minute=end_min % 60, second=0, microsecond=0
        )

    def next_window_start_dt(
        self, now_dt: datetime, start_min: int, end_min: int
    ) -> datetime:
        now_min = now_dt.hour * 60 + now_dt.minute
        if self.is_in_range_minutes(now_min, start_min, end_min):
            return now_dt
        if start_min < end_min:
            if now_min < start_min:
                return now_dt.replace(
                    hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
                )
            nxt = now_dt + timedelta(days=1)
            return nxt.replace(
                hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
            )
        if now_min < end_min:
            return now_dt.replace(
                hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
            )
        if now_min < start_min:
            return now_dt.replace(
                hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
            )
        nxt = now_dt + timedelta(days=1)
        return nxt.replace(
            hour=start_min // 60, minute=start_min % 60, second=0, microsecond=0
        )
