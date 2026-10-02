import asyncio
import logging
import sys
import os
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.slow]


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )


# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.voice.tts_engine import get_tts_manager
from core.voice.stt_engine import get_stt_manager
from core.utils.logger import get_logger

logger = get_logger("TEST_MIGRATION")
logging.basicConfig(level=logging.INFO)

async def test_tts_migration():
    logger.info("Testing TTS Migration...")
    manager = get_tts_manager()
    await manager.initialize()
    
    # Test move to CPU
    logger.info("Moving TTS to CPU...")
    await manager.move_to_cpu()
    logger.info("TTS moved to CPU (check server logs/response)")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Test move to GPU
    logger.info("Moving TTS to GPU...")
    await manager.move_to_gpu()
    logger.info("TTS moved to GPU (check server logs/response)")
    
    await manager.shutdown()

async def test_stt_migration():
    logger.info("Testing STT Migration...")
    manager = get_stt_manager()
    await manager.initialize()
    
    logger.info(f"Current STT Device: {manager.engine.device}")
    
    # Test move to CPU
    logger.info("Moving STT to CPU...")
    await manager.move_to_cpu()
    logger.info(f"Current STT Device: {manager.engine.device}")
    assert manager.engine.device == "cpu"
    
    # Wait a bit
    await asyncio.sleep(1)
    
    # Test move to GPU
    logger.info("Moving STT to GPU...")
    await manager.move_to_gpu()
    logger.info(f"Current STT Device: {manager.engine.device}")
    # Note: might stay on CPU if CUDA not available
    
    await manager.shutdown()

async def main():
    try:
        await test_tts_migration()
    except Exception as e:
        logger.error(f"TTS Migration Test Failed: {e}")
        
    try:
        await test_stt_migration()
    except Exception as e:
        logger.error(f"STT Migration Test Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
