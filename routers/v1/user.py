# -*- coding: utf-8 -*-
"""用户（user）域。

聚合用户侧的侧边栏 / Dashboard 状态：依赖亲密度、学习统计、当前情绪、
系统资源、生命模拟状态等。
"""

import logging

from fastapi import APIRouter

from core.api.contract import error_response
from core.api.error_response import ErrorCode

router = APIRouter(prefix="/user", tags=["用户状态"])
logger = logging.getLogger(__name__)


@router.get("/status", summary="获取聚合用户状态（侧边栏 / Dashboard）")
async def get_user_status():
    try:
        import psutil
        from core.services.study.service import get_study_service
        from core.character.managers.dependency_manager import get_dependency_manager
        from core.emotion.manager import get_emotion_manager
        from core.services.life_simulation.service import get_life_simulation_service
        from core.services.workspace.status_manager import get_user_status_manager
        from config.integrated_config import get_settings

        # 1. 依赖/亲密度
        dep_manager = get_dependency_manager()
        intimacy = dep_manager.get_intimacy_level()
        level = int(intimacy * 100)
        if level == 0:
            level = 1

        # 2. 学习统计
        study_service = get_study_service()
        vocab_stats = study_service.get_dictionary_stats()

        # 3. 情绪
        emo_manager = get_emotion_manager()
        emo_state = emo_manager.get_current_state("user")
        current_emotion = (
            emo_state.primary_emotion.value
            if emo_state and emo_state.primary_emotion
            else "neutral"
        )

        # 4. 系统资源
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent

        # 5. 生命模拟（Aveline 的能量 / 心情）
        life_sim = get_life_simulation_service()
        life_state = life_sim.get_state()
        user_status_manager = get_user_status_manager()
        active_statuses = user_status_manager.get_active_statuses()
        body_metrics = user_status_manager.get_body_metrics()

        return {
            "status": "success",
            "data": {
                "user": {
                    "name": (
                        str(get_settings().user.display_name or "").strip() or "用户"
                    ),
                    "level": level,
                    "intimacy": intimacy,
                    "next_level_progress": int(
                        (intimacy * 1000) % 100
                    ),
                    "title": "Diligent Student",
                },
                "aveline": {
                    "emotion": current_emotion,
                    "energy": life_state.get("energy", 100),
                    "mood": life_state.get("mood", 100),
                },
                "study": {
                    "learned_words": vocab_stats.get("learned_words", 0),
                    "total_words": vocab_stats.get("total_words", 0),
                    "today_reviews": vocab_stats.get("today_reviews", 0),
                },
                "persistent_status": {
                    "items": active_statuses,
                    "body_metrics": {
                        "weight_kg": body_metrics.get("weight_kg"),
                        "weight_updated_at": body_metrics.get("weight_updated_at"),
                    },
                },
                "system": {"cpu_usage": cpu, "ram_usage": ram},
            },
        }
    except Exception as e:
        logger.error(f"Failed to get user status: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
