#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
User and System Status Router
For Frontend Sidebar/Dashboard
"""
import logging
import psutil
from fastapi import APIRouter, Depends
from core.services.study_service import get_study_service
from core.character.managers.dependency_manager import get_dependency_manager
from core.emotion.manager import get_emotion_manager
from core.services.life_simulation.service import get_life_simulation_service

router = APIRouter(prefix="/api/v1/user", tags=["user"])
logger = logging.getLogger(__name__)

@router.get("/status")
async def get_user_status():
    """Get aggregated user status for sidebar"""
    try:
        # 1. Dependency/Intimacy
        dep_manager = get_dependency_manager()
        intimacy = dep_manager.get_intimacy_level()
        # Calculate level: Level = Intimacy // 100 + 1 (Simple formula, assuming max 1.0 is level 100?)
        # Wait, intimacy is 0.0 to 1.0 in code (min(1.0, ...)).
        # Let's scale it to 100 for display or keep as is.
        # User said "Level 5", "XP 100/200".
        # If intimacy is 0.5, maybe Level 50?
        # Let's map 0.0-1.0 to Level 1-100.
        level = int(intimacy * 100)
        if level == 0: level = 1
        
        # 2. Study Stats
        study_service = get_study_service()
        vocab_stats = study_service.get_dictionary_stats()
        
        # 3. Emotion
        emo_manager = get_emotion_manager()
        # Assuming single user for now or getting default
        emo_state = emo_manager.get_current_state("user") # Default user
        current_emotion = emo_state.primary_emotion.value if emo_state and emo_state.primary_emotion else "neutral"
        
        # 4. System Resources (for fun/dashboard)
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        
        # 5. Life Simulation (Energy/Mood of Aveline)
        life_sim = get_life_simulation_service()
        life_state = life_sim.get_state()
        
        return {
            "status": "success",
            "data": {
                "user": {
                    "name": "戚戚", # Should get from profile
                    "level": level,
                    "intimacy": intimacy,
                    "next_level_progress": int((intimacy * 1000) % 100), # Fake progress within level
                    "title": "Diligent Student"
                },
                "aveline": {
                    "emotion": current_emotion,
                    "energy": life_state.get("energy", 100),
                    "mood": life_state.get("mood", 100)
                },
                "study": {
                    "learned_words": vocab_stats.get("learned_words", 0),
                    "total_words": vocab_stats.get("total_words", 0),
                    "today_reviews": vocab_stats.get("today_reviews", 0)
                },
                "system": {
                    "cpu_usage": cpu,
                    "ram_usage": ram
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get user status: {e}")
        return {"status": "error", "message": str(e)}
