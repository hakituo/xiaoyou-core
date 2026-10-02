# -*- coding: utf-8 -*-
"""专注监控协调器阈值配置（不写死在业务代码里）。

通过环境变量或 config/.env 覆盖，例如：
    FOCUS_NUDGE_MIN_FOCUS_SEC=600
    FOCUS_NUDGE_DISTRACTION_SEC=90
"""
from __future__ import annotations

from ._base import BaseSettings, SettingsConfigDict, Field


class FocusMonitorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOCUS_", extra="ignore")

    # 探班（温柔模式）阈值
    nudge_min_focus_sec: int = Field(600, description="至少专注多久后才允许第一次探班（秒，默认10分钟）")
    nudge_distraction_sec: int = Field(90, description="分心状态需持续多久才提醒（秒，默认90秒，介于60~120）")
    nudge_cooldown_sec: int = Field(300, description="两次探班最小间隔（秒，默认5分钟）")
    nudge_max_per_session: int = Field(3, description="单个会话主动消息上限（默认3次）")

    # 严重度判定
    distraction_confidence_min: float = Field(0.6, description="低于此置信度的观察不计入分心/不指责")

    # 掉线 / 心跳
    heartbeat_timeout_sec: int = Field(45, description="超过该时间无心跳/观察视为掉线（秒）")
    offline_grace_sec: int = Field(120, description="掉线宽限，超过则自动暂停会话（秒）")

    # 数据保留
    raw_observation_keep_days: int = Field(7, description="原始观察保留天数，之后仅留存汇总")

    # 探班文案模式
    default_mode: str = Field("gentle", description="默认陪伴模式 gentle/strict")

    # 严格模式：低频视觉复核（严于温柔模式）
    strict_vision_review_enabled: bool = Field(
        True, description="严格模式下是否允许发起低频视觉复核"
    )
    strict_distraction_sec: int = Field(
        120, description="严格模式下，分心需持续多久才触发（秒）"
    )
    strict_vision_cooldown_sec: int = Field(
        600, description="两次低频视觉复核的最小间隔（秒，默认10分钟）"
    )
    strict_vision_min_focus_sec: int = Field(
        300, description="严格模式下至少专注多久后才允许视觉复核（秒）"
    )
    vision_review_prompt: str = Field(
        "简要判断画面里的人是否仍在认真学习，还是明显在做无关的事（如玩手机、离开、看视频）。"
        "只回答现象，不做道德评判。",
        description="低频视觉复核的提示词",
    )


_focus_cfg: FocusMonitorConfig | None = None


def get_focus_monitor_config() -> FocusMonitorConfig:
    global _focus_cfg
    if _focus_cfg is None:
        _focus_cfg = FocusMonitorConfig()
    return _focus_cfg
