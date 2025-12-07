import asyncio
import aiohttp
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TEST_TTS")

async def test_tts_initialization():
    try:
        # Import TTS Manager (this will trigger config loading)
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from core.voice.tts_engine import get_tts_manager
        from config.integrated_config import get_settings
        
        # Verify Settings
        settings = get_settings()
        logger.info(f"Loaded GPT Model Path: {settings.voice.gpt_model_path}")
        logger.info(f"Loaded SoVITS Model Path: {settings.voice.sovits_model_path}")
        
        if not settings.voice.gpt_model_path or not settings.voice.sovits_model_path:
            logger.error("Model paths not loaded in configuration!")
            return False

        # Initialize Manager
        manager = get_tts_manager()
        await manager.initialize()
        
        # Check if it's GPTSoVITSEngine
        if manager.engine.__class__.__name__ == "GPTSoVITSEngine":
            logger.info("Engine is GPTSoVITSEngine")
        else:
            logger.error(f"Engine is {manager.engine.__class__.__name__}, expected GPTSoVITSEngine")
            return False

        # Verify API connectivity (Optional: synthesize a short text)
        logger.info("Attempting synthesis...")
        audio = await manager.synthesize("测试音频", lang="zh")
        if audio.any():
            logger.info(f"Synthesis successful. Audio shape: {audio.shape}")
            return True
        else:
            logger.error("Synthesis returned empty audio.")
            return False

    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_tts_initialization())
    if success:
        print("TEST_SUCCESS")
        sys.exit(0)
    else:
        print("TEST_FAILURE")
        sys.exit(1)
