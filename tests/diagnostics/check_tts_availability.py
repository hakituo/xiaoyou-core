import os
import sys
import asyncio
from pathlib import Path

# 添加项目根目录
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.integrated_config import get_settings
from core.voice.tts_engine import Qwen3TTSEngine
from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine

async def check_tts():
    print("=" * 60)
    print("TTS Availability Check")
    print("=" * 60)
    
    settings = get_settings()
    provider = settings.voice.tts.provider
    model = settings.voice.tts.model
    
    print(f"Configured Provider: {provider}")
    print(f"Configured Model: {model}")
    
    # 1. Check Local Qwen3-TTS
    print("\n[Local Qwen3-TTS Check]")
    try:
        import qwen_tts
        print("✅ Module 'qwen_tts' found.")
    except ImportError:
        print("❌ Module 'qwen_tts' NOT found. (Required for local inference)")
    
    local_engine = Qwen3TTSEngine()
    model_path, exists = local_engine._resolve_model_path()
    if exists:
        print(f"✅ Model path found: {model_path}")
    else:
        print(f"❌ Model path NOT found: {model_path}")
        
    # 2. Check Cloud Qwen3-TTS
    print("\n[Cloud Qwen3-TTS Check]")
    cloud_engine = Qwen3TTSCloudEngine()
    api_key = cloud_engine.api_key
    if api_key:
        print(f"✅ API Key found: {api_key[:8]}...")
        # Try a quick synthesis if key exists
        try:
            print("Trying cloud synthesis...")
            text = "你好，这是一次云端语音测试。"
            audio_bytes = await cloud_engine.synthesize_bytes(text)
            if audio_bytes and len(audio_bytes) > 0:
                print(f"✅ Cloud synthesis successful ({len(audio_bytes)} bytes)")
                output_path = ROOT / "output" / "test_cloud_tts.mp3"
                output_path.parent.mkdir(exist_ok=True, parents=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                print(f"   Saved to: {output_path}")
            else:
                print("❌ Cloud synthesis returned empty data.")
        except Exception as e:
            print(f"❌ Cloud synthesis failed: {e}")
        
    # 3. Check TTSManager Logic (Integration Check)
    print("\n[TTSManager Fallback Integration Check]")
    try:
        from core.voice.tts_engine import get_tts_manager
        # Qwen3TTSEngine and Qwen3TTSCloudEngine are already imported at top level
        
        manager = get_tts_manager()
        # Force re-initialization
        manager.initialized = False
        manager.engine = None
        
        await manager.initialize()
        
        if isinstance(manager.engine, Qwen3TTSCloudEngine):
            print("✅ TTSManager successfully fell back to Qwen3 Cloud Engine!")
        elif isinstance(manager.engine, Qwen3TTSEngine):
            print("✅ TTSManager initialized Local Qwen3 Engine (Surprising given previous check).")
        else:
            engine_name = type(manager.engine).__name__ if manager.engine else "None"
            print(f"⚠️ TTSManager selected: {engine_name}")
            
    except Exception as e:
        print(f"❌ TTSManager integration check failed: {e}")

if __name__ == "__main__":
    asyncio.run(check_tts())
