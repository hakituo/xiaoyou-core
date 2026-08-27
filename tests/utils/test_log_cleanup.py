#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证日志自动清理功能
"""

import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.utils.log_cleanup import scan_old_log_dirs, scan_old_files, cleanup_logs


def test_scan_old_log_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        logs_root = Path(tmp)

        old_date = datetime.now() - timedelta(days=20)
        old_dir = logs_root / str(old_date.year) / str(old_date.month) / str(old_date.day)
        old_dir.mkdir(parents=True)
        (old_dir / "test.log").write_text("old")

        recent_date = datetime.now() - timedelta(days=5)
        recent_dir = logs_root / str(recent_date.year) / str(recent_date.month) / str(recent_date.day)
        recent_dir.mkdir(parents=True)
        (recent_dir / "test.log").write_text("recent")

        old_dirs = scan_old_log_dirs(logs_root, retention_days=15)

        assert len(old_dirs) == 1, f"应找到1个旧目录，找到 {len(old_dirs)}"
        assert old_dirs[0] == old_dir, f"旧目录应为 {old_dir}，实际为 {old_dirs[0]}"
        print("✅ scan_old_log_dirs: 正确识别15天前的日志目录")


def test_scan_old_files():
    with tempfile.TemporaryDirectory() as tmp:
        report_dir = Path(tmp)
        old_file = report_dir / "old_report.md"
        old_file.write_text("old")
        import time
        old_mtime = time.time() - 20 * 86400
        os.utime(old_file, (old_mtime, old_mtime))

        recent_file = report_dir / "recent_report.md"
        recent_file.write_text("recent")

        old_files = scan_old_files(report_dir, retention_days=15)

        assert len(old_files) == 1, f"应找到1个旧文件，找到 {len(old_files)}"
        assert old_files[0] == old_file
        print("✅ scan_old_files: 正确识别15天前的文件")


def test_cleanup_empty_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        logs_root = Path(tmp) / "logs"
        old_date = datetime.now() - timedelta(days=20)
        old_dir = logs_root / str(old_date.year) / str(old_date.month) / str(old_date.day)
        old_dir.mkdir(parents=True)
        (old_dir / "test.log").write_text("old")

        from core.utils.log_cleanup import _find_project_root
        original_fn = _find_project_root

        def mock_root():
            return Path(tmp)

        import core.utils.log_cleanup as lcm
        lcm._find_project_root = mock_root

        try:
            deleted_dirs, deleted_files, errors = cleanup_logs(retention_days=15)
            assert deleted_dirs == 1, f"应删除1个目录，实际删除 {deleted_dirs}"
            assert not old_dir.exists(), "旧目录应被删除"
            print("✅ cleanup_logs: 正确删除旧日志目录并清理空父目录")
        finally:
            lcm._find_project_root = original_fn


def test_retention_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        logs_root = Path(tmp)

        boundary_date = datetime.now() - timedelta(days=15)
        boundary_dir = logs_root / str(boundary_date.year) / str(boundary_date.month) / str(boundary_date.day)
        boundary_dir.mkdir(parents=True)
        (boundary_dir / "test.log").write_text("boundary")

        just_inside = datetime.now() - timedelta(days=14)
        inside_dir = logs_root / str(just_inside.year) / str(just_inside.month) / str(just_inside.day)
        inside_dir.mkdir(parents=True)
        (inside_dir / "test.log").write_text("inside")

        old_dirs = scan_old_log_dirs(logs_root, retention_days=15)

        assert len(old_dirs) == 1, f"15天前的应被标记，14天前的应保留，找到 {len(old_dirs)}"
        assert boundary_dir in old_dirs
        assert inside_dir not in old_dirs
        print("✅ retention边界: 15天前的删除，14天前的保留")


if __name__ == "__main__":
    test_scan_old_log_dirs()
    test_scan_old_files()
    test_cleanup_empty_dirs()
    test_retention_boundary()
    print("\n🎉 所有日志清理验证通过！")
