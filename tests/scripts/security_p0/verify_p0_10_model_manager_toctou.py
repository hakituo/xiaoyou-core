"""P0-10 验证脚本：model_manager.load_model TOCTOU 竞态修复

验证目标：
1. load_model 在并发场景下，同一模型只会被真正加载一次（_load_model_by_type 只调用一次）
2. 第二个并发请求会通过双重检查命中已加载状态，复用第一个线程的加载结果
3. 不同模型的并发加载互不阻塞（_model_locks 是 per-model 的）

修复要点：
- 引入 _get_model_lock(name) 返回每个模型独立的 threading.Lock
- 在全局锁内取模型锁，释放全局锁后进入模型锁
- 模型锁内再次检查 is_loaded（双重检查锁定），命中则直接复用
- 真正的 _load_model_by_type 在模型锁内执行，避免并发重复加载
"""
import asyncio
import os
import sys
import threading
import time
from unittest.mock import patch

# 加入项目根目录
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _make_model_manager_with_fake_loader():
    """构造一个 ModelManager，把 _load_model_by_type 替换为带计数的可等待版本。

    返回 (manager, call_counter, model_name)
    """
    from core.core_engine.model_manager import ModelManager, ModelInfo

    # 重置单例，确保用例之间隔离
    ModelManager._instance = None
    ModelManager._initialized = False

    manager = ModelManager()
    model_name = "test_toctou_model"

    # 直接注册一个虚拟模型
    with manager._global_lock:
        manager._models[model_name] = ModelInfo(
            model_name=model_name, model_type="llm", model_path="/fake/path"
        )

    call_counter = {"count": 0, "lock": threading.Lock()}

    def fake_load(name, **kwargs):
        # 模拟加载耗时，让并发窗口更明显
        time.sleep(0.3)
        with call_counter["lock"]:
            call_counter["count"] += 1
        # 返回 (model_obj, tokenizer_obj)
        return ({"loaded_by_thread": threading.get_ident()}, {"tokenizer": True})

    manager._load_model_by_type = fake_load
    return manager, call_counter, model_name


def check_concurrent_load_only_once() -> list[str]:
    """场景1：多线程并发调用 load_model，_load_model_by_type 应只被调用一次。"""
    issues: list[str] = []
    manager, counter, model_name = _make_model_manager_with_fake_loader()

    barrier = threading.Barrier(5)
    results: list = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            # load_model 只返回 model 对象，不含 tokenizer
            model = manager.load_model(model_name)
            with results_lock:
                results.append((model, threading.get_ident()))
        except Exception as e:
            with results_lock:
                results.append(("error", str(e), threading.get_ident()))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    if counter["count"] != 1:
        issues.append(
            f"并发加载被调用 {counter['count']} 次，期望仅 1 次（TOCTOU 竞态未被消除）"
        )

    if len(results) != 5:
        issues.append(f"仅有 {len(results)} 个线程完成，期望 5 个")

    # 所有线程应拿到同一个 model_obj（同一个 dict 引用）
    model_objs = [r[0] for r in results if isinstance(r[0], dict)]
    if len(model_objs) == 5:
        first_id = id(model_objs[0])
        if any(id(m) != first_id for m in model_objs[1:]):
            issues.append("并发加载返回了不同的 model_obj，期望共享同一实例")
    else:
        issues.append(
            f"部分线程未返回有效 model_obj（成功 {len(model_objs)}/5）"
        )

    return issues


def check_sequential_reload_uses_cache() -> list[str]:
    """场景2：模型已加载后再次调用 load_model，不应再次触发 _load_model_by_type。"""
    issues: list[str] = []
    manager, counter, model_name = _make_model_manager_with_fake_loader()

    # 第一次加载
    try:
        manager.load_model(model_name)
    except Exception as e:
        issues.append(f"第一次加载失败: {e}")
        return issues

    if counter["count"] != 1:
        issues.append(f"第一次加载后 _load_model_by_type 应被调用 1 次，实际 {counter['count']}")
        return issues

    # 第二次加载：应命中缓存，不再调用 _load_model_by_type
    try:
        manager.load_model(model_name)
    except Exception as e:
        issues.append(f"第二次加载失败: {e}")
        return issues

    if counter["count"] != 1:
        issues.append(
            f"第二次加载后 _load_model_by_type 应仍为 1 次（命中缓存），实际 {counter['count']}"
        )

    return issues


