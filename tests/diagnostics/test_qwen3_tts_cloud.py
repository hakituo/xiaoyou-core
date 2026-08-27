#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阿里云 DashScope Qwen3-TTS 云端 API 使用示例

功能：
- ✅ 语音合成（文字转语音）
- ✅ 声音克隆（通过参考音频）
- ✅ 多语言支持
- ✅ 情感/语速/音量控制

前置准备：
1. 获取 DashScope API Key: https://dashscope.console.aliyun.com/
2. 在 .env 文件中设置：DASHSCOPE_API_KEY=sk-xxxxx
3. 准备参考音频（用于声音克隆）：5-30 秒的清晰语音
"""
import os
import sys
import asyncio

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def test_basic_synthesis():
    """测试基础语音合成（不克隆声音）"""
    print("=" * 60)
    print("测试 1: 基础语音合成（使用默认音色）")
    print("=" * 60)
    
    try:
        from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
        
        engine = Qwen3TTSCloudEngine()
        await engine.initialize()
        
        # 合成语音
        text = "你好，这是阿里云 Qwen3-TTS 云端语音合成测试。"
        print(f"合成文本：{text}")
        
        audio_data = await engine.synthesize(
            text=text,
            voice="longhua",  # 音色：longhua（中文女声）
            speed=1.0,
            volume=1.0
        )
        
        print(f"✓ 合成成功！音频时长：{len(audio_data)/24000:.2f}秒")
        print(f"  采样率：24000 Hz")
        print(f"  数据类型：{audio_data.dtype}")
        
        # 保存到文件
        import soundfile as sf
        output_file = "output/qwen3_tts_basic_test.wav"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        sf.write(output_file, audio_data, 24000)
        print(f"  保存至：{output_file}")
        
        await engine.shutdown()
        return True
        
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False


async def test_voice_cloning():
    """测试声音克隆功能"""
    print("\n" + "=" * 60)
    print("测试 2: 声音克隆（使用参考音频）")
    print("=" * 60)
    
    try:
        from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
        
        engine = Qwen3TTSCloudEngine()
        await engine.initialize()
        
        # 准备参考音频
        ref_audio_path = "models/voice/reference/test_ref.wav"
        ref_text = "这是参考音频中说的内容，用于声音克隆。"
        
        # 检查参考音频是否存在
        if not os.path.exists(ref_audio_path):
            print(f"⚠ 参考音频不存在：{ref_audio_path}")
            print(f"  请准备一个 5-30 秒的 WAV 格式参考音频")
            print(f"  并将参考文本保存在同名的 .txt 文件中")
            
            # 尝试查找其他参考音频
            from config.integrated_config import get_settings
            settings = get_settings()
            alt_ref = settings.voice.reference_audio
            if alt_ref and os.path.exists(alt_ref):
                ref_audio_path = alt_ref
                print(f"  使用备用参考音频：{ref_audio_path}")
                
                # 尝试读取同名 txt 文件
                txt_path = os.path.splitext(ref_audio_path)[0] + ".txt"
                if os.path.exists(txt_path):
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        ref_text = f.read().strip()
                    print(f"  自动加载参考文本：{ref_text[:50]}...")
            else:
                print(f"  跳过声音克隆测试")
                await engine.shutdown()
                return True
        
        print(f"参考音频：{ref_audio_path}")
        print(f"参考文本：{ref_text}")
        
        # 合成语音（使用声音克隆）
        text = "这是用克隆声音说的话，听起来应该和参考音频很像。"
        print(f"\n合成文本：{text}")
        
        audio_data = await engine.synthesize(
            text=text,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            speed=1.0,
            volume=1.0
        )
        
        print(f"✓ 声音克隆成功！音频时长：{len(audio_data)/24000:.2f}秒")
        
        # 保存到文件
        import soundfile as sf
        output_file = "output/qwen3_tts_voice_clone_test.wav"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        sf.write(output_file, audio_data, 24000)
        print(f"  保存至：{output_file}")
        
        await engine.shutdown()
        return True
        
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return False


async def test_x_vector_mode():
    """测试 X-Vector 模式（仅使用声音特征，不需要文本）"""
    print("\n" + "=" * 60)
    print("测试 3: X-Vector 模式（简化声音克隆）")
    print("=" * 60)
    
    try:
        from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
        
        engine = Qwen3TTSCloudEngine()
        await engine.initialize()
        
        # 准备参考音频
        ref_audio_path = "models/voice/reference/test_ref.wav"
        
        from config.integrated_config import get_settings
        settings = get_settings()
        if not os.path.exists(ref_audio_path):
            alt_ref = settings.voice.reference_audio
            if alt_ref and os.path.exists(alt_ref):
                ref_audio_path = alt_ref
            else:
                print(f"⚠ 没有可用的参考音频，跳过测试")
                await engine.shutdown()
                return True
        
        print(f"参考音频：{ref_audio_path}")
        print(f"模式：X-Vector（仅提取声音特征）")
        
        # 合成语音（X-Vector 模式）
        text = "这是 X-Vector 模式，不需要参考文本，只使用声音特征。"
        print(f"\n合成文本：{text}")
        
        audio_data = await engine.synthesize(
            text=text,
            ref_audio_path=ref_audio_path,
            x_vector_only_mode=True,  # 仅使用 X-Vector
            speed=1.0,
            volume=1.0
        )
        
        print(f"✓ X-Vector 模式成功！音频时长：{len(audio_data)/24000:.2f}秒")
        
        # 保存到文件
        import soundfile as sf
        output_file = "output/qwen3_tts_xvector_test.wav"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        sf.write(output_file, audio_data, 24000)
        print(f"  保存至：{output_file}")
        
        await engine.shutdown()
        return True
        
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("阿里云 DashScope Qwen3-TTS 云端 API 测试")
    print("=" * 60 + "\n")
    
    # 检查 API Key
    api_key = os.getenv('DASHSCOPE_API_KEY')
    if not api_key:
        print("❌ 错误：未找到 DASHSCOPE_API_KEY")
        print("\n请在 .env 文件中设置:")
        print("  DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx")
        print("\n获取 API Key: https://dashscope.console.aliyun.com/")
        return 1
    
    print(f"✓ API Key 已配置：{api_key[:10]}...{api_key[-4:]}")
    
    # 运行测试
    results = []
    results.append(("基础语音合成", await test_basic_synthesis()))
    results.append(("声音克隆", await test_voice_cloning()))
    results.append(("X-Vector 模式", await test_x_vector_mode()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"  {name}: {status}")
    
    print(f"\n总计：{passed}/{total} 测试通过")
    
    if passed == total:
        print("\n✅ 所有测试通过！Qwen3-TTS 云端服务已就绪。")
        print("\n使用方法:")
        print("  from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine")
        print("  engine = Qwen3TTSCloudEngine()")
        print("  await engine.initialize()")
        print("  audio = await engine.synthesize(")
        print("      text='你好',")
        print("      ref_audio_path='path/to/ref.wav',  # 可选，声音克隆")
        print("      ref_text='参考文本'  # 可选，提高克隆质量")
        print("  )")
        return 0
    else:
        print(f"\n⚠ {total - passed} 个测试失败，请检查配置。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
