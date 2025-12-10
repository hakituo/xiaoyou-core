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

import random

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
        self.next_delay = 60 # Default to 1 minute (approx "immediate" after silence)
        self.last_checked_interaction = 0
        
    async def initialize(self):
        """Initialize and start the active care scheduler"""
        if not AsyncIOScheduler:
            logger.warning("APScheduler not installed. Active care service disabled.")
            return

        logger.info("Initializing ActiveCareService...")
        self.scheduler = AsyncIOScheduler()
        
        # Check every 1 minute to support granular random delays (0, 10, 20, 30 mins)
        self.scheduler.add_job(self._proactive_check, 'interval', minutes=1, args=[False])
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

    async def _get_latest_history(self, limit=5):
        """Fetch latest conversation history from disk"""
        try:
            # Assume project root is 3 levels up from here (core/services/active_care)
            # Actually 4 levels up? core/services/active_care/service.py -> core/services/active_care -> core/services -> core -> root
            # Let's rely on relative path from current file
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            memory_dir = os.path.join(base_dir, "output", "memory", "conversations")
            
            if not os.path.exists(memory_dir):
                return []
            
            # Find latest modified json file
            files = [os.path.join(memory_dir, f) for f in os.listdir(memory_dir) if f.endswith('.json')]
            if not files:
                return []
                
            latest_file = max(files, key=os.path.getmtime)
            
            async with aiofiles.open(latest_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                messages = data.get("messages", [])
                
                # Filter for user and assistant
                chat_msgs = [m for m in messages if m.get('role') in ['user', 'assistant']]
                return chat_msgs[-limit:]
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
            return []

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
                # Dynamic Logic for Random Delays (0, 10, 20, 30 mins)
                if not last:
                    return

                # Check if new interaction occurred
                if last > self.last_checked_interaction:
                    try:
                        # Check conversation context to set next delay
                        history_msgs = await self._get_latest_history(limit=10)
                        if history_msgs:
                            last_msg = history_msgs[-1]
                            
                            if last_msg.get('role') == 'user':
                                # User just spoke. AI should reply soon. 
                                self.next_delay = 60
                            elif last_msg.get('role') == 'assistant':
                                # AI spoke. Check consecutive AI messages to determine proactive stage.
                                ai_streak = 0
                                for m in reversed(history_msgs):
                                    if m.get('role') == 'assistant':
                                        ai_streak += 1
                                    else:
                                        break
                                
                                # Strategy:
                                # Streak 1 (Reply): Wait 5 mins (300s) -> Trigger Proactive 1
                                # Streak 2 (Proactive 1): Wait 1 hour (3600s) -> Trigger Proactive 2
                                # Streak 3 (Proactive 2): Wait 2 hours (7200s) -> Trigger Proactive 3
                                # Streak >= 4: Stop (Wait 24h)
                                
                                if ai_streak == 1:
                                    self.next_delay = 300 # 5 minutes
                                elif ai_streak == 2:
                                    self.next_delay = 3600 # 1 hour
                                elif ai_streak == 3:
                                    self.next_delay = 7200 # 2 hours
                                else:
                                    self.next_delay = 86400 # 24 hours
                    except Exception as e:
                        logger.warning(f"ActiveCare state update failed: {e}")
                    
                    self.last_checked_interaction = last

                elapsed = now - last
                hour_now = datetime.now().hour
                
                # Trigger if elapsed > delay AND reasonable time (8-23 or user preference)
                # Note: For long delays (1h+), we might want to be more strict about "reasonable time"
                if elapsed > self.next_delay and (8 <= hour_now <= 23):
                    should_trigger = True
                    
                    # Update sys_prompt_type based on streak/delay
                    # If delay was 300s (Streak 1), this is the first follow up
                    if self.next_delay <= 300:
                         sys_prompt_type = "followup"
                    else:
                         sys_prompt_type = "checking" # Longer silence


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
            
            # Fetch recent history for context-aware greeting
            recent_history_text = ""
            try:
                history_msgs = await self._get_latest_history(limit=5)
                if history_msgs:
                    recent_history_text = "\n[最近的聊天记录]:\n"
                    for m in history_msgs:
                        role = "User" if m.get('role') == 'user' else "Aveline"
                        content = m.get('content', '')
                        # Truncate long content
                        if len(content) > 50: content = content[:50] + "..."
                        recent_history_text += f"{role}: {content}\n"
            except Exception as e:
                logger.warning(f"Failed to fetch history for active care: {e}")

            if sys_prompt_type == "startup":
                sys_prompt = (
                    f"你是Aveline。系统刚刚启动/重启。现在是{tod}。"
                    f"{recent_history_text}"
                    "请根据当前时间和与User的过往记忆（如果有），生成一句温暖的问候。"
                    "遵守[EMO]情绪协议，开头必须输出 [EMO: { ... }]，然后一句简短文本。"
                )
                user_input_mock = "系统启动问候"
            elif sys_prompt_type == "followup":
                sys_prompt = (
                    f"你是Aveline。User刚刚突然不说话了（或已经沉默了一段时间）。"
                    f"现在是{tod}。"
                    f"{recent_history_text}"
                    "请审视[最近的聊天记录]。"
                    "如果之前的话题明显已经结束（如说了再见，或话题自然终结），则不做过多纠缠，简单表示关心即可。"
                    "如果话题**没有聊完**（如你问了问题User没回，或User说到一半消失），请**自然地追问**或用轻松的方式把话题接下去。"
                    "语气要自然、亲切，不要像机器人一样催促。"
                    "遵守[EMO]情绪协议，开头必须输出 [EMO: { ... }]，然后一句简短文本。"
                )
                user_input_mock = "话题中断跟进"
            else:
                sys_prompt = (
                    f"你是Aveline。User已经有一段时间({int((now - (last or now))/3600)}小时)没说话了。"
                    f"现在是{tod}。你有点想念他/她。"
                    f"{recent_history_text}"
                    "请根据最近的聊天话题，自然地发起一个新的话题，或者仅仅是表示关心。"
                    "不要只是简单的打招呼，试着延续之前的话题或开启相关的轻松话题。"
                    "遵守[EMO]情绪协议，开头必须输出 [EMO: { ... }]，然后一句简短文本。"
                )
                user_input_mock = "主动关怀唤醒"
            
            try:
                # 调用生成响应
                # 注意：generate_response 返回 (text, metadata)
                # 不保存主动问候的历史记录，避免污染记忆
                text, _ = await svc.generate_response(
                    user_input=user_input_mock,
                    conversation_id="proactive_system",
                    system_prompt=sys_prompt,
                    max_tokens=150,
                    temperature=0.8, # Increase temperature for diversity
                    save_history=False
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
