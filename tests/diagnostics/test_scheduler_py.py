#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 C++ 调度器是否可用"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_scheduler_py():
    print("=" * 60)
    print("测试 C++ 调度器模块")
    print("=" * 60)

    try:
        from core.services.scheduler.scheduler_wrapper import scheduler_py
        print("scheduler_py loaded successfully!")
        print(f"scheduler_py module: {scheduler_py}")

        available = [x for x in dir(scheduler_py) if not x.startswith("_")]
        print(f"Available classes: {available}")

        # 测试创建调度器
        print()
        print("测试创建调度器...")
        scheduler = scheduler_py.ResourceIsolationScheduler()
        print(f"Scheduler created: {scheduler}")

        return True
    except Exception as e:
        print(f"Failed to load scheduler_py: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_scheduler_py()
    print()
    print("测试结果:", "通过" if success else "失败")
    sys.exit(0 if success else 1)
