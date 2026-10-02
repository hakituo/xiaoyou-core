"""P0-16 验证脚本：core_memory.py 非原子写入 MEMORY.md

验证目标：
1. atomic_io.py 新增 safe_write_text / safe_read_text / async 版本
2. core_memory.py 的 _save_sync 和 ensure_initialized 使用 safe_write_text（不再用 write_text）
3. safe_write_text 原子性：写入失败时原文件内容不变，且无临时文件残留
4. safe_write_text 基本功能：正常写入内容正确
5. CoreMemory.save() 端到端：保存后文件内容正确，多次保存不损坏
6. CoreMemory.ensure_initialized() 端到端：创建的文件内容正确
7. 并发安全：多个 CoreMemory 实例并发 save 不损坏文件

修复要点：
- atomic_io.py 新增 safe_write_text / safe_read_text / async_safe_write_text / async_safe_read_text
- core_memory.py 的 _save_sync 改用 safe_write_text 替代 write_text
- core_memory.py 的 ensure_initialized 改用 safe_write_text 替代 write_text
"""
import asyncio
import inspect
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# 1. atomic_io.py 新增函数存在性检查
# ============================================================================

def check_atomic_io_has_safe_write_text() -> list[str]:
    """场景1：atomic_io 应提供 safe_write_text 函数。"""
    issues: list[str] = []
    from core.utils import atomic_io

    if not hasattr(atomic_io, "safe_write_text"):
        issues.append("atomic_io 缺少 safe_write_text 函数")
        return issues

    if not callable(atomic_io.safe_write_text):
        issues.append("atomic_io.safe_write_text 不可调用")

    # 检查签名：应接受 text, file_path, encoding, use_fsync
    sig = inspect.signature(atomic_io.safe_write_text)
    params = list(sig.parameters.keys())
    expected = ["text", "file_path", "encoding", "use_fsync"]
    if params[:4] != expected:
        issues.append(
            f"safe_write_text 签名前 4 个参数应为 {expected}，实际 {params[:4]}"
        )

    return issues


def check_atomic_io_has_safe_read_text() -> list[str]:
    """场景2：atomic_io 应提供 safe_read_text 函数。"""
    issues: list[str] = []
    from core.utils import atomic_io

    if not hasattr(atomic_io, "safe_read_text"):
        issues.append("atomic_io 缺少 safe_read_text 函数")
        return issues

    if not callable(atomic_io.safe_read_text):
        issues.append("atomic_io.safe_read_text 不可调用")

    return issues


def check_atomic_io_has_async_safe_write_text() -> list[str]:
    """场景3：atomic_io 应提供 async_safe_write_text 函数。"""
    issues: list[str] = []
    from core.utils import atomic_io

    if not hasattr(atomic_io, "async_safe_write_text"):
        issues.append("atomic_io 缺少 async_safe_write_text 函数")
        return issues

    if not callable(atomic_io.async_safe_write_text):
        issues.append("atomic_io.async_safe_write_text 不可调用")

    # 应该是协程函数
    if not asyncio.iscoroutinefunction(atomic_io.async_safe_write_text):
        issues.append("async_safe_write_text 应为协程函数")

    return issues


def check_atomic_io_has_async_safe_read_text() -> list[str]:
    """场景4：atomic_io 应提供 async_safe_read_text 函数。"""
    issues: list[str] = []
    from core.utils import atomic_io

    if not hasattr(atomic_io, "async_safe_read_text"):
        issues.append("atomic_io 缺少 async_safe_read_text 函数")
        return issues

    if not asyncio.iscoroutinefunction(atomic_io.async_safe_read_text):
        issues.append("async_safe_read_text 应为协程函数")

    return issues


# ============================================================================
# 2. core_memory.py 源码检查：不再用 write_text 写 MEMORY.md
# ============================================================================

def check_core_memory_save_uses_safe_write_text() -> list[str]:
    """场景5：_save_sync 应使用 safe_write_text，不再用 Path.write_text。"""
    issues: list[str] = []
    from core.services.self_improvement.core_memory import CoreMemory

    src = inspect.getsource(CoreMemory._save_sync)

    # 注意：safe_write_text 函数名本身包含 "write_text" 子串，
    # 所以检查 Path.write_text 调用模式（self._memory_file.write_text）而非裸 "write_text"
    if "self._memory_file.write_text" in src or ".write_text(" in src:
        issues.append("_save_sync 仍包含 Path.write_text 调用，未迁移到原子写入")

    if "safe_write_text" not in src:
        issues.append("_save_sync 未使用 safe_write_text")

    return issues


