import asyncio
import torch
import gc
import os
from typing import AsyncGenerator
from transformers import AutoModelForCausalLM, AutoTokenizer
from domain.interfaces.base_interfaces import LLMInterface
from config import get_settings
import logging

logger = logging.getLogger("LocalLLMAdapter")

class LocalLLMAdapter(LLMInterface):
    def __init__(self):
        self.settings = get_settings()
        self.model_path = self.settings.model.text_path
        self.device = self.settings.model.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.tokenizer = None
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self):
        if self.model is None:
            await self._load_model()

    async def _load_model(self):
        logger.info(f"Loading Local LLM from {self.model_path}")
        try:
            # This should ideally be in a separate thread to avoid blocking event loop
            await asyncio.to_thread(self._load_model_sync)
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def _load_model_sync(self):
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            device_map="auto" if self.device == "cuda" else None,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            low_cpu_mem_usage=True,
            local_files_only=True
        )
        if self.device != "cuda":
            self.model.to(self.device)

    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        async with self._lock:
            await self._ensure_loaded()
            
            full_prompt = f"{system_prompt}\n{prompt}" if system_prompt else prompt
            
            response = await asyncio.to_thread(self._generate_sync, full_prompt, **kwargs)
            return response

    def _generate_sync(self, prompt: str, **kwargs) -> str:
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=kwargs.get("max_tokens", 512),
                temperature=kwargs.get("temperature", 0.7),
                do_sample=True
            )
        return self.tokenizer.decode(outputs[0][len(inputs.input_ids[0]):], skip_special_tokens=True)

    async def stream_generate(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        # For MVP, we fallback to non-streaming if underlying model doesn't support easy streaming
        # or implement a simple iterator
        response = await self.generate(prompt, system_prompt, **kwargs)
        # Simulate streaming by yielding words
        for word in response.split(" "):
            yield word + " "
            await asyncio.sleep(0.01)
