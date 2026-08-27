#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速测试 Qwen3-TTS 云端声音克隆功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import base64

async def test_api_connectivity():
    """测试 API 连通性"""
    print("=" * 60)
    print("测试 1: API 连通性测试")
    print("=" * 60)
    
    from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
    
    engine = Qwen3TTSCloudEngine()
    
    print(f"API Key: {engine.api_key[:15]}...{engine.api_key[-4:]}")
    print(f"模型：{engine.model}")
    print(f"Base URL: {engine.base_url}")
    
    await engine.initialize()
    
    status = engine.get_status()
    print(f"\n初始化状态：{status['status']}")
    print(f"会话激活：{status['session_active']}")
    
    if status['api_key_configured'] and status['session_active']:
        print("✅ API 连通性正常")
        return True
    else:
        print("❌ API 连通性异常")
        return False


async def test_basic_synthesis():
    """测试基础语音合成（不克隆）"""
    print("\n" + "=" * 60)
    print("测试 2: 基础语音合成")
    print("=" * 60)
    
    from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
    
    engine = Qwen3TTSCloudEngine()
    await engine.initialize()
    
    try:
        text = "你好，这是阿里云 Qwen3-TTS 云端语音合成测试。"
        print(f"合成文本：{text}")
        
        audio_data = await engine.synthesize(
            text=text,
            voice="Cherry"  # 使用正确的音色名称
        )
        
        duration = len(audio_data) / 24000
        print(f"✅ 合成成功！")
        print(f"  音频时长：{duration:.2f}秒")
        print(f"  采样率：24000 Hz")
        print(f"  数据大小：{len(audio_data)} 采样点")
        
        # 保存
        import soundfile as sf
        output_file = "output/qwen3_tts_basic.wav"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        sf.write(output_file, audio_data, 24000)
        print(f"  保存至：{output_file}")
        
        await engine.shutdown()
        return True
        
    except Exception as e:
        print(f"❌ 合成失败：{e}")
        import traceback
        traceback.print_exc()
        await engine.shutdown()
        return False


async def test_voice_cloning():
    """测试声音克隆"""
    print("\n" + "=" * 60)
    print("测试 3: 声音克隆功能")
    print("=" * 60)
    
    from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
    from config.integrated_config import get_settings
    
    engine = Qwen3TTSCloudEngine()
    await engine.initialize()
    
    # 查找参考音频 - 优先使用根目录 ref_audio 文件夹
    ref_audio_path = None
    
    # 1. 检查根目录 ref_audio 文件夹
    root_ref_audio = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ref_audio", "female")
    if os.path.exists(root_ref_audio):
        # 查找第一个 wav 文件
        for f in os.listdir(root_ref_audio):
            if f.endswith(".wav") and not f.startswith("."):
                ref_audio_path = os.path.join(root_ref_audio, f)
                print(f"找到根目录参考音频：{ref_audio_path}")
                break
    
    # 2. 如果根目录没有，检查配置文件
    if not ref_audio_path:
        settings = get_settings()
        ref_audio_path = settings.voice.reference_audio
        
        if not ref_audio_path or not os.path.exists(ref_audio_path):
            # 3. 尝试 models/voice/reference 目录
            test_ref = "models/voice/reference/test.wav"
            if os.path.exists(test_ref):
                ref_audio_path = test_ref
    
    if not ref_audio_path or not os.path.exists(ref_audio_path):
        print("⚠ 未找到参考音频，跳过声音克隆测试")
        print("\n提示：请准备一个 5-30 秒的参考音频文件")
        print("并在 .env 中设置 XIAOYOU_VOICE__REFERENCE_AUDIO 路径")
        await engine.shutdown()
        return None
    
    print(f"参考音频：{ref_audio_path}")
    
    # 尝试读取参考文本
    ref_text = None
    txt_path = os.path.splitext(ref_audio_path)[0] + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path, 'r', encoding='utf-8') as f:
            ref_text = f.read().strip()
        print(f"参考文本：{ref_text[:50]}...")
    
    try:
        text = "这是用克隆声音说的话，听起来应该和参考音频很像。"
        print(f"\n合成文本：{text}")
        
        audio_data = await engine.synthesize(
            text=text,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            speed=1.0,
            volume=1.0
        )
        
        duration = len(audio_data) / 24000
        print(f"✅ 声音克隆成功！")
        print(f"  音频时长：{duration:.2f}秒")
        
        # 保存
        import soundfile as sf
        output_file = "output/qwen3_tts_clone.wav"
        sf.write(output_file, audio_data, 24000)
        print(f"  保存至：{output_file}")
        
        await engine.shutdown()
        return True
        
    except Exception as e:
        print(f"❌ 声音克隆失败：{e}")
        import traceback
        traceback.print_exc()
        await engine.shutdown()
        return False


async def main():
    """运行所有测试"""
    print("\n阿里云 DashScope Qwen3-TTS 声音克隆功能测试\n")
    
    # 测试 1: API 连通性
    test1 = await test_api_connectivity()
    
    # 测试 2: 基础合成
    if test1:
        test2 = await test_basic_synthesis()
    else:
        print("\n⚠ API 连通性失败，跳过后续测试")
        return 1
    
    # 测试 3: 声音克隆
    if test2:
        test3 = await test_voice_cloning()
    else:
        print("\n⚠ 基础合成失败，跳过声音克隆测试")
        return 1
    
    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"API 连通性：{'✅ 通过' if test1 else '❌ 失败'}")
    print(f"基础合成：{'✅ 通过' if test2 else '❌ 失败'}")
    print(f"声音克隆：{'✅ 通过' if test3 else '❌ 失败' if test3 is False else '⚠ 未测试'}")
    
    if test1 and test2:
        print("\n✅ Qwen3-TTS 云端服务可用！")
        if test3:
            print("✅ 声音克隆功能可用！")
        elif test3 is None:
            print("⚠ 声音克隆功能理论上可用，但缺少参考音频")
        return 0
    else:
        print("\n❌ 测试失败，请检查配置")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
