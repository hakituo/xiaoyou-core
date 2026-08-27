#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实DeepSeek API测试，验证Prompt Caching！
"""

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent_components.persona_system.prompt import (
    get_dynamic_system_prompt,
)

from core.character.managers.persona_manager import PersonaManager
import aiohttp


class MockAgent:
    """模拟Agent"""
    def __init__(self):
        self.tool_registry = None
        self.config = type('', (), {})()
        setattr(self.config, 'system_prompt', '')
    
    def _is_study_mode(self, message):
        return False
    
    def _get_memory_manager(self, user_id):
        class MockMemoryManager:
            def get_memories_by_topic(self, topic, limit=1):
                return []
            def get_important_prompts(self):
                return []
        return MockMemoryManager()


async def test_real_caching():
    """真实DeepSeek API测试"""
    print("=" * 80)
    print("真实DeepSeek API Prompt Caching测试")
    print("=" * 80)
    
    print("\n1. 加载项目配置...")
    from config.integrated_config import get_settings
    cfg = get_settings()
    print(f"✅ 配置加载完成！")
    print(f"   配置属性: {[attr for attr in dir(cfg) if not attr.startswith('_')]}")
    
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("\n❌ 错误：没有找到API Key！")
        print("提示：请在.env文件或环境变量中设置DEEPSEEK_API_KEY")
        return
    
    print(f"   API Key: ✓ 已配置")
    
    print("\n2. 初始化Persona Manager...")
    pm = PersonaManager()
    pm.current_persona_file = "qq/Aveline_QQ_Master.json"
    pm._load_current_persona()
    agent = MockAgent()
    print("✅ 初始化完成！")
    
    print("\n3. 获取两次系统提示词...")
    prompt1 = get_dynamic_system_prompt(
        agent=agent,
        user_id="default_user__persona__aveline_qq_master",
        message="你好",
        user_name="Master",
    )

    await asyncio.sleep(1.5)

    prompt2 = get_dynamic_system_prompt(
        agent=agent,
        user_id="default_user__persona__aveline_qq_master",
        message="你好",
        user_name="Master",
    )

    print(f"✅ 两次提示词获取完成！")
    print(f"   长度: {len(prompt1)} vs {len(prompt2)}")

    # 找到仿生体状态的位置来分割静态/动态部分
    bionic_pos1 = prompt1.find("【仿生体状态】")
    bionic_pos2 = prompt2.find("【仿生体状态】")

    if bionic_pos1 > 0 and bionic_pos2 > 0:
        static1 = prompt1[:bionic_pos1]
        static2 = prompt2[:bionic_pos2]
        dynamic1 = prompt1[bionic_pos1:]
        dynamic2 = prompt2[bionic_pos2:]

        print(f"   静态部分长度: {len(static1)} vs {len(static2)}")
        print(f"   静态部分相等: {static1 == static2}")
        print(f"   动态部分长度: {len(dynamic1)} vs {len(dynamic2)}")
        print(f"   动态部分相等: {dynamic1 == dynamic2}")

        if static1 != static2:
            print("\n⚠️ 静态部分不相等！")
            min_len = min(len(static1), len(static2))
            for i in range(min_len):
                if static1[i] != static2[i]:
                    print(f"   位置{i}: '{static1[max(0, i-20):i+20]}' vs '{static2[max(0, i-20):i+20]}'")
                    break
        else:
            print("\n✅ 静态部分完全相等！适合DeepSeek Prompt Caching！")

        print(f"\n动态部分内容（第1次）:")
        print(repr(dynamic1))
        print(f"\n动态部分内容（第2次）:")
        print(repr(dynamic2))
    else:
        print(f"   是否完全相等: {prompt1 == prompt2}")
    
    print("\n4. 准备DeepSeek API...")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    
    print(f"✅ API配置完成！")
    print(f"   URL: {base_url}")
    print(f"   Model: {model}")
    
    # 第一次调用
    print("\n5. 第一次真实API调用...")
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt1},
                {"role": "user", "content": "你好！"}
            ],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "stream": False,
            "max_tokens": 512
        }
        
        print("   发送请求...")
        async with session.post(
            base_url,
            headers=headers,
            json=payload,
            timeout=60
        ) as resp1:
            print(f"✅ 响应状态: {resp1.status}")
            print("\n【第一次响应Headers】:")
            for key, value in resp1.headers.items():
                print(f"  {key}: {value}")
            
            result1 = await resp1.json()
            print("\n【第一次响应Body前500字符】:")
            preview1 = json.dumps(result1, ensure_ascii=False, indent=2)
            if len(preview1) > 500:
                preview1 = preview1[:500] + "\n..."
            print(preview1)
    
    await asyncio.sleep(2)
    
    # 第二次调用
    print("\n6. 第二次真实API调用（相同系统提示词）...")
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt2},
                {"role": "user", "content": "你好！"}
            ],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "stream": False,
            "max_tokens": 512
        }
        
        print("   发送请求...")
        async with session.post(
            base_url,
            headers=headers,
            json=payload,
            timeout=60
        ) as resp2:
            print(f"✅ 响应状态: {resp2.status}")
            print("\n【第二次响应Headers】:")
            for key, value in resp2.headers.items():
                print(f"  {key}: {value}")
            
            result2 = await resp2.json()
            print("\n【第二次响应Body前500字符】:")
            preview2 = json.dumps(result2, ensure_ascii=False, indent=2)
            if len(preview2) > 500:
                preview2 = preview2[:500] + "\n..."
            print(preview2)
    
    print("\n" + "=" * 80)
    print("测试完成！")
    print("提示：查看响应头里是否有类似x-cache-status、x-deepseek-cache-hit这类字段")
    print("如果有，看看第二次调用是不是HIT！")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(test_real_caching())
    except Exception as e:
        import traceback
        print(f"\n❌ 发生错误: {e}")
        traceback.print_exc()
