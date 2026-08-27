#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 priority_analysis LLM 调用超时问题
复现 Active Care 优先级分析失败的场景
"""
import asyncio
import time
import sys
from pathlib import Path

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_priority_analysis_llm():
    """测试 priority_analysis 模型调用"""
    print("=" * 60)
    print("测试 priority_analysis LLM 调用")
    print("=" * 60)
    
    # 1. 获取配置的模型
    from config.model_config import get_priority_analysis_model
    model_path = get_priority_analysis_model()
    print(f"\n[1] 配置的 priority_analysis 模型: {model_path}")
    
    # 2. 获取 LLM 模块
    from core.llm import get_llm_module
    llm = get_llm_module()
    print(f"[2] LLM 模块加载成功: {llm}")
    
    # 3. 构建测试 prompt（模拟 priority_analyzer 的调用）
    system_prompt = """你是一个优先级分析助手。请分析以下候选话题的优先级，返回 JSON 格式。
返回格式: {"priorities": [{"id": "xxx", "score": 80, "reason": "xxx"}]}"""

    user_prompt = """当前时间: 2026-06-17 23:50
候选话题:
1. urgent:hungry - 突发状态：hungry (score: 84)
2. portrait:activity - 补齐画像：活动 (score: 70)
3. portrait:mood - 补齐画像：心情 (score: 70)

请分析并返回优先级排序。"""

    print(f"\n[3] 开始调用 LLM...")
    print(f"    模型: {model_path}")
    print(f"    超时: 20秒")
    
    start_time = time.time()
    try:
        raw_text = await asyncio.wait_for(
            llm.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
                max_new_tokens=420,
                model_path=model_path or None,
            ),
            timeout=20.0,
        )
        elapsed = time.time() - start_time
        
        if isinstance(raw_text, dict):
            if raw_text.get("status") == "success":
                raw_text = str(raw_text.get("response") or "")
            else:
                raw_text = ""
        
        print(f"\n[4] LLM 调用成功!")
        print(f"    耗时: {elapsed:.2f}秒")
        print(f"    响应: {raw_text[:500]}")
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"\n[4] ❌ LLM 调用超时!")
        print(f"    耗时: {elapsed:.2f}秒")
        print(f"    超时阈值: 20秒")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n[4] ❌ LLM 调用失败!")
        print(f"    耗时: {elapsed:.2f}秒")
        print(f"    错误: {type(e).__name__}: {e}")


async def test_direct_api_call():
    """直接测试 API 调用"""
    print("\n" + "=" * 60)
    print("直接测试 SiliconFlow API 调用")
    print("=" * 60)
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    # 获取 API key
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("[跳过] 未找到 SILICONFLOW_API_KEY")
        return
    
    print(f"\n[1] API Key: {api_key[:10]}...")
    
    import aiohttp
    
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-ai/DeepSeek-V3.2",
        "messages": [
            {"role": "system", "content": "你是一个优先级分析助手。返回 JSON 格式。"},
            {"role": "user", "content": "分析优先级: hungry(84), activity(70), mood(70)"}
        ],
        "temperature": 0.25,
        "max_tokens": 420
    }
    
    print(f"[2] 开始直接 API 调用...")
    print(f"    URL: {url}")
    print(f"    模型: deepseek-ai/DeepSeek-V3.2")
    
    start_time = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                elapsed = time.time() - start_time
                if resp.status == 200:
                    result = await resp.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"\n[3] ✅ API 调用成功!")
                    print(f"    耗时: {elapsed:.2f}秒")
                    print(f"    响应: {content[:300]}")
                else:
                    text = await resp.text()
                    print(f"\n[3] ❌ API 调用失败!")
                    print(f"    耗时: {elapsed:.2f}秒")
                    print(f"    状态码: {resp.status}")
                    print(f"    响应: {text[:300]}")
                    
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"\n[3] ❌ API 调用超时!")
        print(f"    耗时: {elapsed:.2f}秒")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n[3] ❌ API 调用异常!")
        print(f"    耗时: {elapsed:.2f}秒")
        print(f"    错误: {type(e).__name__}: {e}")


async def main():
    print("Active Care Priority Analysis 超时测试")
    print("=" * 60)
    
    # 测试 1: 通过 LLM 模块调用
    await test_priority_analysis_llm()
    
    # 测试 2: 直接 API 调用
    await test_direct_api_call()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
