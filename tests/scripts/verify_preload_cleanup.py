#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冗余预加载线程清理验证脚本

验证 memory/weighted_memory_manager.py 中的冗余预加载线程是否已清理：
1. 不应存在 target=self._lazy_init_vector_indexer 的后台线程启动代码
   （vector_indexer property 已有延迟获取机制，后台预初始化是冗余的）
2. 不应存在 target=self.reclassify_all_memories 的独立后台线程启动代码
   （已合并到 _deferred_load 内部，在数据加载完成后执行）
3. _deferred_load 内部应包含 reclassify_all_memories 调用
4. threading.Thread 调用数量应从 3 降到 1（只保留 _deferred_load）
5. _lazy_init_vector_indexer 方法和 vector_indexer property 应保留
   （延迟获取机制仍需要）
"""

import re
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_FILE = PROJECT_ROOT / "memory" / "weighted_memory_manager.py"


def read_target_file() -> str:
    """读取目标文件内容"""
    if not TARGET_FILE.exists():
        print(f"❌ 文件不存在: {TARGET_FILE}")
        sys.exit(1)
    return TARGET_FILE.read_text(encoding="utf-8")


def check_no_lazy_init_thread(content: str) -> bool:
    """检查 1：不应存在 _lazy_init_vector_indexer 的后台线程启动代码"""
    pattern = r"threading\.Thread\(\s*target\s*=\s*self\._lazy_init_vector_indexer"
    matches = re.findall(pattern, content)
    if matches:
        print(f"❌ 仍存在 _lazy_init_vector_indexer 后台线程启动代码（{len(matches)} 处）")
        return False
    print("✅ 检查 1 通过：不存在 _lazy_init_vector_indexer 后台线程启动代码")
    return True


def check_no_reclassify_thread(content: str) -> bool:
    """检查 2：不应存在 reclassify_all_memories 的独立后台线程启动代码"""
    pattern = r"threading\.Thread\(\s*target\s*=\s*self\.reclassify_all_memories"
    matches = re.findall(pattern, content)
    if matches:
        print(f"❌ 仍存在 reclassify_all_memories 独立后台线程启动代码（{len(matches)} 处）")
        return False
    print("✅ 检查 2 通过：不存在 reclassify_all_memories 独立后台线程启动代码")
    return True


def check_reclassify_in_deferred_load(content: str) -> bool:
    """检查 3：_deferred_load 内部应包含 reclassify_all_memories 调用"""
    # 提取 _deferred_load 函数体
    pattern = r"def\s+_deferred_load\s*\(\s*\)\s*:.*?(?=\n\s{8}threading\.Thread|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("❌ 未找到 _deferred_load 函数定义")
        return False
    deferred_load_body = match.group(0)
    if "self.reclassify_all_memories()" not in deferred_load_body:
        print("❌ _deferred_load 内部未包含 self.reclassify_all_memories() 调用")
        return False
    print("✅ 检查 3 通过：_deferred_load 内部包含 reclassify_all_memories 调用")
    return True


def check_thread_count(content: str) -> bool:
    """检查 4：__init__ 方法中 threading.Thread 调用数量应为 1（只保留 _deferred_load）"""
    # 提取 __init__ 方法体（从 def __init__ 到下一个 def）
    init_pattern = r"def\s+__init__\s*\(.*?\).*?(?=\n    def\s|\n    @)"
    init_match = re.search(init_pattern, content, re.DOTALL)
    if not init_match:
        print("❌ 未找到 __init__ 方法")
        return False
    init_body = init_match.group(0)
    # 统计 threading.Thread 调用
    thread_calls = re.findall(r"threading\.Thread\(", init_body)
    # 预期 1 个：_deferred_load 线程
    # 注意：_start_auto_save 里可能有独立的线程，但那是在另一个方法里
    if len(thread_calls) != 1:
        print(f"❌ __init__ 中 threading.Thread 调用数量为 {len(thread_calls)}，预期 1")
        # 显示所有匹配行的上下文
        for line_num, line in enumerate(init_body.split("\n"), 1):
            if "threading.Thread(" in line:
                print(f"   第 {line_num} 行: {line.strip()}")
        return False
    print("✅ 检查 4 通过：__init__ 中 threading.Thread 调用数量为 1（_deferred_load）")
    return True


def check_lazy_init_method_preserved(content: str) -> bool:
    """检查 5：_lazy_init_vector_indexer 方法应保留"""
    pattern = r"def\s+_lazy_init_vector_indexer\s*\("
    if not re.search(pattern, content):
        print("❌ _lazy_init_vector_indexer 方法已被删除（应保留，延迟获取机制需要）")
        return False
    print("✅ 检查 5 通过：_lazy_init_vector_indexer 方法已保留")
    return True


def check_vector_indexer_property_preserved(content: str) -> bool:
    """检查 6：vector_indexer property 应保留"""
    pattern = r"@property\s*\n\s*def\s+vector_indexer\s*\("
    if not re.search(pattern, content):
        print("❌ vector_indexer property 已被删除（应保留，延迟获取机制需要）")
        return False
    print("✅ 检查 6 通过：vector_indexer property 已保留")
    return True


def check_reclassify_in_deferred_load_after_set(content: str) -> bool:
    """检查 7：reclassify_all_memories 应在 _data_loaded_event.set() 之后调用"""
    pattern = r"def\s+_deferred_load\s*\(\s*\)\s*:.*?(?=\n\s{8}threading\.Thread|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("❌ 未找到 _deferred_load 函数定义")
        return False
    deferred_load_body = match.group(0)
    set_pos = deferred_load_body.find("self._data_loaded_event.set()")
    reclassify_pos = deferred_load_body.find("self.reclassify_all_memories()")
    # 注意：_data_loaded_event.set() 出现两次（try 和 except），取第一次
    if set_pos == -1 or reclassify_pos == -1:
        print("❌ 未找到 _data_loaded_event.set() 或 reclassify_all_memories() 调用")
        return False
    if reclassify_pos < set_pos:
        print("❌ reclassify_all_memories 在 _data_loaded_event.set() 之前调用（应在之后）")
        return False
    print("✅ 检查 7 通过：reclassify_all_memories 在 _data_loaded_event.set() 之后调用")
    return True


def main():
    print("=" * 70)
    print("冗余预加载线程清理验证脚本")
    print(f"目标文件: {TARGET_FILE.relative_to(PROJECT_ROOT)}")
    print("=" * 70)

    content = read_target_file()

    checks = [
        check_no_lazy_init_thread,
        check_no_reclassify_thread,
        check_reclassify_in_deferred_load,
        check_thread_count,
        check_lazy_init_method_preserved,
        check_vector_indexer_property_preserved,
        check_reclassify_in_deferred_load_after_set,
    ]

    results = [check(content) for check in checks]
    all_pass = all(results)

    print("\n" + "=" * 70)
    if all_pass:
        print("✅ 所有检查通过！冗余预加载线程已正确清理。")
    else:
        print(f"❌ {sum(1 for r in results if not r)} 项检查未通过，请查看上方详情。")
    print("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())