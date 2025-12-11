#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aveline Core Service Module
Handles character logic, context management, and response generation.
Replaces the legacy fallback_service.py.
"""

import json
import os
import re
import time
import threading
import traceback
import uuid
import asyncio
import base64
import io
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    Image = None

import torch

from core.utils.logger import get_logger
from config.integrated_config import get_settings
from core.services.monitoring.resource_monitor import get_resource_monitor
from core.agents.chat_agent import get_default_chat_agent, ChatAgent

logger = get_logger("AVELINE_SERVICE")

class AvelineService:
    """
    Aveline Character Service
    Handles all character logic including context management, persona generation, and response generation.
    Replaces the legacy fallback_service.py.
    """
    
    def __init__(self):
        """Initialize Aveline Service"""
        self._initialized = False
        self.chat_agent: Optional[ChatAgent] = None
        try:
            logger.info("Initializing AvelineService...")
            
            self.settings = get_settings()
            self._resource_monitor = get_resource_monitor()
            
            # Load character configuration
            self.character_config = self._load_character_config()
            logger.info(f"Character config loaded: {self.character_config.get('name', 'Unknown')}")
            
            # Initialize ChatAgent
            self.chat_agent = get_default_chat_agent()
            
            # Performance stats
            self.performance_stats = {
                "total_requests": 0,
                "cache_hits": 0,
                "avg_processing_time": 0,
                "last_reset_time": time.time()
            }
            
            self._initialized = True
            logger.info("AvelineService initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize AvelineService: {e}")
            traceback.print_exc()
            # Ensure minimal availability
            if not hasattr(self, 'character_config'):
                self.character_config = {"name": "Aveline", "max_history_length": 5}
            self._initialized = True
            
    async def generate_proactive_message(self) -> str:
        """生成主动问候消息"""
        try:
            hour = datetime.now().hour
            time_period = "早上" if 5 <= hour < 12 else "下午" if 12 <= hour < 18 else "晚上" if 18 <= hour < 23 else "深夜"
            
            # 构造提示词
            prompt = f"现在是{time_period}。请根据当前时间生成一句简短、温暖的问候语。"
            
            # 调用生成响应
            # 注意：generate_response 返回 (text, metadata)
            response, _ = await self.generate_response(
                user_input=prompt,
                conversation_id="system_greeting",
                max_tokens=60,
                save_history=False
            )
            
            return response
        except Exception as e:
            logger.error(f"生成问候语失败: {e}")
            return f"你好，现在是{datetime.now().strftime('%H:%M')}。"

    async def initialize(self):
        """Async initialization"""
        if self.chat_agent:
            await self.chat_agent.initialize()

    async def shutdown(self):
        """Shutdown service and release resources"""
        logger.info("Shutting down AvelineService...")
        logger.info("AvelineService shutdown complete")

    def _init_model_adapter(self):
        """Initialize model adapter configuration (Deprecated)"""
        pass

    def _load_character_config(self):
        try:
            # Use core/character/configs/Aveline.json if available
            # Adjust path to point to core/character/configs
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            path = os.path.join(base_dir, "character", "configs", "Aveline.json")
            
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
                    
            # Fallback to config/character.json
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(base_dir))), "config", "character.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
                    
        except Exception:
            pass
        return {"name": "Aveline", "max_history_length": 10}

    def _init_context_templates(self):
        return {}

    async def analyze_screen(self, image_data: Union[str, bytes], prompt: str = "描述屏幕上的内容", **kwargs) -> Dict[str, Any]:
        """Analyze screen content using Vision Model"""
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        try:
            if not Image:
                return {"status": "error", "error": "PIL not installed"}

            image = None
            if isinstance(image_data, bytes):
                image = Image.open(io.BytesIO(image_data)).convert("RGB")
            elif isinstance(image_data, str):
                if "base64," in image_data:
                    image_data = image_data.split("base64,")[1]
                image_bytes = base64.b64decode(image_data)
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            if not image:
                raise ValueError("Invalid image data")

            if hasattr(self, 'model_manager') and self.model_manager:
                def _vision_task():
                    # Use ModelManager to get/load the vision model and perform inference
                    # Note: We are assuming ModelManager handles module loading now
                    # For MVP, we can load the module directly or via ModelManager's load_model
                    
                    # This part needs to be adapted to the new module structure
                    # We'll use the Module class directly for now to keep it simple, 
                    # but ideally ModelManager should return a Module instance
                    
                    # Using a temporary approach compatible with previous design:
                    # If we registered 'vision_model', we can load it
                    
                    model = self.model_manager.load_model("vision_model")
                    if not model:
                        return {"status": "error", "error": "Vision model not loaded"}
                    
                    # We need the tokenizer/processor too, but ModelManager's load_model currently returns just the model object
                    # The Module class encapsulates both. 
                    # Let's use the module directly here as a bridge until ModelManager is fully refactored
                    from core.modules.vision.module import VisionModule
                    
                    # Get config from model manager registration if possible, or fallback
                    vm = VisionModule()
                    # Hack: Inject the loaded model if it matches to save loading time? 
                    # Or just let VisionModule handle it. 
                    # Ideally ModelManager should return the Module instance.
                    
                    return vm.describe_image(image, prompt)

                response = await asyncio.to_thread(_vision_task)
                
                if isinstance(response, dict) and response.get("status") == "error":
                     return response
                
                response_text = response if isinstance(response, str) else response.get("description", "")
                if not response_text and isinstance(response, dict):
                    response_text = response.get("text", "")

                return {
                    "status": "success",
                    "description": response_text,
                    "request_id": request_id,
                    "processing_time": time.time() - start_time
                }
            else:
                return {"status": "error", "error": "ModelAdapter not initialized"}

        except Exception as e:
            logger.error(f"Screen analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _handle_command(self, user_input: str, conversation_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Handle system commands"""
        if not user_input.startswith("/"):
            return None
            
        parts = user_input[1:].strip().split(" ", 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "clear":
            key = f"conversation:{conversation_id}"
            self.cache_manager.set(key, [], ttl=86400)
            return "记忆已清除。", {"status": "success", "command": "clear"}
            
        elif cmd == "save":
            return "对话记录已保存。", {"status": "success", "command": "save"}
            
        elif cmd == "memory":
            history = self._get_conversation_history(conversation_id)
            msg_count = len(history)
            from core.services.system_memory_service import get_system_memory_manager
            sys_mem = get_system_memory_manager()
            mem_info = ""
            if sys_mem:
                stats = sys_mem.get_memory_stats()
                rss = stats['monitor_info']['process_rss_mb']
                mem_info = f"\n系统占用: {rss:.1f}MB"
            return f"当前记忆状态：\n对话轮数: {msg_count // 2}\n消息总数: {msg_count}{mem_info}", {"status": "success", "command": "memory"}
            
        elif cmd == "help":
             return (
                "可用指令：\n"
                "/clear - 清除当前对话记忆\n"
                "/save - 保存对话记录（自动）\n"
                "/memory - 查看记忆状态\n"
                "/help - 显示此帮助"
            ), {"status": "success", "command": "help"}
            
        return None

    async def stream_generate_response(
        self,
        user_input: str,
        conversation_id: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        model_hint: Optional[str] = None,
        save_history: bool = True
    ):
        """
        Stream response generation
        Yields chunks of text or structured data
        """
        try:
            # 0. Command Check
            cmd_result = await self._handle_command(user_input, conversation_id)
            if cmd_result:
                yield cmd_result[0]
                return

            # Delegate to ChatAgent
            if not self.chat_agent:
                self.chat_agent = get_default_chat_agent()
                
            # Use ChatAgent's stream_chat
            # Note: ChatAgent expects user_id, using conversation_id as user_id for now
            async for chunk in self.chat_agent.stream_chat(
                user_id=conversation_id, 
                message=user_input, 
                save_history=save_history,
                model_hint=model_hint
            ):
                # Pass through the structured chunk directly
                yield chunk
                
        except Exception as e:
            logger.error(f"stream_generate_response error: {e}")
            yield {"error": str(e), "done": True}

    async def generate_response(
        self,
        user_input: str,
        conversation_id: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        timeout: Optional[float] = None,
        model_hint: Optional[str] = None,
        save_history: bool = True
    ) -> Tuple[str, Dict[str, Any]]:
        """Main entry point for generating responses (Non-streaming)"""
        
        # 0. Command Check
        cmd_result = await self._handle_command(user_input, conversation_id)
        if cmd_result:
            return cmd_result
            
        start_time = time.time()
        full_response = ""
        metadata = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "conversation_id": conversation_id,
            "triggers": []
        }

        try:
             # Delegate to ChatAgent
            if not self.chat_agent:
                self.chat_agent = get_default_chat_agent()

            # Aggregate stream
            async for chunk in self.chat_agent.stream_chat(
                user_id=conversation_id, 
                message=user_input, 
                save_history=save_history,
                model_hint=model_hint
            ):
                if "content" in chunk:
                    full_response += chunk["content"]
                
                if "type" in chunk:
                    # Collect triggers for metadata
                    metadata["triggers"].append({
                        "type": chunk["type"],
                        "data": chunk.get("data")
                    })
            
            # Extract emotion from aggregated response
            final_content, emotion_label = self.chat_agent.extract_and_strip_emotion(full_response)
            if emotion_label:
                metadata["emotion"] = emotion_label
                
            # Parse proactive actions
            # 1. Image Generation: [GEN_IMG: prompt]
            img_match = re.search(r'\[GEN_IMG:\s*(.*?)\]', final_content)
            if img_match:
                metadata["image_prompt"] = img_match.group(1)
                final_content = final_content.replace(img_match.group(0), "")
                
            # 2. Voice Selection: [VOICE: style]
            voice_match = re.search(r'\[VOICE:\s*(.*?)\]', final_content)
            if voice_match:
                metadata["voice_id"] = voice_match.group(1)
                final_content = final_content.replace(voice_match.group(0), "")
                metadata["message_type"] = "voice"
            
            final_content = final_content.strip()

            metadata["processing_time_ms"] = int((time.time() - start_time) * 1000)
            return final_content, metadata

        except Exception as e:
            logger.error(f"generate_response error: {e}")
            traceback.print_exc()
            return "抱歉，系统遇到了一些问题。", {"status": "error", "error": str(e)}


    def _infer_with_model(
        self, 
        prompt: str, 
        messages: List[Dict[str, str]], 
        max_tokens: int, 
        temperature: float,
        model_hint: Optional[str]
    ) -> Tuple[str, Dict[str, Any]]:
        """Low-level model inference logic"""
        
        # 1. Resolve model path
        resolved_model_hint = model_hint
        if model_hint:
            if os.path.isabs(model_hint) and os.path.exists(model_hint):
                resolved_model_hint = model_hint
            else:
                project_root = os.getcwd()
                possible_paths = [
                    os.path.join(project_root, "models", model_hint),
                    os.path.join(project_root, model_hint),
                    os.path.join(project_root, "models", model_hint.replace("/", os.sep)),
                ]
                
                found = False
                for p in possible_paths:
                    if os.path.exists(p):
                        resolved_model_hint = p
                        found = True
                        break
                
                if not found:
                    if "/" in model_hint or "\\" in model_hint:
                        logger.warning(f"Model path not found: {model_hint}, falling back to loaded model")
                        resolved_model_hint = None

        # Use model_adapter
        if hasattr(self, 'model_adapter') and self.model_adapter:
            try:
                logger.debug(f"Using model_adapter.chat (model_hint={resolved_model_hint})")
                res = self.model_adapter.chat(
                    messages=messages,
                    model_name=resolved_model_hint,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                if isinstance(res, dict):
                    if res.get("status") == "error":
                         raise Exception(res.get("error", "Unknown error"))
                    
                    content = res.get("response", "")
                    if not content and "data" in res:
                        content = res["data"].get("text", "")
                        
                    return content, {"model": "model_adapter"}
                return str(res), {"model": "model_adapter"}
            except Exception as e:
                logger.error(f"ModelAdapter inference failed: {e}")
                raise e
        
        mgr = self.model_manager
        if hasattr(mgr, 'generate'):
             try:
                out = mgr.generate(prompt, max_tokens=max_tokens, temperature=temperature)
                if isinstance(out, dict):
                    return out.get("text", ""), {"model": "manager_v2"}
                return str(out), {"model": "manager_v1"}
             except Exception as e:
                logger.error(f"Manager inference failed: {e}")
                raise e
        
        return "No model available", {"model": "none"}

    def _check_system_resources(self) -> bool:
        return True

    def _generate_lightweight_response(self, user_input: str) -> str:
        return "系统资源紧张，请稍后再试。"

    def _generate_safe_response(self, user_input: str) -> str:
        return "抱歉，处理超时。"

    def _clean_response(self, text: str) -> str:
        if not text: return ""
        return text.strip()

    def _truncate_response(self, text: str, max_len: int = 4096) -> str:
        if len(text) <= max_len: return text
        return text[:max_len]

    def _generate_cache_key(self, user_input: str, conversation_id: str) -> str:
        raw = f"{conversation_id}:{user_input}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    async def _get_from_cache(self, key: str) -> Optional[Dict]:
        return await self.response_cache.get(key)

    async def _add_to_cache(self, key: str, response: str, metadata: Dict):
        data = {"response": response, "metadata": metadata}
        await self.response_cache.set(key, data)

    def _get_conversation_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        try:
            key = f"conversation:{conversation_id}"
            history = self.cache_manager.get(key)
            return history if history else []
        except Exception:
            return []

    def _update_conversation_history(self, conversation_id: str, user_input: str, assistant_response: str):
        try:
            key = f"conversation:{conversation_id}"
            history = self._get_conversation_history(conversation_id)
            now_ts = time.time()
            
            # Append to memory
            history.append({"role": "user", "content": user_input, "ts": now_ts})
            history.append({"role": "assistant", "content": assistant_response, "ts": now_ts})
            
            # Persist to file (Backup)
            self._persist_conversation(conversation_id, "user", user_input, now_ts)
            self._persist_conversation(conversation_id, "assistant", assistant_response, now_ts)
            
            max_len = self.character_config.get("max_history_length", 10) * 2
            if len(history) > max_len:
                history = history[-max_len:]
            
            self.cache_manager.set(key, history, ttl=86400)
        except Exception as e:
            logger.error(f"Failed to update history: {e}")

    def _persist_conversation(self, conversation_id: str, role: str, content: str, ts: float):
        """Persist conversation to file system"""
        # Optimized persistence
        try:
            # Use MemoryModule if available (not fully migrated yet)
            # For now, keep local implementation but fix path resolution
            
            project_root = os.getcwd() # Use CWD which should be project root
            memory_dir = os.path.join(project_root, "output", "memory", "conversations")
            os.makedirs(memory_dir, exist_ok=True)
            
            path = os.path.join(memory_dir, f"{conversation_id}.json")
            
            # Direct append optimization
            new_msg = {
                "role": role,
                "content": content,
                "timestamp": ts
            }
            
            if not os.path.exists(path):
                data = {"messages": [new_msg]}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                # Append mode is tricky with JSON, so we read-modify-write but optimize where possible
                # To truly optimize, we would need a different format or database
                # For now, stick to read-modify-write to ensure valid JSON
                try:
                    with open(path, "r+", encoding="utf-8") as f:
                        data = json.load(f)
                        if "messages" not in data:
                            data["messages"] = []
                        data["messages"].append(new_msg)
                        f.seek(0)
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.truncate()
                except Exception:
                    # Fallback for corrupted files
                     with open(path, "w", encoding="utf-8") as f:
                        data = {"messages": [new_msg]}
                        json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to persist conversation: {e}")

    def _construct_detailed_system_prompt(self, cfg: Dict[str, Any], model_name: Optional[str] = None) -> str:
        """Construct detailed system prompt based on config"""
        try:
            identity = cfg.get("identity", {})
            name = identity.get("name", "Aveline")
            context = identity.get("context", "")
            
            now = datetime.now()
            current_time_str = now.strftime("%Y-%m-%d %H:%M:%S %A")
            
            base_prompt = cfg.get("system_prompt", "")
            
            personality = cfg.get("personality", {})
            traits = personality.get("traits", [])
            trait_desc = []
            for t in traits:
                if isinstance(t, dict):
                    t_name = t.get("name", "")
                    t_behaviors = t.get("behaviors", [])
                    if t_name and t_behaviors:
                        trait_desc.append(f"- {t_name}: {'; '.join(t_behaviors)}")
            trait_str = "\n".join(trait_desc)
            
            prompt = f"{base_prompt}\n\nName: {name}\nContext: {context}\nCurrent Time: {current_time_str}\n\nPersonality Traits:\n{trait_str}\n"
            
            return prompt
            
        except Exception as e:
            logger.error(f"Error constructing system prompt: {e}")
            return cfg.get("system_prompt", "")

    def _build_prompt(
        self, 
        user_input: str, 
        history: List[Dict[str, Any]], 
        system_prompt: Optional[str], 
        conversation_id: str,
        model_name: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Build prompt from history and user input"""
        
        messages = []
        
        # System prompt
        sys_p = system_prompt
        if not sys_p:
             if hasattr(self, '_construct_detailed_system_prompt'):
                 sys_p = self._construct_detailed_system_prompt(self.character_config, model_name)
             else:
                 sys_p = self.character_config.get("system_prompt", "You are Aveline.")
             
        messages.append({"role": "system", "content": sys_p})
        
        # History
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
                
        # Current input
        messages.append({"role": "user", "content": user_input})
        
        # Text format (for completion models)
        text = ""
        for m in messages:
            text += f"{m['role']}: {m['content']}\n"
        text += "assistant: "
        
        return text, messages
