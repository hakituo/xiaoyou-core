#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 priority_analysis 完整 prompt 大小和响应时间
"""
import asyncio
import time
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_full_prompt():
    """使用完整的 priority_analyzer prompt 测试"""
    print("=" * 60)
    print("测试完整 priority_analysis prompt")
    print("=" * 60)
    
    # 1. 获取配置
    from config.model_config import get_priority_analysis_model
    model_path = get_priority_analysis_model()
    print(f"\n[1] 模型: {model_path}")
    
    # 2. 构建完整的 prompt（模拟 priority_analyzer 的实际调用）
    from core.agents.chat_agent_components.persona_system.prompt.components.templates import PRIORITY_ANALYSIS_SYSTEM_PROMPT
    
    # 模拟实际的 prompt_payload
    prompt_payload = {
        "now": "2026-06-17T23:50:00",
        "latest_user_signal_age_seconds": 3600,
        "priority_focus": {
            "must_probe": False,
            "stage": "idle",
            "task_probe": {},
            "portrait_priority": ["activity", "mood"],
            "covered_topics": [],
            "summary": {
                "timed_pending": 0,
                "untimed_pending": 0,
                "missing_items": ["activity", "mood", "health"]
            },
            "has_recent_peer_chat": False,
            "recent_peer_chat_topics": []
        },
        "urgent_needs": ["hungry"],
        "portrait_completeness": {
            "score": 57,
            "missing_items": ["activity", "mood", "health"],
            "signals": {
                "wakeup": True,
                "sleep": True,
                "meal": True,
                "activity": False,
                "mood": False,
                "study": True,
                "health": False
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
    
    system_prompt = PRIORITY_ANALYSIS_SYSTEM_PROMPT
    user_prompt = (
        "请根据以下上下文生成今日推送优先级：\n"
        + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        + "\n输出格式："
        + json.dumps(
            {
                "summary": "一句话说明排序依据",
                "priorities": [
                    {
                        "priority": 1,
                        "id": "候选ID",
                        "title": "优先事项标题",
                        "reason": "为什么现在该优先",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    
    print(f"\n[2] Prompt 大小:")
    print(f"    system_prompt: {len(system_prompt)} 字符")
    print(f"    user_prompt: {len(user_prompt)} 字符")
    print(f"    总计: {len(system_prompt) + len(user_prompt)} 字符")
    
    # 3. 测试 LLM 调用
    from core.llm import get_llm_module
    llm = get_llm_module()
    
    print(f"\n[3] 开始 LLM 调用 (超时 30 秒)...")
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
            timeout=30.0,
        )
        elapsed = time.time() - start_time
        
        if isinstance(raw_text, dict):
            if raw_text.get("status") == "success":
                raw_text = str(raw_text.get("response") or "")
            else:
                raw_text = ""
        
        print(f"\n[4] ✅ 调用成功!")
        print(f"    耗时: {elapsed:.2f} 秒")
        print(f"    响应长度: {len(raw_text)} 字符")
        print(f"    响应预览: {raw_text[:300]}")
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"\n[4] ❌ 调用超时!")
        print(f"    耗时: {elapsed:.2f} 秒")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n[4] ❌ 调用失败!")
        print(f"    耗时: {elapsed:.2f} 秒")
        print(f"    错误: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(test_full_prompt())
