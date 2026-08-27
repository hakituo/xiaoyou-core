#!/usr/bin/env python
"""
立即测试人物档案提取器

模拟聊天记录，调用 LLM 提取人物，验证是否能正确创建/更新档案。
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_extractor():
    """测试提取器"""
    import time
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people import get_people_profile_manager

    # 1. 先列出当前所有档案
    print("=" * 60)
    print("当前档案列表：")
    print("=" * 60)
    manager = get_people_profile_manager()
    all_profiles = manager.list_all_people_profiles()
    print(f"人际关系档案: {len(all_profiles)} 个")
    for p in all_profiles:
        print(f"  - {p.name} (id={p.profile_id})")

    # 2. 模拟聊天记录（使用当前时间戳）
    now = time.time()
    fake_messages = [
        {"role": "user", "content": "今天和小明一起打游戏，他技术很好", "timestamp": now - 100},
        {"role": "assistant", "content": "小明是谁啊？", "timestamp": now - 99},
        {"role": "user", "content": "我同学，高中同学，他叫李小明，学计算机的", "timestamp": now - 98},
        {"role": "assistant", "content": "原来如此", "timestamp": now - 97},
        {"role": "user", "content": "还有小红，她今天也一起玩了", "timestamp": now - 96},
        {"role": "assistant", "content": "小红也是你同学？", "timestamp": now - 95},
        {"role": "user", "content": "对，她是小明的女朋友，学设计的", "timestamp": now - 94},
    ]

    # 3. 创建假的记忆管理器（只为了传递消息）
    import threading

    class FakeMemoryManager:
        def __init__(self, messages):
            self.weighted_memories = {
                str(i): msg for i, msg in enumerate(messages)
            }
            self.lock = threading.RLock()  # 用真正的锁

    print("\n" + "=" * 60)
    print("开始测试提取器（会调用真实 LLM）...")
    print("=" * 60)

    fake_manager = FakeMemoryManager(fake_messages)
    extractor = PeopleProfileExtractor()

    # 4. 调用提取器（会调用 LLM）
    try:
        result = await extractor.extract_and_update("test_user", fake_manager)
        print(f"\n提取结果: {result}")
    except Exception as exc:
        print(f"\n提取失败: {exc}")
        import traceback
        traceback.print_exc()
        return

    # 5. 再次列出档案，看是否有新增
    print("\n" + "=" * 60)
    print("提取后档案列表：")
    print("=" * 60)
    all_profiles_after = manager.list_all_people_profiles()
    print(f"人际关系档案: {len(all_profiles_after)} 个")
    for p in all_profiles_after:
        facts = p.get_known_facts()
        print(f"  - {p.name} (id={p.profile_id})")
        if facts:
            print(f"    已知事实: {len(facts)} 条")
            for f in facts[:3]:
                print(f"      - {f.key}: {f.value}")

    # 6. 尝试查询新增的人物
    print("\n" + "=" * 60)
    print("查询新增人物：")
    print("=" * 60)
    for name in ["小明", "李小明", "小红"]:
        profile = manager.query_profile_details(name)
        if profile:
            print(f"✓ 查询 '{name}' 成功: {profile.name}")
        else:
            print(f"✗ 查询 '{name}' 失败: 无匹配")


if __name__ == "__main__":
    asyncio.run(test_extractor())