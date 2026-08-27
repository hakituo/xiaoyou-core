"""验证 atomic_io.py 的两个修复：

1. safe_json_dump 在写入前清理陈旧的 .tmp_* 残留临时文件
2. async_safe_json_dump 同样清理陈旧临时文件
3. 不会误删正在写入的临时文件（5 分钟内的）
4. 不会误删其他文件的临时文件
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# 添加项目根到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.utils.atomic_io import (
    _cleanup_stale_temp_files,
    _generate_temp_path,
    _STALE_TEMP_FILE_TTL_SECONDS,
    safe_json_dump,
    async_safe_json_load,
)
import asyncio


def make_stale_file(target_path: str, age_seconds: float) -> str:
    """为目标文件创建一个陈旧的临时文件"""
    temp_path = _generate_temp_path(target_path)
    Path(temp_path).write_text("stale", encoding="utf-8")
    # 把 mtime 设为 age_seconds 前
    old_time = time.time() - age_seconds
    os.utime(temp_path, (old_time, old_time))
    return temp_path


def test_cleanup_stale_temp_files_removes_old():
    """陈旧的临时文件应该被清理"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data.json")
        stale = make_stale_file(target, _STALE_TEMP_FILE_TTL_SECONDS + 60)
        assert os.path.exists(stale), "前置：陈旧文件存在"

        _cleanup_stale_temp_files(target)

        assert not os.path.exists(stale), "陈旧临时文件应被清理"
        print("[OK] 陈旧临时文件被清理")


def test_cleanup_stale_temp_files_keeps_recent():
    """近期的临时文件不应该被清理"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data.json")
        recent = make_stale_file(target, 30)  # 30 秒前
        assert os.path.exists(recent), "前置：近期文件存在"

        _cleanup_stale_temp_files(target)

        assert os.path.exists(recent), "近期临时文件不应被清理"
        print("[OK] 近期临时文件保留")
        os.remove(recent)


def test_cleanup_stale_temp_files_only_same_prefix():
    """只清理同前缀的临时文件，不影响其他文件"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data.json")
        other_target = os.path.join(tmp, "other.json")

        stale_for_target = make_stale_file(target, _STALE_TEMP_FILE_TTL_SECONDS + 60)
        stale_for_other = make_stale_file(other_target, _STALE_TEMP_FILE_TTL_SECONDS + 60)

        _cleanup_stale_temp_files(target)

        assert not os.path.exists(stale_for_target), "目标文件的陈旧临时文件应被清理"
        assert os.path.exists(stale_for_other), "其他文件的临时文件不应被清理"
        print("[OK] 只清理目标文件的临时文件")
        os.remove(stale_for_other)


def test_safe_json_dump_cleans_stale_before_write():
    """safe_json_dump 在写入前应清理陈旧临时文件"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data.json")
        # 创建一个陈旧的临时文件
        stale = make_stale_file(target, _STALE_TEMP_FILE_TTL_SECONDS + 60)
        assert os.path.exists(stale)

        # 写入数据
        safe_json_dump({"hello": "world"}, target)

        # 目标文件应存在且内容正确
        assert os.path.exists(target)
        data = json.loads(Path(target).read_text(encoding="utf-8"))
        assert data == {"hello": "world"}

        # 陈旧临时文件应被清理
        assert not os.path.exists(stale), "safe_json_dump 应清理陈旧临时文件"
        print("[OK] safe_json_dump 在写入前清理陈旧临时文件")


def test_safe_json_dump_normal_write_unaffected():
    """正常的写入流程不受影响"""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data.json")

        # 连续写入多次
        for i in range(5):
            safe_json_dump({"i": i}, target)

        data = json.loads(Path(target).read_text(encoding="utf-8"))
        assert data == {"i": 4}

        # 不应残留任何 .tmp_* 文件
        tmp_files = list(Path(tmp).glob("*.tmp_*"))
        assert not tmp_files, f"不应有临时文件残留: {tmp_files}"
        print("[OK] 正常写入流程不受影响，无残留")


def test_async_safe_json_dump_cleans_stale():
    """async_safe_json_dump 在写入前应清理陈旧临时文件"""
    from core.utils.atomic_io import async_safe_json_dump

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "data.json")
            stale = make_stale_file(target, _STALE_TEMP_FILE_TTL_SECONDS + 60)
            assert os.path.exists(stale)

            await async_safe_json_dump({"async": True}, target)

            data = json.loads(Path(target).read_text(encoding="utf-8"))
            assert data == {"async": True}
            assert not os.path.exists(stale), "async 版本应清理陈旧临时文件"
        print("[OK] async_safe_json_dump 在写入前清理陈旧临时文件")

    asyncio.run(run())


def test_cleanup_silent_on_missing_dir():
    """目录不存在时不应抛异常"""
    _cleanup_stale_temp_files("/nonexistent/path/data.json")
    print("[OK] 目录不存在时不抛异常")


def test_cleanup_silent_on_unreadable_dir():
    """目录不可读时不应抛异常"""
    # 用一个不存在的盘符路径模拟
    _cleanup_stale_temp_files("Z:\\nonexistent_drive\\data.json")
    print("[OK] 目录不可读时不抛异常")


def main():
    print("=== atomic_io 修复验证 ===")
    print(f"_STALE_TEMP_FILE_TTL_SECONDS = {_STALE_TEMP_FILE_TTL_SECONDS}")
    print()
    test_cleanup_stale_temp_files_removes_old()
    test_cleanup_stale_temp_files_keeps_recent()
    test_cleanup_stale_temp_files_only_same_prefix()
    test_safe_json_dump_cleans_stale_before_write()
    test_safe_json_dump_normal_write_unaffected()
    test_async_safe_json_dump_cleans_stale()
    test_cleanup_silent_on_missing_dir()
    test_cleanup_silent_on_unreadable_dir()
    print()
    print("ALL PASS")


if __name__ == "__main__":
    main()