def check_different_models_dont_share_lock() -> list[str]:
    """场景3：不同模型应使用不同的 _model_locks，互不阻塞。"""
    issues: list[str] = []
    manager, _, _ = _make_model_manager_with_fake_loader()

    lock_a = manager._get_model_lock("model_a")
    lock_b = manager._get_model_lock("model_b")

    if lock_a is lock_b:
        issues.append("不同模型返回了同一个 Lock 对象，per-model 锁未生效")

    # 同一模型多次获取应为同一对象
    lock_a2 = manager._get_model_lock("model_a")
    if lock_a is not lock_a2:
        issues.append("同一模型多次获取 _model_locks 返回了不同 Lock 对象")

    return issues


def check_per_model_lock_serializes_loads() -> list[str]:
    """场景4：持有 model_lock 时，另一个并发 load_model 会等待第一个完成。"""
    issues: list[str] = []
    manager, counter, model_name = _make_model_manager_with_fake_loader()

    # 先取出该模型的锁并持有，模拟另一个线程正在加载
    with manager._global_lock:
        blocked_lock = manager._get_model_lock(model_name)

    held_event = threading.Event()
    release_event = threading.Event()

    def hold_lock():
        with blocked_lock:
            held_event.set()
            release_event.wait(timeout=5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    if not held_event.wait(timeout=2):
        issues.append("无法持有 model_lock，验证场景失败")
        return issues

    # 此时 model_lock 被占用，调用 load_model 应被阻塞
    completed = {"done": False}

    def caller():
        try:
            manager.load_model(model_name)
        finally:
            completed["done"] = True

    t = threading.Thread(target=caller)
    t.start()
    time.sleep(0.3)
    if completed["done"]:
        issues.append("load_model 在 model_lock 被占用时未阻塞，双重检查锁定可能无效")

    # 释放锁
    release_event.set()
    holder.join(timeout=5)
    t.join(timeout=5)

    if not completed["done"]:
        issues.append("释放 model_lock 后 load_model 未完成")

    return issues


def check_load_failure_does_not_corrupt_state() -> list[str]:
    """场景5：_load_model_by_type 抛异常时，状态应保持可重试。"""
    issues: list[str] = []
    from core.core_engine.model_manager import ModelManager, ModelInfo

    ModelManager._instance = None
    ModelManager._initialized = False
    manager = ModelManager()
    model_name = "test_failure_model"

    with manager._global_lock:
        manager._models[model_name] = ModelInfo(
            model_name=model_name, model_type="llm", model_path="/fake/path"
        )

    call_count = {"n": 0}

    def failing_then_success(name, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("模拟加载失败")
        return ({"retry_ok": True}, {"tokenizer": True})

    manager._load_model_by_type = failing_then_success

    # 第一次应失败
    try:
        manager.load_model(model_name)
        issues.append("第一次加载应抛异常但未抛出")
    except RuntimeError:
        pass

    # 第二次应成功
    try:
        model = manager.load_model(model_name)
        if not isinstance(model, dict) or not model.get("retry_ok"):
            issues.append("重试加载返回了意外的 model_obj")
    except Exception as e:
        issues.append(f"重试加载失败: {e}")

    return issues


def main() -> int:
    print("=" * 70)
    print("P0-10 验证：model_manager.load_model TOCTOU 竞态修复")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        ("并发加载只调用一次 _load_model_by_type", check_concurrent_load_only_once),
        ("已加载模型命中缓存不重复加载", check_sequential_reload_uses_cache),
        ("不同模型使用独立的 per-model 锁", check_different_models_dont_share_lock),
        ("per-model 锁串行化同模型并发加载", check_per_model_lock_serializes_loads),
        ("加载失败后状态可重试", check_load_failure_does_not_corrupt_state),
    ]

    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            issues = [f"检查本身抛异常: {type(e).__name__}: {e}"]

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
