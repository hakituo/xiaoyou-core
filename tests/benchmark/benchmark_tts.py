
import asyncio
import time

from multimodal.tts_manager import get_tts_manager
from core.utils.logger import get_logger

logger = get_logger("TTS_BENCHMARK")

async def benchmark_tts():
    print("\n" + "="*50)
    print("      TTS Performance Benchmark (Real Engine)")
    print("="*50)
    
    mgr = get_tts_manager()
    print("  TTSManager instance retrieved.")
    
    # 强制初始化
    print("  Initializing real engine...")
    try:
        if not mgr.new_engine:
            from core.voice.tts_engine import TTSManager as NewTTSManager
            mgr.new_engine = NewTTSManager()
        
        await mgr.new_engine.initialize()
        mgr._initialized = True
        print("  ✅ Real engine initialized.")
    except Exception as e:
        print(f"  ❌ Failed to initialize real engine: {e}")
        print("  请确保 GPT-SoVITS 服务已在 127.0.0.1:9880 启动。")
        return

    # 1. Test Text
    test_text_cold = "这是一段全新的文本，用于测试冷加载合成速度。"
    test_text_hot = "这是另一段全新的文本，用于测试热加载合成速度。"
    
    print("\n[测试信息]")
    print(f"  冷加载文本: {test_text_cold}")
    print(f"  热加载文本: {test_text_hot}")

    # 2. Cold Start (First time after initialization)
    print("\n[1/4] 冷加载合成 (引擎刚启动后的首次请求)...")
    start_time = time.perf_counter()
    try:
        result_cold = await mgr.async_text_to_speech(test_text_cold)
        end_time = time.perf_counter()
        if result_cold:
            duration_cold = end_time - start_time
            print(f"  ✅ 成功! ⏱️ 耗时: {duration_cold:.4f}s")
        else:
            print("  ❌ 失败")
            return
    except Exception as e:
        print(f"  ❌ 报错: {e}")
        return

    # 3. Hot Start (Subsequent request)
    print("\n[2/4] 热加载合成 (引擎已就绪，合成新文本)...")
    start_time = time.perf_counter()
    try:
        result_hot = await mgr.async_text_to_speech(test_text_hot)
        end_time = time.perf_counter()
        if result_hot:
            duration_hot = end_time - start_time
            print(f"  ✅ 成功! ⏱️ 耗时: {duration_hot:.4f}s")
        else:
            print("  ❌ 失败")
    except Exception as e:
        print(f"  ❌ 报错: {e}")

    # 4. Cached Run
    print("\n[3/4] 缓存读取 (完全命中本地缓存)...")
    start_time = time.perf_counter()
    try:
        result_cached = await mgr.async_text_to_speech(test_text_hot)
        end_time = time.perf_counter()
        if result_cached:
            duration_cached = end_time - start_time
            print(f"  ✅ 成功! ⏱️ 耗时: {duration_cached:.4f}s")
        else:
            print("  ❌ 失败")
    except Exception as e:
        print(f"  ❌ 报错: {e}")

    # 5. Deduplication Run
    print("\n[4/4] 并发去重测试 (同时发起3个相同新请求)...")
    concurrent_text = f"并发测试文本 {int(time.time())}"
    start_time = time.perf_counter()
    tasks = [mgr.async_text_to_speech(concurrent_text) for _ in range(3)]
    results = await asyncio.gather(*tasks)
    end_time = time.perf_counter()
    if all(results) and len(set(results)) == 1:
        print(f"  ✅ 成功! ⏱️ 总耗时: {end_time - start_time:.4f}s")
    else:
        print("  ❌ 失败或并发结果不一致")

    print("\n" + "="*50)
    print("      测试完成")
    print("="*50)

if __name__ == "__main__":
    try:
        asyncio.run(benchmark_tts())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n程序异常退出: {e}")
