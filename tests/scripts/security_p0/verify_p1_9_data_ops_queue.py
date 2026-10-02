"""P1-9 data_ops/queue.py 任务重复执行修复 — 验证脚本

验证 DataOpsQueue 的并发安全与幂等性：
1. 同一 task_id 并发 run_task 时，handler 只执行一次（互斥）
2. 已 done/failed 的任务不会被重复 run_task 触发
3. 幂等键并发 enqueue 不会创建多个任务
4. handler 抛异常时 retries 正确递增，重试耗尽后置 failed
5. get_task 返回浅拷贝，不影响内部状态

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p1_9_data_ops_queue.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'-' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ──────────────────────────────────────────────────────────────
# 测试 1：并发 run_task 同一 task_id，handler 只执行一次
# ──────────────────────────────────────────────────────────────
def test_concurrent_run_only_once() -> list[str]:
    issues: list[str] = []
    _section("测试 1：并发 run_task 同一 task_id 时 handler 只执行一次")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    counter = {"value": 0}
    counter_lock = threading.Lock()

    def handler(payload):
        # 模拟耗时操作，放大 TOCTOU 窗口
        time.sleep(0.05)
        with counter_lock:
            counter["value"] += 1
        return {"ok": True}

    q.register_handler("test_once", handler)
    task = q.enqueue(task_type="test_once", payload={"x": 1})
    task_id = task.task_id

    # 10 个线程并发调用 run_task 同一 task_id
    threads = []
    results: list = []
    rlock = threading.Lock()

    def _runner():
        r = q.run_task(task_id)
        with rlock:
            results.append(r)

    for _ in range(10):
        t = threading.Thread(target=_runner)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    if counter["value"] != 1:
        issues.append(
            f"handler 被执行了 {counter['value']} 次（应只执行 1 次）"
        )

    # 验证所有线程都拿到了 done 状态
    done_count = sum(1 for r in results if r is not None and r.status == "done")
    if done_count != 10:
        issues.append(
            f"返回 done 状态的线程数 = {done_count}（应 10）"
        )

    if not issues:
        _ok("handler 只执行 1 次，10 个线程均拿到 done 状态")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 2：done 状态的任务不会被重新执行
# ──────────────────────────────────────────────────────────────
def test_done_not_re_executed() -> list[str]:
    issues: list[str] = []
    _section("测试 2：done 状态的任务不会被重新执行")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    counter = {"value": 0}
    clock = threading.Lock()

    def handler(payload):
        with clock:
            counter["value"] += 1
        return {"v": payload.get("v", 0)}

    q.register_handler("test_done", handler)
    task = q.enqueue(task_type="test_done", payload={"v": 1})

    # 第一次 run，应该执行
    r1 = q.run_task(task.task_id)
    if r1 is None or r1.status != "done":
        issues.append(f"第一次 run_task 未成功: {r1!r}")
    if counter["value"] != 1:
        issues.append(f"第一次 run 后 counter={counter['value']}（应=1）")

    # 第二次 run，应直接返回，不重新执行
    r2 = q.run_task(task.task_id)
    if r2 is None or r2.status != "done":
        issues.append(f"第二次 run_task 未返回 done: {r2!r}")
    if counter["value"] != 1:
        issues.append(
            f"第二次 run 后 counter={counter['value']}（应仍=1，"
            f"说明 done 任务被重新执行了）"
        )

    if not issues:
        _ok("done 状态任务被重复 run_task 时直接返回，未重新执行 handler")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 3：failed 状态的任务不会被重新执行
# ──────────────────────────────────────────────────────────────
def test_failed_not_re_executed() -> list[str]:
    issues: list[str] = []
    _section("测试 3：failed 状态的任务不会被重新执行")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    counter = {"value": 0}
    clock = threading.Lock()

    def handler(payload):
        with clock:
            counter["value"] += 1
        # 永远抛异常，max_retries=0 时第一次失败就置 failed
        raise RuntimeError("always fail")

    q.register_handler("test_failed", handler)
    # max_retries=0 → retries=1 > 0 → failed
    task = q.enqueue(task_type="test_failed", payload={}, max_retries=0)

    r1 = q.run_task(task.task_id)
    if r1 is None or r1.status != "failed":
        issues.append(f"第一次 run_task 未置 failed: {r1!r}")
    if counter["value"] != 1:
        issues.append(f"第一次 run 后 counter={counter['value']}（应=1）")

    r2 = q.run_task(task.task_id)
    if r2 is None or r2.status != "failed":
        issues.append(f"第二次 run_task 未保持 failed: {r2!r}")
    if counter["value"] != 1:
        issues.append(
            f"第二次 run 后 counter={counter['value']}（应仍=1，"
            f"说明 failed 任务被重新执行了）"
        )

    if not issues:
        _ok("failed 状态任务被重复 run_task 时直接返回，未重新执行 handler")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 4：max_retries>0 时失败后会回 queued，下次可重试
# ──────────────────────────────────────────────────────────────
def test_retry_until_max_retries() -> list[str]:
    issues: list[str] = []
    _section("测试 4：max_retries>0 时失败回 queued，重试耗尽后置 failed")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    counter = {"value": 0}
    clock = threading.Lock()

    def handler(payload):
        with clock:
            counter["value"] += 1
        raise RuntimeError("always fail")

    q.register_handler("test_retry", handler)
    # max_retries=2 → 允许重试 2 次（共执行 3 次：1 次初始 + 2 次重试）
    task = q.enqueue(task_type="test_retry", payload={}, max_retries=2)

    # 第 1 次执行：retries=1，1 <= 2，回 queued
    r1 = q.run_task(task.task_id)
    if r1.status != "queued":
        issues.append(f"第 1 次 run 后 status={r1.status}（应=queued）")
    if r1.retries != 1:
        issues.append(f"第 1 次 run 后 retries={r1.retries}（应=1）")

    # 第 2 次执行：retries=2，2 <= 2，回 queued
    r2 = q.run_task(task.task_id)
    if r2.status != "queued":
        issues.append(f"第 2 次 run 后 status={r2.status}（应=queued）")
    if r2.retries != 2:
        issues.append(f"第 2 次 run 后 retries={r2.retries}（应=2）")

    # 第 3 次执行：retries=3，3 > 2，置 failed
    r3 = q.run_task(task.task_id)
    if r3.status != "failed":
        issues.append(f"第 3 次 run 后 status={r3.status}（应=failed）")
    if r3.retries != 3:
        issues.append(f"第 3 次 run 后 retries={r3.retries}（应=3）")

    if counter["value"] != 3:
        issues.append(f"handler 共执行 {counter['value']} 次（应=3）")

    if not issues:
        _ok("max_retries=2 时正确执行 3 次后置 failed")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 5：幂等键并发 enqueue 不会创建多个任务
# ──────────────────────────────────────────────────────────────
def test_idempotency_concurrent_enqueue() -> list[str]:
    issues: list[str] = []
    _section("测试 5：幂等键并发 enqueue 不会创建多个任务")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    q.register_handler("test_idem", lambda p: {"ok": True})

    results: list = []
    rlock = threading.Lock()

    def _enq():
        t = q.enqueue(
            task_type="test_idem",
            payload={"ts": time.time()},
            idempotency_key="same_key",
        )
        with rlock:
            results.append(t.task_id)

    threads = [threading.Thread(target=_enq) for _ in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    unique_ids = set(results)
    if len(unique_ids) != 1:
        issues.append(
            f"并发 enqueue 返回 {len(unique_ids)} 个不同 task_id（应=1）: {unique_ids}"
        )

    if not issues:
        _ok(f"15 个并发 enqueue 全部返回同一 task_id={results[0]}")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 6：get_task 返回浅拷贝，外部修改不影响内部状态
# ──────────────────────────────────────────────────────────────
def test_get_task_returns_copy() -> list[str]:
    issues: list[str] = []
    _section("测试 6：get_task 返回浅拷贝，不影响内部状态")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    q.register_handler("test_copy", lambda p: {"ok": True})
    task = q.enqueue(task_type="test_copy", payload={"v": 1})
    q.run_task(task.task_id)

    # 取出快照并篡改
    snap = q.get_task(task.task_id)
    if snap is None:
        issues.append("get_task 返回 None")
        return issues
    snap.status = "tampered"
    snap.payload["v"] = 999
    snap.result["injected"] = True

    # 内部 task 应不受影响
    inner = q.get_task(task.task_id)
    if inner.status != "done":
        issues.append(f"内部 task.status 被污染: {inner.status}")
    if inner.payload.get("v") != 1:
        issues.append(f"内部 task.payload 被污染: {inner.payload}")
    if inner.result.get("injected"):
        issues.append(f"内部 task.result 被污染: {inner.result}")

    if not issues:
        _ok("get_task 返回的快照被篡改后，内部 task 状态不变")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 7：handler 不存在时直接置 failed
# ──────────────────────────────────────────────────────────────
def test_handler_not_found() -> list[str]:
    issues: list[str] = []
    _section("测试 7：handler 不存在时直接置 failed")

    from core.services.data_ops.queue import DataOpsQueue

    q = DataOpsQueue()
    task = q.enqueue(task_type="no_such_handler", payload={})
    r = q.run_task(task.task_id)
    if r is None or r.status != "failed":
        issues.append(f"未注册 handler 时 status={r.status if r else None}（应=failed）")
    if r and "handler_not_found" not in (r.error or ""):
        issues.append(f"未注册 handler 时 error={r.error!r}（应含 handler_not_found）")

    if not issues:
        _ok("未注册 handler 时直接置 failed 并写入 handler_not_found 错误")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────
def main() -> int:
    print("P1-9 data_ops/queue.py 任务重复执行修复验证")

    all_issues: list[str] = []
    for test in [
        test_concurrent_run_only_once,
        test_done_not_re_executed,
        test_failed_not_re_executed,
        test_retry_until_max_retries,
        test_idempotency_concurrent_enqueue,
        test_get_task_returns_copy,
        test_handler_not_found,
    ]:
        try:
            all_issues.extend(test())
        except Exception as e:
            _fail(f"{test.__name__} 异常: {e!r}")
            all_issues.append(f"{test.__name__} 异常: {e!r}")

    print("\n" + "=" * 60)
    if all_issues:
        print(f"FAILED: {len(all_issues)} 个问题")
        for it in all_issues:
            print(f"  - {it}")
        return 1
    print("PASSED: 全部测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