def check_core_memory_ensure_init_uses_safe_write_text() -> list[str]:
    """场景6：ensure_initialized 应使用 safe_write_text，不再用 Path.write_text。"""
    issues: list[str] = []
    from core.services.self_improvement.core_memory import CoreMemory

    src = inspect.getsource(CoreMemory.ensure_initialized)

    if "self._memory_file.write_text" in src or ".write_text(" in src:
        issues.append("ensure_initialized 仍包含 Path.write_text 调用，未迁移到原子写入")

    if "safe_write_text" not in src:
        issues.append("ensure_initialized 未使用 safe_write_text")

    return issues


def check_core_memory_imports_safe_write_text() -> list[str]:
    """场景7：core_memory 应从 atomic_io 导入 safe_write_text。"""
    issues: list[str] = []
    import core.services.self_improvement.core_memory as cm

    src = inspect.getsource(cm)
    if "from core.utils.atomic_io import" not in src:
        issues.append("core_memory 未从 atomic_io 导入")
    elif "safe_write_text" not in src:
        issues.append("core_memory 未导入 safe_write_text")

    return issues


# ============================================================================
# 3. safe_write_text 基本功能与原子性测试
# ============================================================================

def check_safe_write_text_basic() -> list[str]:
    """场景8：safe_write_text 正常写入内容正确。"""
    issues: list[str] = []
    from core.utils.atomic_io import safe_write_text, safe_read_text

    with tempfile.TemporaryDirectory() as tmpdir:
        fp = Path(tmpdir) / "test.txt"
        content = "hello\nworld\n中文测试\n"
        try:
            safe_write_text(content, fp, encoding="utf-8")
        except Exception as e:
            issues.append(f"safe_write_text 写入异常: {type(e).__name__}: {e}")
            return issues

        if not fp.exists():
            issues.append("safe_write_text 写入后文件不存在")
            return issues

        read_back = safe_read_text(fp, encoding="utf-8")
        if read_back != content:
            issues.append(
                f"写入内容与读回内容不一致\n"
                f"  期望: {content!r}\n"
                f"  实际: {read_back!r}"
            )

    return issues


def check_safe_write_text_atomicity() -> list[str]:
    """场景9：safe_write_text 原子性 - 写入失败时原文件内容不变，无临时文件残留。

    模拟 _retry_os_replace 抛异常，验证：
    1. 原文件内容不变
    2. 临时文件被清理
    """
    issues: list[str] = []
    from core.utils import atomic_io

    with tempfile.TemporaryDirectory() as tmpdir:
        fp = Path(tmpdir) / "test_atomic.txt"
        original = "original content\n"
        # 先写入原始内容
        fp.write_text(original, encoding="utf-8")

        # 模拟 _retry_os_replace 失败
        new_content = "new content that should NOT be written\n"
        with patch.object(
            atomic_io, "_retry_os_replace", side_effect=OSError("模拟替换失败")
        ):
            try:
                atomic_io.safe_write_text(new_content, fp, encoding="utf-8")
                issues.append("safe_write_text 应在 _retry_os_replace 失败时抛异常")
            except OSError:
                pass  # 预期行为
            except Exception as e:
                issues.append(
                    f"safe_write_text 抛出了非预期异常类型: {type(e).__name__}: {e}"
                )

        # 验证原文件内容不变
        actual = fp.read_text(encoding="utf-8")
        if actual != original:
            issues.append(
                f"原子写入失败后原文件被修改了！\n"
                f"  期望: {original!r}\n"
                f"  实际: {actual!r}"
            )

        # 验证无临时文件残留
        tmp_files = list(fp.parent.glob(f"{fp.name}.tmp_*"))
        if tmp_files:
            issues.append(
                f"原子写入失败后留下临时文件残留: {[str(p) for p in tmp_files]}"
            )

    return issues


def check_safe_write_text_overwrite() -> list[str]:
    """场景10：safe_write_text 覆盖已有文件，新内容正确。"""
    issues: list[str] = []
    from core.utils.atomic_io import safe_write_text, safe_read_text

    with tempfile.TemporaryDirectory() as tmpdir:
        fp = Path(tmpdir) / "overwrite.txt"
        # 先写入旧内容
        safe_write_text("old content\n", fp)
        # 覆盖写入新内容
        new_content = "new content\nline2\n"
        safe_write_text(new_content, fp)

        actual = safe_read_text(fp)
        if actual != new_content:
            issues.append(
                f"覆盖写入后内容不正确\n  期望: {new_content!r}\n  实际: {actual!r}"
            )

    return issues


