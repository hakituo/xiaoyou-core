#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查当前提示词的静态/动态划分情况
"""

import asyncio
import sys
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
        "preview": content[:200].replace("\n", "\\n") + ("..." if len(content) > 200 else ""),
    }


async def audit_prompt_cache():
    print("=" * 80)
    print("提示词缓存审计 - 检查当前系统提示词的静态/动态划分")
    print("=" * 80)
    
    from core.agents.chat_agent import ChatAgent
    from core.agents.chat_agent_components.persona_system.prompt import get_dynamic_system_prompt
    from core.character.managers.persona_manager import PersonaManager
    
    try:
        # 初始化角色和代理
        pm = PersonaManager()
        pm.current_persona_file = "qq/Aveline_QQ_Master.json"
        pm._load_current_persona()
        
        agent = ChatAgent()
        await agent.initialize()
        
        # 生成系统提示词
        prompt = get_dynamic_system_prompt(
            agent=agent,
            user_id="default_user__persona__aveline_qq_master",
            message="你好",
            user_name="Master"
        )
        
        # 分析缓存情况
        result = get_static_prefix_length(prompt)
        
        print(f"\n📊 系统提示词总长度: {result['total_length']} 字符")
        print(f"📊 静态前缀长度: {result['static_length']} 字符")
        print(f"📊 缓存率: {result['cache_ratio']:.1%}")
        print(f"📊 缓存状态: {result['status']}")
        print(f"📊 中断原因: {result['reason']}")
        
        print(f"\n📝 静态部分预览:\n{result['preview']}")
        
        # 打印完整的提示词
        print("\n" + "=" * 80)
        print("📝 完整系统提示词:")
        print("=" * 80)
        print(prompt)
        print("=" * 80)
        
        # 分析结构
        if result['static_length'] < len(prompt):
            print(f"\n📍 动态部分开始位置: {result['static_length']}")
            start_idx = max(0, result['static_length'] - 100)
            end_idx = min(len(prompt), result['static_length'] + 200)
            print(f"\n📍 动态部分开始上下文:")
            print(f"...{prompt[start_idx:end_idx]}...")
        
        # 检查我们的修改是否正确
        if '【可用工具】' in prompt:
            print("\n⚠️ 警告：提示词中仍然包含【可用工具】部分！")
        else:
            print("\n✅ 验证：提示词中已经移除了工具注入")
            
        if '【记忆浮现】' in prompt:
            print("\n⚠️ 警告：提示词中仍然包含记忆浮现注入！")
            
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(audit_prompt_cache())
