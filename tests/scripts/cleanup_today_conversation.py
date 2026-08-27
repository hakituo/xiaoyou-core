"""清理今天（2026-07-20）的对话记录和 weighted memory。

删除范围：
1. chat_history 目录下今天的 JSONL 文件
2. weighted memory 文件中今天的记录（按 timestamp 字段过滤）

用法：
    venv_core\Scripts\python.exe tests\scripts\cleanup_today_conversation.py
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# 2026-07-20 的时间戳范围（UTC）
TARGET_DATE = "2026-07-20"
START_TS = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp()
END_TS = datetime(2026, 7, 20, 23, 59, 59, tzinfo=timezone.utc).timestamp()


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parents[2]


def remove_chat_history_dirs(root: Path) -> list[str]:
    """删除 chat_history 目录下今天的日期目录"""
    removed = []
    for scope in ("aveline_data", "ling_data"):
        chat_dir = root / "companion_data" / scope / "chat_history" / "2026" / "07" / "20"
        if chat_dir.exists():
            shutil.rmtree(chat_dir)
            removed.append(str(chat_dir))
            print(f"已删除: {chat_dir}")
    return removed


def filter_weighted_memories(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """从 weighted memory 数据中删除今天的记录

    返回: (过滤后的数据, 删除的记录数)
    """
    memories = data.get("weighted_memories", [])
    original_count = len(memories)
    filtered = []

    for mem in memories:
        ts = mem.get("timestamp", 0)
        # 保留非今天的记录
        if not (START_TS <= ts <= END_TS):
            filtered.append(mem)

    removed_count = original_count - len(filtered)
    if removed_count > 0:
        data["weighted_memories"] = filtered
        return data, removed_count
    return data, 0


def process_weighted_files(root: Path) -> list[tuple[str, int]]:
    """处理所有 weighted memory 文件"""
    weighted_base = root / "companion_data" / "aveline_data" / "memories" / "weighted"
    results = []

    if not weighted_base.exists():
        print(f"weighted 目录不存在: {weighted_base}")
        return results

    # 遍历所有 weighted 目录和子目录
    for json_file in weighted_base.rglob("*.json"):
        # 跳过 tmp 文件
        if ".tmp_" in json_file.name:
            continue

        try:
            content = json_file.read_text(encoding="utf-8")
            data = json.loads(content)

            # 检查是否有 weighted_memories 字段
            if "weighted_memories" not in data:
                continue

            new_data, removed = filter_weighted_memories(data)
            if removed > 0:
                # 写回文件
                json_file.write_text(
                    json.dumps(new_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                results.append((str(json_file), removed))
                print(f"已清理: {json_file} (删除 {removed} 条记录)")

        except Exception as e:
            print(f"处理文件失败 {json_file}: {e}")

    return results


def main():
    root = get_project_root()
    print(f"项目根目录: {root}")
    print(f"目标日期: {TARGET_DATE}")
    print(f"时间戳范围: {START_TS} - {END_TS}")
    print()

    # 1. 删除 chat_history 目录
    print("=== 删除 chat_history 目录 ===")
    chat_removed = remove_chat_history_dirs(root)
    print(f"删除了 {len(chat_removed)} 个目录")
    print()

    # 2. 处理 weighted memory 文件
    print("=== 清理 weighted memory ===")
    weighted_results = process_weighted_files(root)
    total_removed = sum(count for _, count in weighted_results)
    print(f"清理了 {len(weighted_results)} 个文件，共删除 {total_removed} 条记录")
    print()

    # 汇总
    print("=== 清理完成 ===")
    print(f"chat_history 目录: {len(chat_removed)} 个")
    print(f"weighted memory: {len(weighted_results)} 个文件, {total_removed} 条记录")


if __name__ == "__main__":
    main()