def check_async_safe_write_text() -> list[str]:
    """场景11：async_safe_write_text 异步写入内容正确。"""
    issues: list[str] = []
    from core.utils.atomic_io import async_safe_write_text, async_safe_read_text

    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "async_test.txt"
            content = "async content\n异步测试\n"
            await async_safe_write_text(content, fp, encoding="utf-8")

            if not fp.exists():
                issues.append("async_safe_write_text 写入后文件不存在")
                return

            read_back = await async_safe_read_text(fp, encoding="utf-8")
            if read_back != content:
                issues.append(
                    f"异步写入内容与读回内容不一致\n  期望: {content!r}\n  实际: {read_back!r}"
                )

    asyncio.run(run())
    return issues


# ============================================================================
# 4. CoreMemory 端到端测试
# ============================================================================

def check_core_memory_save_end_to_end() -> list[str]:
    """场景12：CoreMemory.save() 保存后文件内容正确。"""
    issues: list[str] = []
    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "memory"
            cm = CoreMemory(base_dir=base_dir, scope="user")
            cm.ensure_initialized()

            # 加载并添加条目
            await cm.load()
            await cm.add_item(MemorySection.PREFERENCES, "用户喜欢深色主题")
            await cm.add_item(MemorySection.EXPERIENCE, "遇到 WebSocket 断连先检查心跳")
            await cm.add_item(MemorySection.ACTIVE_TASKS, "P0-16 修复原子写入")

            # 保存
            await cm.save()

            # 验证文件存在且内容正确
            if not cm._memory_file.exists():
                issues.append("save() 后 MEMORY.md 不存在")
                return

            content = cm._memory_file.read_text(encoding="utf-8")
            if "用户喜欢深色主题" not in content:
                issues.append("save() 后 MEMORY.md 中找不到用户偏好条目")
            if "遇到 WebSocket 断连先检查心跳" not in content:
                issues.append("save() 后 MEMORY.md 中找不到业务经验条目")
            if "P0-16 修复原子写入" not in content:
                issues.append("save() 后 MEMORY.md 中找不到活跃任务条目")

            # 验证重新加载后内容一致
            cm2 = CoreMemory(base_dir=base_dir, scope="user")
            await cm2.load()
            prefs = await cm2.get_section(MemorySection.PREFERENCES)
            if "用户喜欢深色主题" not in prefs:
                issues.append(
                    f"重新加载后用户偏好丢失，实际: {prefs}"
                )

    asyncio.run(run())
    return issues


def check_core_memory_ensure_init_end_to_end() -> list[str]:
    """场景13：CoreMemory.ensure_initialized() 创建的文件内容正确。"""
    issues: list[str] = []
    from core.services.self_improvement.core_memory import CoreMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "memory"
        cm = CoreMemory(base_dir=base_dir, scope="user")
        cm.ensure_initialized()

        if not cm._memory_file.exists():
            issues.append("ensure_initialized() 后 MEMORY.md 不存在")
            return issues

        content = cm._memory_file.read_text(encoding="utf-8")
        # 应包含所有分区标题
        if "# MEMORY.md - 核心记忆" not in content:
            issues.append("ensure_initialized() 创建的文件缺少标题")
        if "用户偏好" not in content:
            issues.append("ensure_initialized() 创建的文件缺少用户偏好分区")
        if "业务经验" not in content:
            issues.append("ensure_initialized() 创建的文件缺少业务经验分区")

    return issues


def check_core_memory_concurrent_save() -> list[str]:
    """场景14：多个 CoreMemory 实例并发 save 不损坏文件。"""
    issues: list[str] = []
    from core.services.self_improvement.core_memory import (
        CoreMemory,
        MemorySection,
    )

    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "memory"
            # 用同一个 base_dir 创建多个实例
            cm1 = CoreMemory(base_dir=base_dir, scope="user")
            cm2 = CoreMemory(base_dir=base_dir, scope="user")
            cm1.ensure_initialized()

            await cm1.load()
            await cm2.load()

            await cm1.add_item(MemorySection.PREFERENCES, "cm1 的偏好")
            await cm2.add_item(MemorySection.PREFERENCES, "cm2 的偏好")

            # 并发保存
            await asyncio.gather(cm1.save(), cm2.save())

            # 验证文件可正常读取（未被损坏）
            try:
                content = cm1._memory_file.read_text(encoding="utf-8")
            except Exception as e:
                issues.append(f"并发保存后文件无法读取: {type(e).__name__}: {e}")
                return

            if "# MEMORY.md - 核心记忆" not in content:
                issues.append(
                    f"并发保存后文件内容损坏，缺少标题。内容片段: {content[:200]!r}"
                )

            # 验证能重新加载（JSON/文本格式完整）
            cm3 = CoreMemory(base_dir=base_dir, scope="user")
            try:
                await cm3.load()
            except Exception as e:
                issues.append(
                    f"并发保存后重新加载失败: {type(e).__name__}: {e}"
                )

    asyncio.run(run())
    return issues


