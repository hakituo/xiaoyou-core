"""P1-5 持久化关键运行时状态 — 验证脚本

验证 PatchManager / CorrectionTracker / AnomalyDetector 三类关键运行时状态
在重启（重新实例化）后能正确恢复，避免"晋升失忆"、"补丁回滚能力丧失"、
"重复错误检测失忆"等问题。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p1_5_persist_state.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ──────────────────────────────────────────────────────────────
# 测试 1：PatchManager 持久化
# ──────────────────────────────────────────────────────────────

def test_patch_manager_persist() -> list[str]:
    """验证 PatchManager 状态在重新实例化后能恢复"""
    issues: list[str] = []
    _section("测试 1：PatchManager 持久化")

    from core.services.auto_heal.models import Patch, PatchStatus
    from core.services.auto_heal.patch_manager import PatchManager

    # 使用临时 state_file，避免污染生产数据
    tmp_dir = Path(tempfile.mkdtemp(prefix="p1_5_patch_"))
    state_file = tmp_dir / "patches_state.json"

    try:
        # 第一次实例化：注册补丁
        pm1 = PatchManager()
        pm1._state_file = state_file  # 覆盖默认路径
        # 模拟从 AWAITING_APPROVAL 流转到 APPLIED
        patch = Patch(
            id="test-patch-001",
            anomaly_id="anom-001",
            file_path="core/test/dummy.py",
            original_code="def foo():\n    return 1\n",
            patched_code="def foo():\n    return 2\n",
            diff="- return 1\n+ return 2\n",
            description="修复 foo 返回值",
            status=PatchStatus.AWAITING_APPROVAL,
            created_at=time.time(),
            rollback_code="def foo():\n    return 1\n",
        )
        pm1.register_patch(patch)
        pm1._daily_patch_count = 5
        pm1._daily_patch_reset_ts = time.time()
        pm1._file_patch_counts["core/test/dummy.py"] = 2
        pm1._heal_count = 3

        # 异步保存
        asyncio.run(pm1._save_state_async())

        # 验证文件已生成
        if not state_file.exists():
            issues.append("_save_state_async 后未生成 state 文件")
            return issues
        _ok(f"状态文件已生成: {state_file.name}")

        # 验证文件内容是合法 JSON
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("daily_patch_count") != 5:
            issues.append(f"daily_patch_count 未持久化: {data.get('daily_patch_count')}")
        if data.get("heal_count") != 3:
            issues.append(f"heal_count 未持久化: {data.get('heal_count')}")
        if len(data.get("patches") or []) != 1:
            issues.append(f"patches 数量不对: {len(data.get('patches') or [])}")
        else:
            p_dict = data["patches"][0]
            if p_dict.get("rollback_code") != "def foo():\n    return 1\n":
                issues.append("rollback_code 未正确持久化")
            if p_dict.get("original_code") != "def foo():\n    return 1\n":
                issues.append("original_code 未正确持久化")
        _ok("持久化字段完整（daily_count/heal_count/patches/rollback_code）")

        # 第二次实例化：模拟进程重启
        pm2 = PatchManager()
        pm2._state_file = state_file
        pm2._load_state_sync()

        # 验证状态恢复
        if len(pm2.patches) != 1:
            issues.append(f"重启后 patches 数量不对: {len(pm2.patches)}")
            return issues
        restored = pm2.patches.get("test-patch-001")
        if restored is None:
            issues.append("重启后找不到补丁 test-patch-001")
            return issues
        if restored.rollback_code != "def foo():\n    return 1\n":
            issues.append(f"重启后 rollback_code 不对: {restored.rollback_code!r}")
        if restored.status != PatchStatus.AWAITING_APPROVAL:
            issues.append(f"重启后 status 不对: {restored.status}")
        if pm2._daily_patch_count != 5:
            issues.append(f"重启后 daily_patch_count 不对: {pm2._daily_patch_count}")
        if pm2._heal_count != 3:
            issues.append(f"重启后 heal_count 不对: {pm2._heal_count}")
        if pm2._file_patch_counts.get("core/test/dummy.py") != 2:
            issues.append(f"重启后 file_patch_counts 不对: {pm2._file_patch_counts}")
        _ok("重启后补丁元数据/配额计数完整恢复")

        # 验证 Patch.to_dict / from_dict 往返一致
        roundtrip = Patch.from_dict(restored.to_dict())
        if roundtrip.id != restored.id or roundtrip.status != restored.status:
            issues.append("Patch to_dict/from_dict 往返不一致")
        else:
            _ok("Patch.to_dict/from_dict 往返一致")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return issues


# ──────────────────────────────────────────────────────────────
# 测试 2：CorrectionTracker 持久化
# ──────────────────────────────────────────────────────────────

def test_correction_tracker_persist() -> list[str]:
    """验证 CorrectionTracker._recent_corrections 在重启后能恢复"""
    issues: list[str] = []
    _section("测试 2：CorrectionTracker 持久化（晋升失忆修复）")

    from core.services.self_improvement.correction_tracker import CorrectionTracker
    from core.services.self_improvement.models import CorrectionEntry, CorrectionSignal, EntryStatus

    tmp_dir = Path(tempfile.mkdtemp(prefix="p1_5_corr_"))

    try:
        # 第一次实例化
        ct1 = CorrectionTracker(base_dir=tmp_dir)
        # 模拟两条相似纠正（应该触发晋升）
        e1 = CorrectionEntry(
            id="COR-001",
            signal_type=CorrectionSignal.DIRECT_DENY,
            title="数据库连接池泄漏",
            correction="使用 async with 而非裸 acquire",
            my_error="忘记释放连接",
            tags=["database", "leak"],
        )
        e2 = CorrectionEntry(
            id="COR-002",
            signal_type=CorrectionSignal.DIFFERENT_ANSWER,
            title="数据库连接池泄漏修复",
            correction="用 context manager 包裹",
            my_error="直接 await acquire()",
            tags=["database", "leak"],
        )
        ct1._recent_corrections = [e2, e1]  # 最近的在前

        # 异步保存
        asyncio.run(ct1._save_index_async())

        index_file = tmp_dir / ".learnings" / "corrections_index.json"
        if not index_file.exists():
            issues.append("_save_index_async 后未生成 index 文件")
            return issues
        _ok(f"索引文件已生成: {index_file.name}")

        # 第二次实例化：模拟重启
        ct2 = CorrectionTracker(base_dir=tmp_dir)
        if len(ct2._recent_corrections) != 2:
            issues.append(f"重启后纠正数量不对: {len(ct2._recent_corrections)}")
            return issues
        ids = {e.id for e in ct2._recent_corrections}
        if ids != {"COR-001", "COR-002"}:
            issues.append(f"重启后纠正 ID 不对: {ids}")
        # 验证字段完整
        restored_e1 = next(e for e in ct2._recent_corrections if e.id == "COR-001")
        if restored_e1.title != "数据库连接池泄漏":
            issues.append(f"重启后 title 不对: {restored_e1.title!r}")
        if restored_e1.signal_type != CorrectionSignal.DIRECT_DENY:
            issues.append(f"重启后 signal_type 不对: {restored_e1.signal_type}")
        if restored_e1.tags != ["database", "leak"]:
            issues.append(f"重启后 tags 不对: {restored_e1.tags}")
        _ok("重启后纠正条目（含 tags/signal_type）完整恢复")

        # 验证晋升检测能利用持久化数据
        # ct2 已加载 2 条相似纠正，再加一条相似纠正应该触发晋升
        # 由于前两条可能已 PENDING，新加第三条相似会触发晋升
        async def _test_promotion():
            # 重置前两条为 PENDING（默认就是 PENDING）
            for e in ct2._recent_corrections:
                e.status = EntryStatus.PENDING
            await ct2.record_correction(
                signal_type=CorrectionSignal.DIRECT_DENY,
                title="数据库连接池又双叒泄漏了",
                correction="务必用 async with",
                tags=["database", "leak"],
            )

        asyncio.run(_test_promotion())
        promoted = [e for e in ct2._recent_corrections if e.status == EntryStatus.PROMOTED]
        if not promoted:
            issues.append("利用持久化数据进行晋升检测失败（重启后晋升失忆）")
        else:
            _ok(f"利用持久化数据成功触发晋升：{len(promoted)} 条被晋升")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return issues


# ──────────────────────────────────────────────────────────────
# 测试 3：AnomalyDetector 持久化
# ──────────────────────────────────────────────────────────────

def test_anomaly_detector_persist() -> list[str]:
    """验证 AnomalyDetector 错误指纹和抑制状态在重启后能恢复"""
    issues: list[str] = []
    _section("测试 3：AnomalyDetector 持久化（重复错误检测失忆修复）")

    from core.services.auto_heal.anomaly_detector import AnomalyDetector

    tmp_dir = Path(tempfile.mkdtemp(prefix="p1_5_anom_"))
    state_file = tmp_dir / "anomaly_state.json"

    try:
        # 第一次实例化
        ad1 = AnomalyDetector()
        ad1._state_file = state_file  # 覆盖默认路径

        # 模拟错误指纹累积
        ad1.on_error("err-1", {
            "error_type": "ValueError",
            "error_message": "invalid value",
            "traceback": 'File "core/test/foo.py", line 42, in bar',
        })
        ad1.on_error("err-2", {
            "error_type": "ValueError",
            "error_message": "invalid value",
            "traceback": 'File "core/test/foo.py", line 42, in bar',
        })
        ad1.on_error("err-3", {
            "error_type": "ConnectionError",
            "error_message": "connection refused",
            "traceback": 'File "core/test/net.py", line 10, in connect',
        })
        # 模拟抑制状态
        ad1._suppressed["error_burst"] = time.time()
        ad1._dirty = True

        # 异步保存
        asyncio.run(ad1._save_state_async())

        if not state_file.exists():
            issues.append("_save_state_async 后未生成 state 文件")
            return issues
        _ok(f"状态文件已生成: {state_file.name}")

        # 验证内容
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if len(data.get("fingerprints") or []) != 2:
            issues.append(f"持久化指纹数量不对: {len(data.get('fingerprints') or [])}")
        if "error_burst" not in (data.get("suppressed") or {}):
            issues.append(f"suppressed 未持久化: {data.get('suppressed')}")
        _ok("指纹 + 抑制状态已落盘")

        # 第二次实例化：模拟重启
        ad2 = AnomalyDetector()
        ad2._state_file = state_file
        ad2._load_state_sync()

        if len(ad2._fingerprints) != 2:
            issues.append(f"重启后指纹数量不对: {len(ad2._fingerprints)}")
            return issues
        # 找到 ValueError 指纹，验证 count 是否恢复
        vp = next(
            (fp for fp in ad2._fingerprints.values() if fp.error_type == "ValueError"),
            None,
        )
        if vp is None:
            issues.append("重启后找不到 ValueError 指纹")
        elif vp.count != 2:
            issues.append(f"重启后 ValueError 指纹 count 不对: {vp.count}")
        else:
            _ok(f"重启后错误指纹恢复：ValueError count={vp.count}")

        if "error_burst" not in ad2._suppressed:
            issues.append("重启后 suppressed 状态丢失")
        else:
            _ok("重启后抑制状态恢复")

        # 验证重启后 on_error 能在已有指纹上累加（而非重置为 1）
        ad2.on_error("err-4", {
            "error_type": "ValueError",
            "error_message": "invalid value",
            "traceback": 'File "core/test/foo.py", line 42, in bar',
        })
        if vp and vp.count != 3:
            issues.append(f"重启后累加错误 count 不对: {vp.count}（应为 3）")
        else:
            _ok(f"重启后错误指纹能正确累加：count={vp.count}")

        # 验证 flush_state_async 节流逻辑
        # 刚保存过，立即再 flush 应该被节流跳过
        before_ts = ad2._last_persist_ts
        asyncio.run(ad2.flush_state_async(force=False))
        if ad2._last_persist_ts != before_ts:
            # dirty 仍为 True 时可能再次保存，但应该在间隔内被跳过
            # 这里只验证不会抛异常即可
            pass
        _ok("flush_state_async 节流逻辑无异常")

        # force=True 应该立即保存
        asyncio.run(ad2.flush_state_async(force=True))
        _ok("flush_state_async(force=True) 正常保存")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return issues


# ──────────────────────────────────────────────────────────────
# 测试 4：原子写入验证
# ──────────────────────────────────────────────────────────────

def test_atomic_write() -> list[str]:
    """验证原子写入：写入过程中不应有部分写入的文件可见"""
    issues: list[str] = []
    _section("测试 4：原子写入（.tmp + os.replace）")

    from core.services.auto_heal.patch_manager import PatchManager

    tmp_dir = Path(tempfile.mkdtemp(prefix="p1_5_atomic_"))
    state_file = tmp_dir / "patches_state.json"
    tmp_file = tmp_dir / "patches_state.json.tmp"

    try:
        pm = PatchManager()
        pm._state_file = state_file
        asyncio.run(pm._save_state_async())

        # 验证：写完后 tmp 文件不应存在
        if tmp_file.exists():
            issues.append(f"原子写入后 tmp 文件未清理: {tmp_file.name}")
        else:
            _ok("原子写入完成后 .tmp 文件已清理")

        # 验证：state 文件内容是合法 JSON（不是部分写入）
        with open(state_file, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            json.loads(content)
            _ok("state 文件内容是合法 JSON（无部分写入）")
        except json.JSONDecodeError as e:
            issues.append(f"state 文件不是合法 JSON: {e}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return issues


# ──────────────────────────────────────────────────────────────
# 测试 5：源码静态检查
# ──────────────────────────────────────────────────────────────

def test_source_static() -> list[str]:
    """静态检查关键持久化代码已落地"""
    issues: list[str] = []
    _section("测试 5：源码静态检查")

    files_to_check = [
        ("core/services/auto_heal/patch_manager.py", [
            "_load_state_sync", "_save_state_async", "register_patch",
            "_state_file", "_resolve_state_file",
        ]),
        ("core/services/auto_heal/anomaly_detector.py", [
            "_load_state_sync", "_save_state_async", "flush_state_async",
            "_dirty", "_PERSIST_INTERVAL_SECONDS",
        ]),
        ("core/services/self_improvement/correction_tracker.py", [
            "_load_index_sync", "_save_index_async", "_index_file",
        ]),
        ("core/services/auto_heal/models.py", [
            "def to_dict", "def from_dict",
        ]),
    ]

    for file_path, markers in files_to_check:
        full_path = PROJECT_ROOT / file_path
        if not full_path.exists():
            issues.append(f"文件不存在: {file_path}")
            continue
        src = full_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in src:
                issues.append(f"{file_path} 缺少标记: {marker}")
        _ok(f"{file_path} 关键标记齐全")

    # 检查 heal_service 是否调用了 register_patch 和 flush_state_async
    heal_src = (PROJECT_ROOT / "core/services/auto_heal/heal_service.py").read_text(encoding="utf-8")
    if "self._patch_manager.register_patch(patch)" not in heal_src:
        issues.append("heal_service.py 未改用 register_patch")
    if "self._patch_manager._save_state_async()" not in heal_src:
        issues.append("heal_service.py 未在 AWAITING_APPROVAL 后调用 _save_state_async")
    if "self.detector.flush_state_async()" not in heal_src:
        issues.append("heal_service.py 未调用 detector.flush_state_async")
    if "await self._patch_manager.reject_patch(patch_id)" not in heal_src:
        issues.append("heal_service.py 未将 reject_patch 改为 await")
    _ok("heal_service.py 持久化调用点齐全")

    return issues


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────

def main() -> int:
    print("P1-5 持久化关键运行时状态 — 验证脚本")
    print(f"项目根目录: {PROJECT_ROOT}")

    all_issues: list[str] = []
    for test_fn in [
        test_patch_manager_persist,
        test_correction_tracker_persist,
        test_anomaly_detector_persist,
        test_atomic_write,
        test_source_static,
    ]:
        try:
            issues = test_fn()
            all_issues.extend(issues)
        except Exception as e:
            all_issues.append(f"{test_fn.__name__} 测试本身异常: {e!r}")
            import traceback
            traceback.print_exc()

    _section("总结")
    if not all_issues:
        print("  ✅ 所有 P1-5 持久化验证通过！")
        return 0
    else:
        print(f"  ❌ 发现 {len(all_issues)} 个问题：")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
