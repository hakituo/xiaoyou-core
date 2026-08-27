#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt Caching 审计脚本
检查所有模块的 prompt 结构，确保时间锚点不在开头，以优化 DeepSeek Prompt Caching 命中率
"""

import asyncio
import sys
import time
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_static_prefix_length(content: str) -> dict:
    """
    测量可以被安全缓存的静态前缀长度。
    遇到任何时间、设备状态、生理状态等可能随时间/请求变化的动态标记，就认为前缀结束。
    """
    content = str(content or "").strip()
    
    # 定义动态锚点的正则表达式
    dynamic_patterns = [
        r"【时间锚点】当前时间：",
        r"【时间锚点】当前本地时间：",
        r"当前时间：",
        r"当前系统时间：",
        r"\[用户手机实时状态\]",
        r"【你的底层状态",
        r"【饮食系统状态】",
        r"【用户的生理监测数据",
        r"【用户当前状态】",
        r"【今日日程摘要】",
        r"【睡眠事实锚点",
        r"【顺便找茬】",
        r"【用户健康】",
        r"【仿生体状态】",
        r"【用户当前学习状态",
        r"【学习状态监控】",
        r"【当前进行中的话题】",
        r"【最近记录】",
        r"【最近聊天记录】",
        r"\[用户状态\]",
        r"\(当前无用户生理数据，忽略此项\)",
        r"【触发任务：",
    ]
    
    # 额外检查：有没有遗漏的变量占位符，如果没替换掉，也算问题
    if "{current_time}" in content:
        return {
            "static_length": content.find("{current_time}"),
            "total_length": len(content),
            "cache_ratio": content.find("{current_time}") / len(content) if len(content) > 0 else 0,
            "reason": "{current_time} 未替换",
            "status": "❌ 较差 (占位符未替换)",
            "preview": content[:100].replace("\n", "\\n") + ("..." if len(content) > 100 else ""),
        }
    
    earliest_match_idx = len(content)
    match_reason = "No dynamic anchor found"
    
    for pattern in dynamic_patterns:
        match = re.search(pattern, content)
        if match:
            if match.start() < earliest_match_idx:
                earliest_match_idx = match.start()
                match_reason = pattern
                
    cache_ratio = earliest_match_idx / len(content) if len(content) > 0 else 0
    
    status = "✅ 优秀 (缓存率>80%)" if cache_ratio > 0.8 else "⚠️ 良好 (缓存率>50%)" if cache_ratio > 0.5 else "❌ 较差 (缓存率<50%)"
    
    return {
        "static_length": earliest_match_idx,
        "total_length": len(content),
        "cache_ratio": cache_ratio,
        "reason": match_reason,
        "status": status,
        "preview": content[:100].replace("\n", "\\n") + ("..." if len(content) > 100 else ""),
    }


async def test_chat_prompt(persona_file: str, user_id: str):
    """测试 Chat 模块的 prompt 结构"""
    print("\n" + "=" * 60)
    print(f"1. Chat 模块 - {persona_file}")
    print("=" * 60)
    
    from core.agents.chat_agent import ChatAgent
    from core.agents.chat_agent_components.context import build_conversation_history
    from core.character.managers.persona_manager import PersonaManager
    
    pm = PersonaManager()
    pm.current_persona_file = persona_file
    pm._load_current_persona()
    
    agent = ChatAgent()
    await agent.initialize()
    
    messages = await build_conversation_history(
        agent=agent,
        user_id=user_id,
        message='你好',
        model_hint='cloud',
    )
    
    system_messages = [str(m.get('content', '')) for m in messages if m.get('role') == 'system']
    combined_system_prompt = "\n\n".join(x for x in system_messages if str(x).strip())
    print(f"  system消息数: {len(system_messages)}")
    result = get_static_prefix_length(combined_system_prompt)
    
    print(f"  {result['status']}")
    print(f"  总长度: {result['total_length']} chars")
    print(f"  静态前缀: {result['static_length']} chars ({result['cache_ratio']:.1%})")
    print(f"  中断原因: 匹配到 {result['reason']}")
    
    return result['cache_ratio'] > 0.5


async def test_active_care_prompt_builder(persona_file: str, persona_name: str, conversation_id: str):
    """测试 Active Care prompt_builder 的 prompt 结构"""
    print("\n" + "=" * 60)
    print(f"2. Active Care - {persona_name}")
    print("=" * 60)
    
    from core.services.active_care.prompt.prompt_builder import build_active_care_prompt
    from core.services.active_care.core.executor import ActiveCareExecutor
    from core.character.managers.persona_manager import PersonaManager
    
    pm = PersonaManager()
    pm.current_persona_file = persona_file
    pm._load_current_persona()
    
    executor = ActiveCareExecutor(context=None, storage=None)
    persona_prompt = executor._load_active_care_persona_prompt(conversation_id)
    persona_filename = executor._resolve_persona_filename(conversation_id)
    tone_reference_text = executor._build_active_care_tone_reference(
        conversation_id,
        "你下班了吗",
        "sensitive/" in str(persona_filename or "").replace("\\", "/").lower(),
    )

    result = build_active_care_prompt(
        now=time.time(),
        user_id=conversation_id,
        persona_prompt=persona_prompt,
        sys_prompt_type="greeting",
        user_input_mock="",
        reminder_msg="",
        thought="",
        tod="早上",
        user_display_name="Master",
        recent_history_text="",
        tone_reference_text=tone_reference_text,
        persona_filename=persona_filename,
        persona_name=persona_name,
    )
    
    prompt = result.prompt
    
    check_result = get_static_prefix_length(prompt)
    
    print(f"  {check_result['status']}")
    print(f"  总长度: {check_result['total_length']} chars")
    print(f"  静态前缀: {check_result['static_length']} chars ({check_result['cache_ratio']:.1%})")
    print(f"  中断原因: 匹配到 {check_result['reason']}")
    
    # 打印被中断的上下文
    if check_result['static_length'] < check_result['total_length']:
        start = max(0, check_result['static_length'] - 20)
        end = min(len(prompt), check_result['static_length'] + 50)
        print(f"  中断上下文: ...{prompt[start:end]}...")
    
    return check_result['cache_ratio'] > 0.5


async def main():
    print("=" * 60)
    print("Prompt Caching 深度审计")
    print("检查所有模块的 prompt 静态前缀长度")
    print("=" * 60)
    
    results = {}
    
    try:
        results["Chat (Aveline)"] = await test_chat_prompt("qq/Aveline_QQ_Master.json", "default_user__persona__aveline_qq_master")
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results["Chat (Aveline)"] = False
        
    try:
        results["Chat (Ling)"] = await test_chat_prompt("core_ling.json", "default_user__persona__core_ling")
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results["Chat (Ling)"] = False
    
    try:
        results["Active Care (Aveline)"] = await test_active_care_prompt_builder("qq/Aveline_QQ_Master.json", "七濑 澪", "default_user__persona__aveline_qq_master")
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results["Active Care (Aveline)"] = False
        
    try:
        results["Active Care (Ling)"] = await test_active_care_prompt_builder("core_ling.json", "Ling", "default_user__persona__core_ling")
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results["Active Care (Ling)"] = False
    
    print("\n" + "=" * 60)
    print("审计结果汇总")
    print("=" * 60)
    
    all_ok = True
    for name, ok in results.items():
        status = "✅ 缓存率达标" if ok else "❌ 缓存率过低"
        print(f"  {name}: {status}")
        if not ok:
            all_ok = False
    
    print("=" * 60)
    if all_ok:
        print("🎉 所有模块的静态前缀长度都达标，Prompt Caching 优化成功！")
    else:
        print("⚠️ 部分模块的缓存率仍需优化")
    print("=" * 60)
    
    return all_ok


if __name__ == "__main__":
    asyncio.run(main())
