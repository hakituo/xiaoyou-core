from core.utils.logger import get_logger
import httpx

from typing import Dict, Any

logger = get_logger(__name__)


class CPPSchedulerClient:
    """
    Client for communicating with the C++ Resource Isolation Scheduler.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.base_url = f"http://{host}:{port}"
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        self._is_connected = False

    async def connect(self) -> bool:
        """
        Check connection to the scheduler.
        """
        try:
            response = await self.client.get("/health")
            if response.status_code == 200:
                self._is_connected = True
                logger.info(
                    f"Successfully connected to C++ Scheduler at {self.base_url}"
                )
                return True
            else:
                logger.warning(
                    f"C++ Scheduler returned non-200 status: {response.status_code}"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to connect to C++ Scheduler: {e}")
            return False

    async def submit_llm_task(
        self, prompt: str, model: str = "default", **kwargs
    ) -> Dict[str, Any]:
        """
        Submit an LLM inference task.
        """
        payload = {"prompt": prompt, "model": model, **kwargs}
        return await self._send_request("POST", "/api/v1/llm/generate", json=payload)

    async def submit_tts_task(
        self, text: str, voice_id: str, **kwargs
    ) -> Dict[str, Any]:
        """
        Submit a TTS synthesis task.
        """
        payload = {"text": text, "voice_id": voice_id, **kwargs}
        return await self._send_request("POST", "/api/v1/tts/synthesize", json=payload)

    async def submit_image_task(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Submit an image generation task.
        """
        payload = {"prompt": prompt, **kwargs}
        return await self._send_request("POST", "/api/v1/image/generate", json=payload)

    async def _send_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Dict[str, Any]:
        if not self._is_connected:
            # Try to reconnect once
            if not await self.connect():
                raise ConnectionError("C++ Scheduler is not reachable")

        try:
            response = await self.client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Request to C++ Scheduler failed: {e}")
            raise

    async def close(self):
        await self.client.aclose()
