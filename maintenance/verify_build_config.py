import os
from core.core_engine.config_manager import ConfigManager
from core.utils.logger import get_logger

# Mock sys.frozen for testing if we can, but simpler to just test the logic
# We will test the source logic first.

logger = get_logger("VERIFY")


def test_config():
    print("Testing Config Manager Auto-detection...")
    cm = ConfigManager()
    cm.initialize()

    settings = cm._settings

    print("\n=== Model Detection Results ===")
    print(f"LLM Path: {settings.model.text_path}")
    print(f"SD Path: {settings.model.image_gen_path}")
    print(f"Vision Path: {settings.model.vision_path}")

    if hasattr(settings, "voice"):
        print(f"TTS GPT Path: {settings.voice.gpt_model_path}")
        print(f"TTS SoVITS Path: {settings.voice.sovits_model_path}")
    else:
        print("TTS Config: Not found in settings")

    print(f"Whisper Path: {settings.model.whisper_path}")

    print("\n=== Verification ===")
    missing = []
    if not settings.model.text_path or not os.path.exists(settings.model.text_path):
        missing.append("LLM")
    if not settings.model.image_gen_path or not os.path.exists(
        settings.model.image_gen_path
    ):
        missing.append("Stable Diffusion")
    # Vision is optional or might be a dir
    if settings.model.vision_path and not os.path.exists(settings.model.vision_path):
        missing.append("Vision (Path invalid)")

    if hasattr(settings, "voice"):
        if not settings.voice.gpt_model_path or not os.path.exists(
            settings.voice.gpt_model_path
        ):
            missing.append("TTS GPT")
        if not settings.voice.sovits_model_path or not os.path.exists(
            settings.voice.sovits_model_path
        ):
            missing.append("TTS SoVITS")

    if missing:
        print(f"❌ Missing or invalid models: {', '.join(missing)}")
    else:
        print("✅ All key models detected and paths exist.")


if __name__ == "__main__":
    test_config()
