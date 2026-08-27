#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查完整消息构建的 Prompt Caching 审计
"""

import sys
import os
import asyncio

# 加入项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


async def audit_full_message_cache():
    print("=" * 80)
    print("完整消息构建 Prompt Caching 审计")
    print("=" * 80)

    from core.agents.chat_agent import ChatAgent
    from core.character.managers.persona_manager import PersonaManager

    try:
        # 初始化角色和代理
        pm = PersonaManager()
        pm.current_persona_file = "qq/Aveline_QQ_Master.json"
        pm._load_current_persona()

        agent = ChatAgent()
        await agent.initialize()

        # 调用完整的消息构建函数
        print("\n1. 调用完整的消息构建过程...")
        messages = await agent._build_conversation_history(
            user_id="default_user__persona__aveline_qq_master",
            message="你好",
        )

        print(f"✅ 消息构建成功，数量: {len(messages)}")

        print("\n2. 分析每条消息的详细信息:")
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            preview = content[:100].replace("\n", "\\n")
            print(f"\n消息 {i+1}: [{role}]")
            print(f"  长度: {len(content)} 字符")
            print(f"  预览: {preview}...")

        # 计算第一条消息（应该是 persona_system_prompt，静态内容）
        print("\n" + "=" * 80)
        if len(messages) > 0:
            first_msg = messages[0]
            first_preview = first_msg.get('content')[:200].replace("\n", "\\n")
            print(f"第一条消息应该是 persona_system_prompt（静态内容）：")
            print(f"  角色: {first_msg.get('role')}")
            print(f"  长度: {len(first_msg.get('content'))} 字符")
            print(f"  预览: {first_preview}...")
        else:
            print("❌ 没有消息")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(audit_full_message_cache())
