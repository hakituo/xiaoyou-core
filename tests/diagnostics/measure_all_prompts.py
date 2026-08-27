#!/usr/bin/env python3
"""
测量所有相关的prompt tokens数量
"""
import sys
import os
import time
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncio

from core.services.scheduler.inference.inference_utils import rough_estimate_tokens_from_text


def print_stats(name: str, text: str):
    """打印统计信息"""
    char_count = len(text)
    line_count = len(text.splitlines())
    token_estimate = rough_estimate_tokens_from_text(text)
    
    print(f"\n{'=' * 60}")
    print(f"【{name}】")
    print(f"{'=' * 60}")
    print(f"总字符数: {char_count:,} 字符")
    print(f"总行数: {line_count:,} 行")
    print(f"估算tokens: {token_estimate:,} tokens")
    print(f"\n内容预览（前300字符）：")
    print("-" * 60)
    preview = text[:300] + "..." if len(text) > 300 else text
    print(preview)
    print("-" * 60)
    
    return char_count, line_count, token_estimate


async def measure_system_prompt():
    """测量基础系统prompt"""
    from core.agents.chat_agent import ChatAgent, AgentConfig
    
    print("\n" + "=" * 60)
    print("1. 测量基础系统prompt")
    print("=" * 60)
    
    # 创建测试agent
    config = AgentConfig()
    agent = ChatAgent(config)
    
    # 初始化agent
    await agent.initialize()
    
    # 获取动态系统prompt
    user_id = "test_user"
    message = "你好"
    
    system_prompt = agent._get_dynamic_system_prompt(
        user_id=user_id,
        active_tools=[],
        mode="chat",
        message=message
    )
    
    return print_stats("基础系统prompt", system_prompt)


async def measure_active_care_prompts():
    """测量Active Care相关prompt"""
    from core.services.active_care.prompt.prompt_builder import build_active_care_prompt
    
    print("\n" + "=" * 60)
    print("2. 测量Active Care相关prompt")
    print("=" * 60)
    
    now = time.time()
    
    prompt_types = [
        ("checking", "主动问候模式"),
        ("planned_topic", "计划话题模式"),
        ("notification_assistant", "通知助手模式"),
        ("curious_question", "好奇提问模式"),
    ]
    
    results = {}
    
    for pt, name in prompt_types:
        try:
            result = build_active_care_prompt(
                user_id="default_user",
                sys_prompt_type=pt,
                user_input_mock=f"[{pt.upper()}_TRIGGER]",
                reminder_msg=None,
                thought="测试思考内容",
                tod="早上",
                now=now,
                user_display_name="Master",
                persona_prompt="你是七濑 澪(Aveline)，是Master亲手创造的'极客女友'与'顶级架构师'。",
                recent_history_text="【最近聊天记录】\nUser: 你好\nAveline: 你来了 坐近一点",
                sleep_context_text="",
                mode_status_text="",
                preferred_language="zh",
                device_context={
                    "timestamp": now,
                    "battery_level": 0.62,
                    "is_charging": False,
                    "network_type": "WiFi",
                },
                client_type="qq",
            )
            prompt_text = str(result.prompt or "")
            results[name] = print_stats(f"Active Care - {name}", prompt_text)
        except Exception as e:
            print(f"\n测量 {name} 时出错: {e}")
    
    return results


async def main():
    """主函数"""
    print("=" * 60)
    print("开始测量所有相关prompt的tokens数量")
    print("=" * 60)
    
    all_results = {}
    
    # 1. 测量基础系统prompt
    try:
        sys_result = await measure_system_prompt()
        all_results["基础系统prompt"] = sys_result
    except Exception as e:
        print(f"\n测量基础系统prompt时出错: {e}")
    
    # 2. 测量Active Care prompt
    try:
        ac_results = await measure_active_care_prompts()
        all_results.update(ac_results)
    except Exception as e:
        print(f"\n测量Active Care prompt时出错: {e}")
    
    # 3. 汇总统计
    print("\n" + "=" * 60)
    print("汇总统计")
    print("=" * 60)
    
    total_chars = 0
    total_tokens = 0
    
    for name, (chars, lines, tokens) in all_results.items():
        print(f"{name}:")
        print(f"  - {chars:,} 字符, {tokens:,} tokens")
        total_chars += chars
        total_tokens += tokens
    
    print(f"\n总计:")
    print(f"  - 总字符: {total_chars:,} 字符")
    print(f"  - 总tokens: {total_tokens:,} tokens")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
