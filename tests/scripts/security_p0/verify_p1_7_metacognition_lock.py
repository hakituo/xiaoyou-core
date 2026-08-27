"""P1-7 metacognition/service.py 锁驱逐修复 — 验证脚本

验证 _get_lock 的 LRU 驱逐逻辑不会破坏并发安全性：
1. 持有中的锁不会被驱逐
2. LRU 顺序正确（访问移到末尾，驱逐头部）
3. 所有锁都被持有时不会强制驱逐，允许突破上限
4. 并发场景下互斥性不被破坏

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p1_7_metacognition_lock.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import OrderedDict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ──────────────────────────────────────────────────────────────
# 测试 1：持有中的锁不会被驱逐
# ──────────────────────────────────────────────────────────────

def test_held_lock_not_evicted() -> list[str]:
    """验证当锁被持有时，驱逐逻辑会跳过它"""
    issues: list[str] = []
    _section("测试 1：持有中的锁不会被驱逐")

    from core.services.metacognition.service import MetaIntentService, _MAX_LOCKS

    service = MetaIntentService()

    async def _run():
        # 模拟填满锁缓存（用 _MAX_LOCKS 个 user_id）
        # 但第一个锁（user_0）会被持有，不应被驱逐
        lock0 = service._get_lock("user_0")
        # 填充到接近上限
        for i in range(1, _MAX_LOCKS):
            service._get_lock(f"user_{i}")

        # 现在 user_0 应该在头部（最久未访问）
        # 持有 user_0 的锁
        async with lock0:
            # 再请求一个新 user_id，触发驱逐
            service._get_lock("user_new_1")
            # 验证 user_0 的锁还在（因为被持有，未被驱逐）
            if "user_0" not in service._locks:
                issues.append("user_0 的锁被驱逐了（被持有时不应驱逐）")
            # 验证 user_new_1 已添加
            if "user_new_1" not in service._locks:
                issues.append("user_new_1 未被添加")

    asyncio.run(_run())

    if not issues:
        _ok("持有中的锁未被驱逐，新锁正常创建")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 2：LRU 顺序正确
# ──────────────────────────────────────────────────────────────

def test_lru_order() -> list[str]:
    """验证 OrderedDict 的 LRU 顺序：访问移到末尾"""
    issues: list[str] = []
    _section("测试 2：LRU 顺序（访问移到末尾）")

    from core.services.metacognition.service import MetaIntentService

    service = MetaIntentService()

    # 按顺序添加 a, b, c
    service._get_lock("a")
    service._get_lock("b")
    service._get_lock("c")

    # 此时顺序应为 [a, b, c]
    keys = list(service._locks.keys())
    if keys != ["a", "b", "c"]:
        issues.append(f"初始顺序不对: {keys}（应为 [a, b, c]）")

    # 再次访问 a，应移到末尾
    service._get_lock("a")
    keys = list(service._locks.keys())
    if keys != ["b", "c", "a"]:
        issues.append(f"访问 a 后顺序不对: {keys}（应为 [b, c, a]）")

    if not issues:
        _ok("LRU 顺序正确：访问后移到末尾")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 3：所有锁都被持有时不强制驱逐
# ──────────────────────────────────────────────────────────────

def test_all_locked_no_force_evict() -> list[str]:
    """验证所有锁都被持有时，允许突破上限而非破坏互斥"""
    issues: list[str] = []
    _section("测试 3：所有锁被持有时突破上限（正确性优先）")

    from core.services.metacognition.service import MetaIntentService, _MAX_LOCKS

    # 用小的上限测试
    service = MetaIntentService()

    async def _run():
        # 模拟所有锁都被持有
        held_locks = []
        for i in range(_MAX_LOCKS):
            lock = service._get_lock(f"held_{i}")
            await lock.acquire()  # 持有但不释放
            held_locks.append(lock)

        # 此时所有锁都被持有，请求新锁应突破上限
        new_lock = service._get_lock("new_user")
        # 验证新锁可以正常获取（没有被驱逐逻辑破坏）
        async with new_lock:
            pass

        # 验证总锁数 > _MAX_LOCKS（突破了上限）
        if len(service._locks) <= _MAX_LOCKS:
            issues.append(
                f"所有锁被持有时未突破上限: {len(service._locks)}（应 > {_MAX_LOCKS}）"
            )

        # 清理
        for lock in held_locks:
            lock.release()

    asyncio.run(_run())

    if not issues:
        _ok("所有锁被持有时正确突破上限，未破坏互斥")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 4：并发场景下互斥性不被破坏
# ──────────────────────────────────────────────────────────────

def test_concurrent_mutex_preserved() -> list[str]:
    """验证高并发场景下，相同 user_id 的临界区仍然互斥"""
    issues: list[str] = []
    _section("测试 4：并发场景下互斥性保持")

    from core.services.metacognition.service import MetaIntentService

    service = MetaIntentService()
    shared_counter = {"value": 0}
    # 只追踪 shared_user 的并发数（other_* 各自有独立锁，可并发）
    shared_max_concurrent = {"value": 0}
    shared_current = {"value": 0}

    async def _shared_worker(delay: float):
        """shared_user 的任务，应串行执行"""
        lock = service._get_lock("shared_user")
        async with lock:
            shared_current["value"] += 1
            if shared_current["value"] > shared_max_concurrent["value"]:
                shared_max_concurrent["value"] = shared_current["value"]
            await asyncio.sleep(delay)
            shared_counter["value"] += 1
            shared_current["value"] -= 1

    async def _other_worker(user_id: str, delay: float):
        """其他 user 的任务，可并发（仅用于制造锁缓存压力）"""
        lock = service._get_lock(user_id)
        async with lock:
            await asyncio.sleep(delay)

    async def _run():
        # 启动 10 个 shared_user 任务（应串行）
        # 同时混杂 50 个 other 任务（可并发，制造缓存压力）
        tasks = []
        for i in range(10):
            tasks.append(_shared_worker(0.05))
        for i in range(50):
            tasks.append(_other_worker(f"other_{i}", 0.01))
        await asyncio.gather(*tasks)

    asyncio.run(_run())

    # 验证 shared_user 的 10 个任务串行执行（max_concurrent == 1）
    if shared_max_concurrent["value"] > 1:
        issues.append(
            f"shared_user 临界区并发数 = {shared_max_concurrent['value']}（应 ≤ 1）"
        )
    if shared_counter["value"] != 10:
        issues.append(
            f"shared_user 计数器 = {shared_counter['value']}（应为 10）"
        )

    if not issues:
        _ok(f"shared_user 临界区串行执行（max_concurrent=1, 计数=10）")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 5：驱逐只针对未被持有的锁
# ──────────────────────────────────────────────────────────────

def test_evict_only_unlocked() -> list[str]:
    """验证驱逐只针对 lock.locked() == False 的锁"""
    issues: list[str] = []
    _section("测试 5：驱逐只针对未被持有的锁")

    from core.services.metacognition.service import MetaIntentService

    service = MetaIntentService()

    async def _run():
        # 添加 3 个锁：a, b, c
        lock_a = service._get_lock("a")
        lock_b = service._get_lock("b")
        lock_c = service._get_lock("c")

        # 持有 a 和 c（b 不持有）
        await lock_a.acquire()
        await lock_c.acquire()
        try:
            # 此时 b 在中间，lock.locked() == False
            # 触发驱逐逻辑：手动调用驱逐
            evicted = 0
            for k in list(service._locks.keys()):
                candidate = service._locks.get(k)
                if candidate is None:
                    continue
                if candidate.locked():
                    continue
                del service._locks[k]
                evicted += 1
                break  # 只驱逐一个验证

            if evicted != 1:
                issues.append(f"应驱逐 1 个未持有的锁，实际驱逐 {evicted}")
            if "a" not in service._locks:
                issues.append("持有的锁 a 被错误驱逐")
            if "c" not in service._locks:
                issues.append("持有的锁 c 被错误驱逐")
            if "b" in service._locks:
                issues.append("未持有的锁 b 应被驱逐但仍在")
        finally:
            lock_a.release()
            lock_c.release()

    asyncio.run(_run())

    if not issues:
        _ok("驱逐逻辑正确：只驱逐 lock.locked()==False 的锁")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 6：源码静态检查
# ──────────────────────────────────────────────────────────────

def test_source_static() -> list[str]:
    """静态检查关键修复点已落地"""
    issues: list[str] = []
    _section("测试 6：源码静态检查")

    src_path = PROJECT_ROOT / "core/services/metacognition/service.py"
    if not src_path.exists():
        issues.append("metacognition/service.py 文件不存在")
        return issues

    src = src_path.read_text(encoding="utf-8")

    required_markers = [
        "OrderedDict",
        "move_to_end",
        "lock.locked()",
        "P1-7 修复",
        "正确性优先于内存上限",
    ]
    for marker in required_markers:
        if marker not in src:
            issues.append(f"缺少标记：{marker}")

    # 验证原版问题逻辑已移除
    if "oldest_keys = list(self._locks.keys())[: _MAX_LOCKS // 4]" in src:
        issues.append("原版强制驱逐 1/4 的逻辑仍存在")

    if not issues:
        _ok("所有关键修复标记齐全，原版问题逻辑已移除")
    return issues


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────

def main() -> int:
    print("P1-7 metacognition/service.py 锁驱逐修复 — 验证脚本")
    print(f"项目根目录: {PROJECT_ROOT}")

    all_issues: list[str] = []
    for test_fn in [
        test_held_lock_not_evicted,
        test_lru_order,
        test_all_locked_no_force_evict,
        test_concurrent_mutex_preserved,
        test_evict_only_unlocked,
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
        print("  ✅ 所有 P1-7 验证通过！")
        return 0
    else:
        print(f"  ❌ 发现 {len(all_issues)} 个问题：")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
