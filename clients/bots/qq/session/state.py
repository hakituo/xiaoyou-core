"""QQ 适配器会话状态管理模块。

负责仿生延迟画像、打字延迟计算、智能睡眠等状态相关逻辑。
从 qq_adapter_session.py 拆分而来，采用 session 实例注入策略。
"""
import asyncio
import random
import time

from clients.bots.qq.settings import logger


class SessionStateManager:
    """会话状态管理器，处理打字延迟、仿生画像、智能睡眠等。"""

    def __init__(self, session):
        # 持有外层 XiaoyouSession 实例，用于访问 cfg/session_id 等属性
        self.session = session

    async def load_bionic_profile(self):
        """加载仿生延迟画像，带 TTL 缓存。"""
        if not self.session._cfg.qq_typing_delay_use_bionic_profile:
            return
        now = time.time()
        if self.session._bionic_profile and self.session._bionic_profile_expire_ts > now:
            return
        profile = {}
        try:
            if hasattr(self.session.adapter, "get_bionic_delay_profile"):
                profile = await self.session.adapter.get_bionic_delay_profile(self.session.session_id)
        except Exception as e:
            logger.debug(f"[{self.session.session_id}] 拉取仿生延迟画像失败: {e}")
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        ttl = max(30, int(self.session._cfg.qq_typing_delay_bionic_profile_ttl_seconds or 180))
        self.session._bionic_profile = profile
        self.session._bionic_profile_expire_ts = now + ttl

    def resolve_comma_split_probability(self) -> float:
        """解析逗号断句概率，优先使用仿生画像推荐值。"""
        value = float(self.session._cfg.qq_stream_comma_split_probability)
        delay_cfg = (
            (self.session._bionic_profile.get("delay") or {})
            if isinstance(self.session._bionic_profile, dict)
            else {}
        )
        suggested = delay_cfg.get("recommended_comma_split_probability")
        if suggested is not None:
            try:
                value = float(suggested)
            except Exception:
                pass
        return max(0.0, min(1.0, value))

    def calc_typing_delay(
        self,
        sentence: str,
        is_last_chunk: bool = False,
        allow_surprise_delay: bool = False,
    ) -> float:
        """计算打字延迟，综合考虑仿生画像、文本长度、惊喜延迟等。"""
        cfg = self.session._cfg
        char_count = len(str(sentence or ""))
        base_delay = max(cfg.qq_typing_delay_min_seconds, char_count * cfg.qq_typing_delay_per_char_seconds)
        delay_cfg = (
            (self.session._bionic_profile.get("delay") or {})
            if isinstance(self.session._bionic_profile, dict)
            else {}
        )
        try:
            base_factor = float(delay_cfg.get("base_multiplier") or 1.0)
        except Exception:
            base_factor = 1.0
        base_delay = base_delay * max(0.7, min(2.0, base_factor))
        base_delay = min(cfg.qq_typing_delay_max_seconds, base_delay)
        min_factor = min(cfg.qq_typing_delay_random_min_factor, cfg.qq_typing_delay_random_max_factor)
        max_factor = max(cfg.qq_typing_delay_random_min_factor, cfg.qq_typing_delay_random_max_factor)
        final_delay = base_delay * random.uniform(min_factor, max_factor)
        if char_count < cfg.qq_typing_delay_short_text_threshold:
            final_delay = max(cfg.qq_typing_delay_min_seconds, final_delay * cfg.qq_typing_delay_short_text_factor)
        if is_last_chunk:
            final_delay = max(cfg.qq_typing_delay_min_seconds, final_delay * 0.9)
        try:
            surprise_prob_factor = float(
                delay_cfg.get("surprise_probability_multiplier") or 1.0
            )
        except Exception:
            surprise_prob_factor = 1.0
        surprise_prob = max(
            0.0,
            min(
                1.0,
                float(cfg.qq_typing_delay_surprise_probability)
                * max(0.5, min(2.5, surprise_prob_factor)),
            ),
        )
        if allow_surprise_delay and not self.session._surprise_delay_used and surprise_prob > 0:
            if random.random() < surprise_prob:
                delay_min_from_profile = delay_cfg.get("surprise_min_seconds")
                delay_max_from_profile = delay_cfg.get("surprise_max_seconds")
                min_seconds = cfg.qq_typing_delay_surprise_min_seconds
                max_seconds = cfg.qq_typing_delay_surprise_max_seconds
                if delay_min_from_profile is not None:
                    try:
                        min_seconds = float(delay_min_from_profile)
                    except Exception:
                        pass
                if delay_max_from_profile is not None:
                    try:
                        max_seconds = float(delay_max_from_profile)
                    except Exception:
                        pass
                low = min(float(min_seconds), float(max_seconds))
                high = max(float(min_seconds), float(max_seconds))
                final_delay = max(final_delay, random.uniform(low, high))
                self.session._surprise_delay_used = True
        return final_delay

    async def smart_sleep(self, seconds: float):
        """分段睡眠，同时持续更新 last_activity 防止会话被监控杀死。"""
        if seconds <= 0:
            return

        self.session._in_smart_sleep = True
        try:
            # 分成小块睡眠，保持会话活跃
            chunk_size = 5.0
            remaining = seconds
            while remaining > 0 and self.session.running:
                sleep_time = min(remaining, chunk_size)
                await asyncio.sleep(sleep_time)
                # 更新活动时间戳，防止监控杀死会话
                self.session.last_activity = time.time()
                remaining -= sleep_time
        finally:
            self.session._in_smart_sleep = False
