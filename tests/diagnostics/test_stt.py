import os
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[1]

def test_stt():
    async def _run():
        sys.path.append(str(project_root))

        from core.voice.stt_engine import get_stt_manager
        from core.utils.logger import get_logger

        logger = get_logger("TEST_STT")
        stt_manager = get_stt_manager()
        logger.info("Initializing STT Manager...")
        await stt_manager.initialize()

        logger.info(f"Using engine: {type(stt_manager.engine).__name__}")

        voice_dir = project_root / "output" / "voice"
        if not voice_dir.exists():
            logger.error(f"Voice directory not found: {voice_dir}")
            return

        wav_files = list(voice_dir.glob("*.wav"))
        if not wav_files:
            logger.error("No .wav files found in output/voice")
            return

        test_file = max(wav_files, key=os.path.getmtime)
        logger.info(f"Testing with file: {test_file.name}")

        with open(test_file, "rb") as f:
            audio_data = f.read()

        logger.info(f"Audio data size: {len(audio_data)} bytes")

        logger.info("Starting transcription...")
        try:
            import time

            start_time = time.time()
            result = await stt_manager.transcribe(audio_data, language="zh")
            end_time = time.time()

            logger.info(f"Transcription finished in {end_time - start_time:.2f}s")
            logger.info(f"Result: {result}")

            if result.get("text"):
                logger.info(f"Transcribed text: {result['text']}")
            else:
                logger.warning("No text transcribed.")
                if "error" in result:
                    logger.error(f"Error: {result['error']}")

        except Exception as e:
            logger.error(f"An exception occurred during transcription: {e}")
            import traceback

            traceback.print_exc()

    asyncio.run(_run())

if __name__ == "__main__":
    test_stt()
