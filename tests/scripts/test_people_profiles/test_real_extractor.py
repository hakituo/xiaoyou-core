#!/usr/bin/env python
"""
使用真实记忆数据测试人物档案提取器（改进版）

测试改进点：
1. 增量处理（state 文件）
2. 分批提取
3. 置信度过滤
4. 鲁棒 JSON 解析
5. 更好的 prompt（带示例、负面示例）
"""

import asyncio
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class RealMemoryManager:
    """从磁盘加载真实记忆数据"""

    def __init__(self, weighted_file: str, days: int = 1):
        self.weighted_memories = {}
        self.lock = threading.RLock()

        with open(weighted_file, encoding="utf-8") as f:
            data = json.load(f)

        memories = data.get("weighted_memories", [])
        window_start = (datetime.now() - timedelta(days=days)).timestamp()

        count = 0
        for m in memories:
            ts = float(m.get("timestamp", 0) or 0)
            if ts >= window_start:
                memory_id = m.get("id", str(len(self.weighted_memories)))
                self.weighted_memories[memory_id] = m
                count += 1

        print(f"加载了 {count} 条记忆（{days} 天窗口内）")


async def test_with_real_data():
    """用真实记忆数据测试"""
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people import get_people_profile_manager

    # 1. 检查当前档案
    print("=" * 60)
    print("当前档案列表：")
    print("=" * 60)
    manager = get_people_profile_manager()
    all_profiles = manager.list_all_people_profiles()
    print(f"人际关系档案: {len(all_profiles)} 个")
    for p in all_profiles:
        print(f"  - {p.name} (id={p.profile_id})")

    # 2. 加载真实记忆数据（1 天窗口）
    weighted_file = r"d:\AI\xiaoyou-core\companion_data\aveline_data\memories\weighted\chat\private_10001__scope__aveline_weighted.json"
    print(f"\n加载记忆文件: {Path(weighted_file).name}")

    real_manager = RealMemoryManager(weighted_file, days=1)

    # 3. 清除旧的 state（强制重新处理）
    state_path = manager._get_state_path() if hasattr(manager, '_get_state_path') else None
    extractor = PeopleProfileExtractor()
    state_path = extractor._get_state_path()
    if state_path.exists():
        state_path.unlink()
        print(f"已清除旧 state: {state_path.name}")

    # 4. 运行提取器
    print("\n" + "=" * 60)
    print("开始提取（改进版提取器）...")
    print("=" * 60)

    result = await extractor.extract_and_update("private_10001", real_manager)
    print(f"\n提取结果: {result}")

    # 5. 检查新档案
    print("\n" + "=" * 60)
    print("提取后档案列表：")
    print("=" * 60)
    all_profiles_after = manager.list_all_people_profiles()
    print(f"人际关系档案: {len(all_profiles_after)} 个")
    for p in all_profiles_after:
        facts = p.get_known_facts()
        print(f"  - {p.name} (id={p.profile_id}, source={p.source})")
        if p.description:
            print(f"    描述: {p.description}")
        if facts:
            print(f"    已知事实: {len(facts)} 条")
            for f in facts[:3]:
                print(f"      - {f.key}: {f.value} (confidence={f.confidence})")

    # 6. 检查 state 文件
    print("\n" + "=" * 60)
    print("增量处理状态：")
    print("=" * 60)
    state = extractor._load_state()
    last_ts = state.get("last_processed_timestamp", 0)
    if last_ts > 0:
        print(f"  last_processed_timestamp: {last_ts}")
        print(f"  last_run_time: {state.get('last_run_time', 'N/A')}")
        print(f"  对应时间: {datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("  无 state（未处理过）")


if __name__ == "__main__":
    asyncio.run(test_with_real_data())
