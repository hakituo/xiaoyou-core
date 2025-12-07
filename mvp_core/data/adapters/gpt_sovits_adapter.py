import logging
import aiohttp
import os
import uuid
from mvp_core.domain.interfaces.base_interfaces import TTSInterface

logger = logging.getLogger("GPTSoVITSAdapter")

class GPTSoVITSAdapter(TTSInterface):
    def __init__(self, api_url: str = "http://127.0.0.1:9880/tts"):
        self.api_url = api_url
        self.output_dir = "temp/tts_output"
        os.makedirs(self.output_dir, exist_ok=True)

    async def synthesize(self, text: str, emotion: str = None, **kwargs) -> str:
        """
        Synthesize speech using local GPT-SoVITS server.
        Returns the path to the saved audio file.
        """
        # Construct parameters
        # This assumes the standard GPT-SoVITS API
        params = {
            "text": text,
            "text_lang": kwargs.get("lang", "zh"),
            "ref_audio_path": kwargs.get("ref_audio_path", r"d:\AI\xiaoyou-core\ref_audio\female\ref_calm.wav"),
            "prompt_text": kwargs.get("prompt_text", "这是中文纯语音测试，不包含英文内容"),
            "prompt_lang": kwargs.get("prompt_lang", "zh"),
        }
        
        # Add emotion or reference audio if supported by the specific API setup
        # For now, we stick to basic text-to-speech
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"GPT-SoVITS API Error: {response.status} - {error_text}")
                        raise Exception(f"TTS API failed with status {response.status}")
                    
                    content = await response.read()
                    
                    filename = f"{uuid.uuid4()}.wav"
                    filepath = os.path.join(self.output_dir, filename)
                    
                    with open(filepath, "wb") as f:
                        f.write(content)
                        
                    return filepath
        except Exception as e:
            logger.error(f"Failed to connect to GPT-SoVITS: {e}")
            # Fallback or re-raise depending on requirement. 
            # Since this is a benchmark for "Real" mode, we should probably raise.
            raise
