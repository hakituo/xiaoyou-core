#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试不同模型的 priority_analysis 响应时间
对比 DeepSeek-V3.2 和 DeepSeek-V4-Flash
"""
import asyncio
import time
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()


async def test_model(model_name: str, api_key: str, base_url: str, provider: str):
    """测试单个模型"""
    print(f"\n{'='*60}")
    print(f"测试模型: {model_name}")
    print(f"Provider: {provider}")
    print(f"{'='*60}")
    
    import aiohttp
    
    system_prompt = """你是主动关怀调度分析器。请为'今日主动推送'生成优先级排序，输出必须是 JSON。
按紧急程度、用户上下文、任务时效综合排序。
suggested_intent 只能是: curious_question/share_thought/emotional_support/user_health_reminder/bio_complaint。
禁止输出 JSON 以外内容。"""

    user_prompt = """请根据以下上下文生成今日推送优先级：
{
  "now": "2026-06-17T23:50:00",
  "latest_user_signal_age_seconds": 3600,
  "priority_focus": {
    "must_probe": false,
    "stage": "idle",
    "portrait_priority": ["activity", "mood"],
    "covered_topics": [],
    "recent_peer_chat_topics": []
  },
  "urgent_needs": ["hungry"],
  "candidates": [
    {"id": "urgent:hungry", "title": "突发状态：hungry", "reason": "urgent", "base_score": 84},
    {"id": "portrait:activity", "title": "补齐画像：活动", "reason": "portrait_missing", "base_score": 70},
    {"id": "portrait:mood", "title": "补齐画像：心情", "reason": "portrait_missing", "base_score": 70}
  ]
}
输出格式：{"summary": "一句话说明", "priorities": [{"priority": 1, "id": "xxx", "title": "xxx", "reason": "xxx"}]}"""

    # 根据 provider 构建请求
    if provider == "deepseek":
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.25,
            "max_tokens": 420
        }
    elif provider == "siliconflow":
        url = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.25,
            "max_tokens": 420
        }
    else:
        print(f"未知 provider: {provider}")
        return
    
    print(f"URL: {url}")
    print(f"开始调用...")
    
    start_time = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, 
                headers=headers, 
                json=data, 
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                elapsed = time.time() - start_time
                if resp.status == 200:
                    result = await resp.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"\n✅ 调用成功!")
                    print(f"耗时: {elapsed:.2f}秒")
                    print(f"响应: {content[:500]}")
                else:
                    text = await resp.text()
                    print(f"\n❌ 调用失败!")
                    print(f"耗时: {elapsed:.2f}秒")
                    print(f"状态码: {resp.status}")
                    print(f"响应: {text[:300]}")
                    
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"\n❌ 调用超时!")
        print(f"耗时: {elapsed:.2f}秒")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ 调用异常!")
        print(f"耗时: {elapsed:.2f}秒")
        print(f"错误: {type(e).__name__}: {e}")


async def main():
    print("Priority Analysis 模型对比测试")
    print("="*60)
    
    # 测试 1: DeepSeek V4 Flash (bot2 API key)
    deepseek_key = os.getenv("DEEPSEEK_API_KEY_QQBOT2")
    if deepseek_key:
        await test_model(
            model_name="deepseek-chat",  # V4 Flash
            api_key=deepseek_key,
            base_url="https://api.deepseek.com",
            provider="deepseek"
        )
    else:
        print("\n[跳过] 未找到 DEEPSEEK_BOT2_API_KEY")
    
    # 测试 2: DeepSeek V3.2 (SiliconFlow)
    siliconflow_key = os.getenv("SILICONFLOW_API_KEY")
    if siliconflow_key:
        await test_model(
            model_name="deepseek-ai/DeepSeek-V3.2",
            api_key=siliconflow_key,
            base_url="https://api.siliconflow.cn",
            provider="siliconflow"
        )
    else:
        print("\n[跳过] 未找到 SILICONFLOW_API_KEY")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
