#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比测试：DeepSeek-V3.2 vs DeepSeek-V4-Flash 使用相同的完整 prompt
"""
import asyncio
import time
import sys
import json
import os
from pathlib import Path
from dotenv import load_dotenv
import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()


async def test_model(name: str, url: str, api_key: str, model: str, messages: list):
    """测试单个模型"""
    print(f"\n{'='*50}")
    print(f"测试: {name}")
    print(f"模型: {model}")
    print(f"{'='*50}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": 420
    }
    
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
                    print(f"✅ 成功! 耗时: {elapsed:.2f}秒")
                    print(f"响应: {content[:200]}")
                    return elapsed, True
                else:
                    text = await resp.text()
                    print(f"❌ 失败! 耗时: {elapsed:.2f}秒, 状态码: {resp.status}")
                    return elapsed, False
                    
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"❌ 超时! 耗时: {elapsed:.2f}秒")
        return elapsed, False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ 异常! 耗时: {elapsed:.2f}秒, 错误: {e}")
        return elapsed, False


async def main():
    print("Priority Analysis 模型对比测试 (相同 prompt)")
    print("="*60)
    
    # 构建完整的 priority_analysis prompt
    system_prompt = """你是主动关怀调度分析器。请为'今日主动推送'生成优先级排序，输出必须是 JSON。
按紧急程度、用户上下文、任务时效综合排序。
suggested_intent 只能是: curious_question/share_thought/emotional_support/user_health_reminder/bio_complaint。
禁止输出 JSON 以外内容。
重要：必须参考 recent_chat 判断用户是否已聊过某话题，covered_topics 中的话题已覆盖禁止再排入优先级。"""

    user_prompt = """请根据以下上下文生成今日推送优先级：
{
  "now": "2026-06-17T23:50:00",
  "latest_user_signal_age_seconds": 3600,
  "priority_focus": {
    "must_probe": false,
    "stage": "idle",
    "task_probe": {},
    "portrait_priority": ["activity", "mood"],
    "covered_topics": [],
    "summary": {
      "timed_pending": 0,
      "untimed_pending": 0,
      "missing_items": ["activity", "mood", "health"]
    },
    "has_recent_peer_chat": false,
    "recent_peer_chat_topics": []
  },
  "urgent_needs": ["hungry"],
  "portrait_completeness": {
    "score": 57,
    "missing_items": ["activity", "mood", "health"],
    "signals": {
      "wakeup": true,
      "sleep": true,
      "meal": true,
      "activity": false,
      "mood": false,
      "study": true,
      "health": false
    }
  },
  "daily_tasks_focus": {},
  "candidates": [
    {
      "id": "urgent:hungry",
      "title": "突发状态：hungry",
      "reason": "urgent",
      "suggested_intent": "share_thought",
      "base_score": 84
    },
    {
      "id": "portrait:activity",
      "title": "补齐画像：活动",
      "reason": "portrait_missing",
      "suggested_intent": "user_health_reminder",
      "base_score": 70
    },
    {
      "id": "portrait:mood",
      "title": "补齐画像：心情",
      "reason": "portrait_missing",
      "suggested_intent": "user_health_reminder",
      "base_score": 70
    }
  ],
  "recent_chat": [
    "user: 我吃过了",
    "assistant: 吃的什么呀",
    "user: 薯饼",
    "assistant: 空气炸锅做的吗",
    "user: 对啊，很方便"
  ],
  "covered_topics": []
}
输出格式：{"summary": "一句话说明", "priorities": [{"priority": 1, "id": "xxx", "title": "xxx", "reason": "xxx"}]}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"Prompt 大小: {len(system_prompt) + len(user_prompt)} 字符")
    
    # 测试 1: DeepSeek-V3.2 (SiliconFlow)
    siliconflow_key = os.getenv("SILICONFLOW_API_KEY")
    if siliconflow_key:
        t1, _ = await test_model(
            name="DeepSeek-V3.2 (SiliconFlow)",
            url="https://api.siliconflow.cn/v1/chat/completions",
            api_key=siliconflow_key,
            model="deepseek-ai/DeepSeek-V3.2",
            messages=messages
        )
    else:
        t1 = 0
        print("\n[跳过] 未找到 SILICONFLOW_API_KEY")
    
    # 测试 2: DeepSeek-V4-Flash (Bot2 API Key)
    deepseek_key = os.getenv("DEEPSEEK_API_KEY_QQBOT2")
    if deepseek_key:
        t2, _ = await test_model(
            name="DeepSeek-V4-Flash (DeepSeek 官方)",
            url="https://api.deepseek.com/chat/completions",
            api_key=deepseek_key,
            model="deepseek-chat",
            messages=messages
        )
    else:
        t2 = 0
        print("\n[跳过] 未找到 DEEPSEEK_API_KEY_QQBOT2")
    
    # 对比结果
    print("\n" + "="*60)
    print("对比结果")
    print("="*60)
    if t1 > 0 and t2 > 0:
        print(f"DeepSeek-V3.2 (SiliconFlow): {t1:.2f}秒")
        print(f"DeepSeek-V4-Flash (官方):    {t2:.2f}秒")
        print(f"速度提升: {t1/t2:.1f}倍")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
