import asyncio
import os
import time
import sys
import logging
from concurrent.futures import ThreadPoolExecutor
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.slow]


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )


# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.voice.stt_engine import STTManager, HuggingFaceSTTEngine
from core.voice.tts_engine import TTSManager
from core.modules.llm.module import LLMModule
# from core.modules.image.module import ImageGenModule

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SystemTest")

async def test_stt():
    logger.info("=== Testing STT ===")
    stt_manager = STTManager()
    await stt_manager.initialize()
    
    if isinstance(stt_manager.engine, HuggingFaceSTTEngine):
        logger.info("SUCCESS: STT Manager is using HuggingFaceSTTEngine")
    else:
        logger.warning(f"WARNING: STT Manager is using {type(stt_manager.engine)}")

    # Create a dummy audio file if not exists
    # We need a real wav for librosa
    import numpy as np
    import soundfile as sf
    import io
    
    sr = 16000
    t = np.linspace(0, 3, int(sr * 3))
    # Generate a simple sine wave (beep)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)
    
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format='WAV')
    audio_data = buf.getvalue()
    
    start_time = time.time()
    result = await stt_manager.transcribe(audio_data, language="zh")
    latency = time.time() - start_time
    logger.info(f"STT Result: {result}")
    logger.info(f"STT Latency: {latency:.4f}s")
    return result

async def test_tts():
    logger.info("=== Testing TTS ===")
    tts_manager = TTSManager()
    await tts_manager.initialize()
    
    text = "这是一个测试语音合成的句子。"
    start_time = time.time()
    # Note: TTS might be calling the running API
    audio = await tts_manager.synthesize(text)
    latency = time.time() - start_time
    
    if len(audio) > 0:
        logger.info(f"TTS Success: Generated {len(audio)} samples")
    else:
        logger.error("TTS Failed: No audio generated")
    
    logger.info(f"TTS Latency: {latency:.4f}s")
    return len(audio)

async def test_llm():
    logger.info("=== Testing LLM ===")
    # We might need to initialize the LLM module or use a client if it's a service
    # Assuming direct module usage for now or skipping if too heavy
    logger.info("Skipping heavy LLM load in this test script to avoid OOM during STT verification")
    return "Skipped"

async def test_image_gen():
    logger.info("=== Testing Image Gen ===")
    # Similar to LLM, verify connectivity
    logger.info("Skipping Image Gen in this test script")
    return "Skipped"

async def main():
    logger.info("Starting System Verification")
    
    # 1. Initialize Managers
    tts_manager = TTSManager()
    stt_manager = STTManager()
    
    await tts_manager.initialize()
    await stt_manager.initialize()

    # 2. Test Loop: TTS -> STT
    test_text = "这是一个测试语音合成与识别闭环的句子。"
    logger.info(f"Original Text: {test_text}")
    
    # Generate Audio
    start_time = time.time()
    audio_data = await tts_manager.synthesize(test_text)
    tts_latency = time.time() - start_time
    logger.info(f"TTS Latency: {tts_latency:.4f}s")
    
    if len(audio_data) == 0:
        logger.error("TTS Failed: No audio generated")
        return

    # Transcribe Audio
    # GPT-SoVITS returns float32 numpy array, we need bytes for STT (usually wav bytes or raw bytes depending on implementation)
    # HuggingFaceSTTEngine expects bytes and uses librosa.load on a BytesIO
    # We need to convert numpy array to wav bytes
    import io
    import soundfile as sf
    
    buf = io.BytesIO()
    # GPT-SoVITS usually outputs 32000Hz
    sf.write(buf, audio_data, 32000, format='WAV')
    wav_bytes = buf.getvalue()
    
    start_time = time.time()
    stt_result = await stt_manager.transcribe(wav_bytes, language="zh")
    stt_latency = time.time() - start_time
    
    logger.info(f"STT Result: {stt_result}")
    logger.info(f"STT Latency: {stt_latency:.4f}s")
    
    # Simple verification
    if stt_result.get("text"):
        logger.info("Loop Verification: SUCCESS (Text detected)")
    else:
        logger.warning("Loop Verification: POTENTIAL FAILURE (No text detected)")

    logger.info("System Verification Completed")

if __name__ == "__main__":
    asyncio.run(main())
