#!/usr/bin/env python
"""
扫描所有历史聊天记录，批量提取人物档案

从 aveline_data 和 ling_data 的 weighted_memories 中加载所有对话记忆，
分批调用 LLM 提取人物，建立完整的人物档案库。
"""

import asyncio
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_all_weighted_memories() -> list:
    """加载所有角色的 weighted_memories（所有类别，不只是 chat）"""
    base_dir = PROJECT_ROOT / "companion_data"
    all_messages = []

    # 扫描 aveline_data 和 ling_data 的所有 weighted 记忆
    # 记忆按类别分类存储：chat/work/tech/thinking/diary/health/learning 等
    # 人物信息可能出现在任何类别中
    for role_dir_name in ["aveline_data", "ling_data"]:
        weighted_root = base_dir / role_dir_name / "memories" / "weighted"
        if not weighted_root.exists():
            continue

        # 递归扫描所有子目录的 JSON 文件
        for json_file in weighted_root.rglob("*.json"):
            # 跳过临时文件和 state 文件
            if json_file.name.startswith("_") or ".tmp_" in json_file.name:
                continue
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                memories = data.get("weighted_memories", [])
                for m in memories:
                    all_messages.append(m)
                # 显示相对路径，方便调试
                rel_path = json_file.relative_to(weighted_root)
                if memories:
                    print(f"  {role_dir_name}/{rel_path}: {len(memories)} 条")
            except Exception as exc:
                print(f"  {role_dir_name}/{json_file.name}: 读取失败 {exc}")

    return all_messages


class FakeManager:
    """假的管理器，持有所有历史记忆"""

    def __init__(self, messages: list):
        self.weighted_memories = {}
        self.lock = threading.RLock()
        for i, m in enumerate(messages):
            memory_id = m.get("id", str(i))
            self.weighted_memories[memory_id] = m


async def run_full_extraction():
    """运行完整的历史提取"""
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people import get_people_profile_manager

    print("=" * 60)
    print("步骤 1: 加载所有历史聊天记录")
    print("=" * 60)
    all_messages = load_all_weighted_memories()
    print(f"\n总计: {len(all_messages)} 条记忆")

    if not all_messages:
        print("无记忆数据，退出")
        return

    # 按时间排序
    all_messages.sort(key=lambda m: float(m.get("timestamp", 0) or 0))
    earliest = datetime.fromtimestamp(
        float(all_messages[0].get("timestamp", 0) or 0)
    ).strftime("%Y-%m-%d %H:%M")
    latest = datetime.fromtimestamp(
        float(all_messages[-1].get("timestamp", 0) or 0)
    ).strftime("%Y-%m-%d %H:%M")
    print(f"时间范围: {earliest} ~ {latest}")

    # 当前档案
    print("\n" + "=" * 60)
    print("步骤 2: 当前档案列表")
    print("=" * 60)
    manager = get_people_profile_manager()
    all_profiles = manager.list_all_people_profiles()
    print(f"当前人际关系档案: {len(all_profiles)} 个")
    for p in all_profiles:
        print(f"  - {p.name}")

    # 清除 state（强制从头处理）
    extractor = PeopleProfileExtractor()
    state_path = extractor._get_state_path()
    if state_path.exists():
        state_path.unlink()
        print(f"\n已清除旧 state: {state_path.name}")

    # 构造假 manager
    fake_manager = FakeManager(all_messages)

    # 临时修改时间窗口为很大（覆盖所有历史）
    import core.character.people.extractor as ext_module

    original_days = ext_module._TIME_WINDOW_DAYS
    ext_module._TIME_WINDOW_DAYS = 3650  # 10 年，覆盖所有历史

    print("\n" + "=" * 60)
    print("步骤 3: 开始批量提取（可能需要几分钟）")
    print("=" * 60)

    try:
        result = await extractor.extract_and_update(
            "private_10001", fake_manager
        )
    finally:
        # 恢复原始时间窗口
        ext_module._TIME_WINDOW_DAYS = original_days

    print(f"\n提取结果: {result}")

    # 展示最终档案
    print("\n" + "=" * 60)
    print("步骤 4: 最终档案列表")
    print("=" * 60)
    # 清除缓存，重新从磁盘加载
    manager._cache.clear()
    manager._people_index_dirty = True
    all_profiles_after = manager.list_all_people_profiles()
    print(f"人际关系档案: {len(all_profiles_after)} 个\n")

    for p in all_profiles_after:
        facts = p.get_known_facts()
        print(f"【{p.name}】 (id={p.profile_id}, source={p.source})")
        if p.core_fields.get("role"):
            print(f"  关系: {p.core_fields['role']}")
        if p.description:
            print(f"  描述: {p.description}")
        if facts:
            print(f"  已知事实 ({len(facts)} 条):")
            for f in facts:
                print(f"    - {f.key}: {f.value} (confidence={f.confidence})")
        if p.aliases:
            print(f"  别名: {p.aliases}")
        print()


if __name__ == "__main__":
    asyncio.run(run_full_extraction())
