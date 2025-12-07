from abc import ABC, abstractmethod
from typing import AsyncGenerator, Any, Dict, List, Optional
from pydantic import BaseModel

class LLMInterface(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        pass

    @abstractmethod
    async def stream_generate(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        pass

class MemoryInterface(ABC):
    @abstractmethod
    async def add_message(self, role: str, content: str, **kwargs):
        pass

    @abstractmethod
    async def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> List[str]:
        pass

class TTSInterface(ABC):
    @abstractmethod
    async def synthesize(self, text: str, emotion: str = None, **kwargs) -> str:
        """Returns path to audio file"""
        pass

class STTInterface(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: bytes, **kwargs) -> str:
        pass

class ImageGenInterface(ABC):
    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs) -> str:
        """Returns path to generated image"""
        pass

class VisionInterface(ABC):
    @abstractmethod
    async def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """Returns description of the image"""
        pass
