"""
验证 async_safe_json_dump 并发写入同一目标文件时的竞态修复。

背景：多个 ActiveCareStorage 实例（nightly_processor / anomaly_detector /
active_care 服务等）会并发写入同一个 proactive_state.json。旧实现使用
固定 .tmp 临时文件名，一个实例替换走 .tmp 后另一个实例 os.replace 报
WinError 2。修复后使用 _generate_temp_path 生成线程+进程唯一的临时文件名。
"""
import asyncio
import os
import sys
import tempfile

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from core.utils.atomic_io import async_safe_json_dump, async_safe_json_load


async def _write_once(file_path: str, idx: int) -> None:
    """单次并发写入任务"""
    payload = {"writer": idx, "data": f"payload-{idx}"}
    await async_safe_json_dump(payload, file_path, use_fsync=True)


async def test_concurrent_writes_no_winerror2(tmp_path):
    """并发写入同一文件不应抛出 FileNotFoundError / WinError 2"""
    target = str(tmp_path / "concurrent_target.json")

    # 20 个并发写入任务，模拟多个 Storage 实例同时落盘
    tasks = [_write_once(target, i) for i in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"并发写入出现失败: {failures}"

    # 目标文件最终应存在且是合法 JSON
    loaded = await async_safe_json_load(target)
    assert loaded is not None
    assert "writer" in loaded

    # 不应残留任何 .tmp / .tmp_xxx 临时文件
    leftover = [f for f in os.listdir(tmp_path) if f.endswith(".tmp") or ".tmp_" in f]
    assert not leftover, f"残留临时文件: {leftover}"


async def test_concurrent_writes_via_multiple_storage_instances(tmp_path):
    """多个 ActiveCareStorage 实例并发写入同一 proactive_state.json"""
    from core.services.active_care.storage.storage import ActiveCareStorage

    storage_a = ActiveCareStorage()
    storage_b = ActiveCareStorage()

    # 指向同一个临时目录，模拟同一 scope 下的并发写入
    target_dir = str(tmp_path)
    state_file = os.path.join(target_dir, "proactive_state.json")

    async def _save(storage, key: str):
        # 直接调用底层写入接口，绕过 runtime_scope 解析
        await storage._write_json_file(state_file, {"writer": key, "data": "x" * 100})

    tasks = [_save(storage_a, f"A-{i}") for i in range(10)] + \
            [_save(storage_b, f"B-{i}") for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"多 Storage 实例并发写入失败: {failures}"

    assert os.path.exists(state_file), "目标文件未生成"


async def test_temp_path_uniqueness():
    """验证 _generate_temp_path 生成唯一路径（回归测试）"""
    from core.utils.atomic_io import _generate_temp_path

    base = "D:/tmp/proactive_state.json"
    # 同一线程内连续调用 50 次应得到 50 个不同路径（uuid 保证唯一）
    paths = {_generate_temp_path(base) for _ in range(50)}
    assert len(paths) == 50, f"临时路径未唯一: {len(paths)}/50"
    # 均不应等于旧的固定 .tmp 路径
    assert f"{base}.tmp" not in paths
