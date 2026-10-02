#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
调试 Qwen3-TTS 声音克隆功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json

async def test_clone_debug():
    """调试声音克隆"""
    from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine
    
    engine = Qwen3TTSCloudEngine()
    await engine.initialize()
    
    # 参考音频
    ref_audio_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ref_audio", "female", "huanhuan.wav")
    ref_text_path = os.path.splitext(ref_audio_path)[0] + ".txt"
    
    with open(ref_text_path, 'r', encoding='utf-8') as f:
        ref_text = f.read().strip()
    
    print(f"参考音频：{ref_audio_path}")
    print(f"参考文本：{ref_text}")
    
    # 构建 payload 看看
    payload = {
        "model": engine.model,
        "input": {
            "text": "这是用克隆声音说的话。",
            "voice": engine.default_voice,
            "language_type": engine.default_language,
        }
    }
    
    # 添加参考音频
    if ref_audio_path and os.path.exists(ref_audio_path):
        ref_audio_data = await engine._encode_audio_to_base64(ref_audio_path)
        payload["input"]["ref_audio"] = ref_audio_data
        if ref_text:
            payload["input"]["ref_text"] = ref_text
    
    print("\n=== 发送的 Payload ===")
    # 为了可读性，不打印完整的 base64
    payload_debug = payload.copy()
    if "ref_audio" in payload_debug.get("input", {}):
        audio_data = payload_debug["input"]["ref_audio"]
        if isinstance(audio_data, str) and len(audio_data) > 50:
            payload_debug["input"]["ref_audio"] = f"{audio_data[:50]}...[truncated]"
    
    print(json.dumps(payload_debug, indent=2, ensure_ascii=False))
    
    # 实际调用
    print("\n=== 开始调用 ===")
    try:
        audio_data = await engine.synthesize(
            text="这是用克隆声音说的话，听起来应该和参考音频很像。",
            ref_audio_path=ref_audio_path,
            ref_text=ref_text
        )
        print(f"✅ 合成成功！音频时长：{len(audio_data)/24000:.2f}秒")
        
        # 保存
        import soundfile as sf
        output_file = "output/qwen3_tts_clone_debug.wav"
        sf.write(output_file, audio_data, 24000)
        print(f"保存至：{output_file}")
        
    except Exception as e:
        print(f"❌ 失败：{e}")
        import traceback
        traceback.print_exc()
    
    await engine.shutdown()

if __name__ == "__main__":
    asyncio.run(test_clone_debug())
