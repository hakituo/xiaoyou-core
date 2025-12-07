#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Active Care Service
Handles proactive interactions with the user based on time and inactivity.
"""

import logging
import time
import os
import json
import asyncio
import aiofiles
from datetime import datetime
from typing import Optional

from config.integrated_config import get_settings
from core.utils.logger import get_logger

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    AsyncIOScheduler = None

logger = get_logger("ACTIVE_CARE")

class ActiveCareService:
    def __init__(self):
        self.scheduler = None
        self._running = False
        self.settings = get_settings()
        
    async def initialize(self):
        """Initialize and start the active care scheduler"""
        if not AsyncIOScheduler:
            logger.warning("APScheduler not installed. Active care service disabled.")
            return

        logger.info("Initializing ActiveCareService...")
        self.scheduler = AsyncIOScheduler()
        
        # Add scheduled job: Check every 10 minutes
        self.scheduler.add_job(self._proactive_check, 'interval', minutes=10, args=[False])
        self.scheduler.start()
        self._running = True
        
        # Run immediate check for startup (once)
        # Disabled to avoid duplicate greeting with frontend
        # asyncio.create_task(self._proactive_check(is_startup=True))
        
        logger.info("ActiveCareService initialized and scheduled.")

    async def shutdown(self):
        """Stop the scheduler"""
        if self.scheduler and self._running:
            logger.info("Shutting down ActiveCareService...")
            try:
                self.scheduler.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down scheduler: {e}")
            self._running = False
            logger.info("ActiveCareService shutdown complete.")

    async def _proactive_check(self, is_startup=False):
        """
        Execute proactive check logic.
        """
        try:
            # Import here to avoid circular imports during startup
            from core.services.life_simulation.service import get_life_simulation_service
            from core.server.connection_manager import get_connection_manager
            from core.core_engine.lifecycle_manager import get_aveline_service
            
            svc = get_aveline_service()
            if not svc:
                logger.warning("Active Care: Service not ready, skipping")
                return

            # Get last interaction time
            sim_service = get_life_simulation_service()
            last = sim_service.last_interaction_time
            now = time.time()
            
            should_trigger = False
            sys_prompt_type = "normal"
            
            if is_startup:
                logger.info("Active Care: Performing startup check...")
                should_trigger = True
                sys_prompt_type = "startup"
            else:
                # Normal periodic check logic
                if not last:
                    return
                
                hours = (now - last) / 3600.0
                hour_now = datetime.now().hour
                
                # User requirements: Check every 10 minutes via LLM
                # Logic: If silent for > 1 hour AND current time is reasonable (8-23), trigger check
                if hours > 1.0 and (8 <= hour_now <= 23):
                    should_trigger = True
                    sys_prompt_type = "checking"
            
            if not should_trigger:
                return

            # Daily frequency limit check
            # Use memory settings path if available, otherwise fallback to runtime
            runtime_dir = self.settings.memory.history_dir or "runtime"
            if not os.path.isabs(runtime_dir):
                # 如果是相对路径，基于项目根目录
                # 这里简单处理，假设 runtime 目录在项目根目录
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                runtime_dir = os.path.join(base_dir, runtime_dir)
            
            os.makedirs(runtime_dir, exist_ok=True)
            pc_file = os.path.join(runtime_dir, 'proactive_count.json')
            
            pc = {}
            try:
                if os.path.exists(pc_file):
                    async with aiofiles.open(pc_file, 'r', encoding='utf-8') as f:
                        content = await f.read()
                        pc = json.loads(content)
            except Exception as e:
                logger.warning(f"Failed to read proactive count: {e}")
                pc = {}
                
            date_key = datetime.now().strftime('%Y-%m-%d')
            count = int(pc.get(date_key) or 0)
            
            # If not startup greeting, and today's limit reached (5 times), stop.
            if not is_startup and count >= 5:
                logger.info("Active Care: Daily limit reached")
                return

            hour_now = datetime.now().hour
            tod = '早上' if hour_now < 12 else ('下午' if hour_now < 18 else '晚上')
            
            if sys_prompt_type == "startup":
                sys_prompt = (
                    f"你是Aveline。系统刚刚启动/重启。现在是{tod}。"
                    "请根据当前时间和与User的过往记忆，生成一句温暖的问候。"
                    "遵守[EMO]情绪协议，开头必须输出 [EMO: { ... }]，然后一句简短文本。"
                )
                user_input_mock = "系统启动问候"
            else:
                sys_prompt = (
                    f"你是Aveline。User已经有一段时间({int((now - (last or now))/3600)}小时)没说话了。"
                    f"现在是{tod}。你有点想念他/她。"
                    "请生成一句简短的问候或开启话题。"
                    "遵守[EMO]情绪协议，开头必须输出 [EMO: { ... }]，然后一句简短文本。"
                )
                user_input_mock = "主动关怀唤醒"
            
            try:
                # Generate using LLM
                logger.info(f"Active Care: Generating content ({sys_prompt_type})...")
                text, _ = await svc.generate_response(
                    user_input=user_input_mock,
                    conversation_id="proactive_system",
                    system_prompt=sys_prompt,
                    max_tokens=150,
                    temperature=0.8 # Increase temperature for diversity
                )
                
                # Only send if generation successful and contains EMO
                if text and "EMO" in text:
                    conn_manager = get_connection_manager()
                    await conn_manager.broadcast({
                        "type": "chat_message",
                        "sender": "Aveline",
                        "content": text,
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.info(f"Active Care: Pushed - {text[:20]}...")
                    
                    # Update count
                    if not is_startup:
                        pc[date_key] = count + 1
                        try:
                            async with aiofiles.open(pc_file, 'w', encoding='utf-8') as f:
                                await f.write(json.dumps(pc, ensure_ascii=False, indent=2))
                        except Exception as e:
                            logger.error(f"Failed to write proactive count: {e}")
            except Exception as e:
                logger.error(f"Active Care generation failed: {e}")
                
        except Exception as e:
            logger.error(f"Active Care execution error: {e}")

_active_care_service = None

def get_active_care_service():
    global _active_care_service
    if _active_care_service is None:
        _active_care_service = ActiveCareService()
    return _active_care_service