def check_core_memory_save_no_truncation_on_failure() -> list[str]:
    """场景15：_save_sync 写入失败时原文件不被截断（原子性端到端）。

    模拟 safe_write_text 抛异常，验证 MEMORY.md 原内容不变。
    """
    issues: list[str] = []
    from core.services.self_improvement.core_memory import CoreMemory, MemorySection
    from core.utils import atomic_io

    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "memory"
            cm = CoreMemory(base_dir=base_dir, scope="user")
            cm.ensure_initialized()
            await cm.load()
            await cm.add_item(MemorySection.PREFERENCES, "原始偏好内容")

            # 记录原始文件内容
            original = cm._memory_file.read_text(encoding="utf-8")
            if "原始偏好内容" not in original:
                issues.append("前置条件失败：add_item 后文件中应有原始偏好")
                return

            # 模拟 safe_write_text 失败
            with patch.object(
                atomic_io,
                "safe_write_text",
                side_effect=OSError("模拟写入失败"),
            ):
                # _save_sync 内部 catch 了异常并记日志，不会抛出
                cm._save_sync()

            # 验证原文件内容不变（未被截断）
            after = cm._memory_file.read_text(encoding="utf-8")
            if after != original:
                issues.append(
                    f"safe_write_text 失败后 MEMORY.md 被修改了！\n"
                    f"  期望: {original!r}\n"
                    f"  实际: {after!r}"
                )
            if "原始偏好内容" not in after:
                issues.append(
                    f"safe_write_text 失败后原始偏好内容丢失，文件被截断: {after!r}"
                )

    asyncio.run(run())
    return issues


# ============================================================================
# 主入口
# ============================================================================

def main() -> int:
    print("=" * 70)
    print("P0-16 验证：core_memory.py 非原子写入 MEMORY.md")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        # atomic_io 新函数
        ("atomic_io 提供 safe_write_text", check_atomic_io_has_safe_write_text),
        ("atomic_io 提供 safe_read_text", check_atomic_io_has_safe_read_text),
        ("atomic_io 提供 async_safe_write_text", check_atomic_io_has_async_safe_write_text),
        ("atomic_io 提供 async_safe_read_text", check_atomic_io_has_async_safe_read_text),
        # core_memory 源码
        ("core_memory 从 atomic_io 导入 safe_write_text", check_core_memory_imports_safe_write_text),
        ("_save_sync 使用 safe_write_text", check_core_memory_save_uses_safe_write_text),
        ("ensure_initialized 使用 safe_write_text", check_core_memory_ensure_init_uses_safe_write_text),
        # safe_write_text 功能与原子性
        ("safe_write_text 正常写入", check_safe_write_text_basic),
        ("safe_write_text 原子性（失败时原文件不变）", check_safe_write_text_atomicity),
        ("safe_write_text 覆盖写入", check_safe_write_text_overwrite),
        ("async_safe_write_text 异步写入", check_async_safe_write_text),
        # CoreMemory 端到端
        ("CoreMemory.save() 端到端", check_core_memory_save_end_to_end),
        ("CoreMemory.ensure_initialized() 端到端", check_core_memory_ensure_init_end_to_end),
        ("CoreMemory 并发 save 不损坏", check_core_memory_concurrent_save),
        ("_save_sync 失败时不截断原文件", check_core_memory_save_no_truncation_on_failure),
    ]

    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            import traceback
            issues = [f"检查本身抛异常: {type(e).__name__}: {e}"]
            traceback.print_exc()

        if issues:
            for i in issues:
                print(f"  FAIL: {i}")
            all_issues.extend(issues)
        else:
            print("  PASS")

    print("\n" + "=" * 70)
    if all_issues:
        print(f"结果：失败（{len(all_issues)} 项问题）")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
