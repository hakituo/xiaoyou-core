import logging
import asyncio
from typing import AsyncGenerator
try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

from domain.interfaces.base_interfaces import LLMInterface

logger = logging.getLogger("GGUFLLMAdapter")

class GGUFLLMAdapter(LLMInterface):
    def __init__(self, model_path: str, n_ctx: int = 2048, n_gpu_layers: int = -1):
        if Llama is None:
            raise ImportError("llama_cpp is not installed. Please install llama-cpp-python.")
        
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.model = None
        self._lock = asyncio.Lock()
    
    async def _ensure_loaded(self):
        if self.model is None:
            await self._load_model()

    async def _load_model(self):
        logger.info(f"Loading GGUF Model from {self.model_path}")
        try:
            self.model = await asyncio.to_thread(
                Llama,
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False
            )
            logger.info("GGUF Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load GGUF model: {e}")
            raise

    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        async with self._lock:
            await self._ensure_loaded()
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = await asyncio.to_thread(
                self.model.create_chat_completion,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 512),
                temperature=kwargs.get("temperature", 0.7),
                stream=False
            )
            
            return response["choices"][0]["message"]["content"]

    async def stream_generate(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        async with self._lock:
            await self._ensure_loaded()
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            stream = await asyncio.to_thread(
                self.model.create_chat_completion,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 512),
                temperature=kwargs.get("temperature", 0.7),
                stream=True
            )
            
            for chunk in stream:
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]
                    # Give other tasks a chance to run
                    await asyncio.sleep(0)
