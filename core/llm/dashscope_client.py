#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DashScope API Client (dashscope_client.py)

Provides integration with Alibaba Cloud's DashScope API (e.g. Qwen-Max).
"""
import os
import sys
import asyncio
import time
import json
from typing import List, Dict, Optional, Any, Union
import aiohttp

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import logger
from core.utils.logger import get_logger
logger = get_logger('dashscope_client')

# Import config loader
from config.config_loader import ConfigLoader, Config
_loader = ConfigLoader()
config = Config(_loader)

from . import LLMModule

class DashScopeClient(LLMModule):
    """
    Client for interacting with DashScope API (Qwen models)
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize DashScope Client
        
        Args:
            api_key: DashScope API Key
        """
        super().__init__()
        # Priority: 
        # 1. Passed arg
        # 2. Environment variable direct check (Highest priority for security)
        # 3. Config from app.yaml
        self.api_key = (
            api_key 
            or os.getenv('DASHSCOPE_API_KEY')
            or config.get('app.system.dashscope_api_key') 
            or config.get('system.dashscope_api_key') 
        )
        # Lock to qwen3-max-2025-09-23 as requested
        self.default_model = "qwen3-max-2025-09-23"
        self.base_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        self.timeout = 60
        self.session = None
        self.initialized = False
        
        if not self.api_key:
            logger.warning("DashScope API Key not found. Please set DASHSCOPE_API_KEY in .env or config.")
        else:
            logger.info("DashScope Client initialized with API Key.")

    async def initialize(self):
        """
        Initialize LLM module
        """
        if not self.initialized:
            # 创建会话
            await self._get_session()
            self.initialized = True
            logger.info("DashScope Client initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
        return self.session

    async def _close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def chat(self, messages: list, **kwargs) -> str:
        """
        Chat generation
        
        Args:
            messages: List of chat messages
            **kwargs: Additional parameters
        
        Returns:
            Generated text content
        """
        if not self.initialized:
            await self.initialize()
        
        # 从messages中提取历史和当前prompt
        history = messages[:-1] if len(messages) > 1 else []
        prompt = messages[-1]['content'] if messages else ""
        
        result = await self.generate(prompt, history, **kwargs)
        if result['status'] == 'success':
            return result['text']
        else:
            logger.error(f"Chat failed: {result.get('error')}")
            return f"Error: {result.get('error')}"

    async def stream_chat(self, messages: list, **kwargs) -> Any:
        """
        Stream chat generation
        
        Args:
            messages: List of chat messages
            **kwargs: Additional parameters
        
        Yields:
            Generated text chunks
        """
        # 简化实现，实际应该调用流式API
        content = await self.chat(messages, **kwargs)
        yield {"content": content}

    def get_status(self) -> Dict[str, Any]:
        """
        Get module status
        
        Returns:
            Status dictionary
        """
        return {
            "status": "initialized" if self.initialized else "not_initialized",
            "api_key_configured": bool(self.api_key),
            "session_active": self.session is not None and not self.session.closed,
            "llm_status": {
                "instances_count": 1
            }
        }

    async def generate(
        self, 
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        model: str = "qwen3-max-2025-09-23",
        max_tokens: int = 1500,
        temperature: float = 0.8,
        top_p: float = 0.8,
        repetition_penalty: float = 1.1,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate text using DashScope API
        """
        if not self.api_key:
             return {"status": "error", "error": "DashScope API Key missing"}

        # Construct messages from history + prompt
        messages = []
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                messages.append({"role": role, "content": content})
        
        # Append current prompt as user message if not already in history (usually it isn't)
        # Check if the last message is the same as prompt to avoid duplication if caller handled it
        if not messages or messages[-1]['content'] != prompt:
             messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "input": {
                "messages": messages
            },
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "repetition_penalty": repetition_penalty,
                "result_format": "message"
            }
        }

        try:
            session = await self._get_session()
            async with session.post(self.base_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if "output" in data and "choices" in data["output"]:
                        choice = data["output"]["choices"][0]
                        content = choice["message"]["content"]
                        return {
                            "status": "success",
                            "text": content,
                            "usage": data.get("usage", {})
                        }
                    elif "code" in data:
                         return {
                            "status": "error",
                            "error": f"DashScope Error: {data.get('message')}",
                            "code": data.get("code")
                        }
                    else:
                        return {
                            "status": "error",
                            "error": "Unknown response format",
                            "raw": data
                        }
                else:
                    text = await response.text()
                    logger.error(f"DashScope API Error {response.status}: {text}")
                    return {"status": "error", "error": f"HTTP {response.status}: {text}"}
        except Exception as e:
            logger.error(f"DashScope Request Failed: {e}")
            return {"status": "error", "error": str(e)}

# Global instance
_dashscope_client = None

def get_dashscope_client():
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = DashScopeClient()
    return _dashscope_client
