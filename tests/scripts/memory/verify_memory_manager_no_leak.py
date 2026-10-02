"""验证 WeightedMemoryManager 不再被逐轮对话重复创建（9GB 内存泄漏根因）

问题回顾
--------
每轮对话里 `_resolve_persona_prompt` → `agent._get_dynamic_system_prompt` →
`build_persona_prompt` 这条链没有透传 `memory_manager`，导致
`get_context_injection` 走进 `else` 分支，直接 `WeightedMemoryManager(uid)`：
  * 新建一个实例 = 重新装载 4000+ 条记忆 + 新建 C++ VectorIndexer（约百 MB 级）
  * 构造函数会启动常驻自动保存线程，线程闭包持有 `self`，
    实例永远无法被 GC —— 每轮对话泄漏一份，RSS 从 3.7GB 涨到 9GB+
  * 兜底的 `cleanup_idle_weighted_memory_managers` / `shutdown_all_...`
    此前没有任何调用点（死代码），watchdog 只记录不回收，所以问题被掩盖

修复内容
--------
1. `context_gathering.py` 改为走工厂 `get_weighted_memory_manager(..., ensure_loaded=False)`
2. `build_persona_prompt` / `_get_dynamic_system_prompt` / `resolve_persona_prompt`
   全链路透传 `memory_manager`
3. `lifespan.py` 退出时调用 `shutdown_all_weighted_memory_managers()`

运行：
    venv_cpu\\Scripts\\python.exe tests/scripts/memory/verify_memory_manager_no_leak.py
"""
from __future__ import annotations

import inspect
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.persona_system.prompt import (  # noqa: E402
    context_gathering,
    data,
)
from core.agents.chat_agent_components.persona_system.prompt.assembler import (  # noqa: E402
    build_persona_prompt,
    build_persona_prompt_split,
)
from memory.weighted_memory_manager import WeightedMemoryManager  # noqa: E402


def _read_source(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _auto_save_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name.startswith("auto-save-"))


# ---------------------------------------------------------------------------
# 1. 静态检查：泄漏点必须消失
# ---------------------------------------------------------------------------

def check_no_direct_construction() -> None:
    """context_gathering 不得再直接 new WeightedMemoryManager（唯一泄漏点）"""
    src = _read_source(
        "core/agents/chat_agent_components/persona_system/prompt/context_gathering.py"
    )
    body = src.split("def get_context_injection", 1)[-1]
    assert "WeightedMemoryManager(" not in body, (
        "context_gathering.get_context_injection 仍在直接构造 WeightedMemoryManager，"
        "必须改用 get_weighted_memory_manager 工厂取共享单例"
    )
    assert "get_weighted_memory_manager(" in body, (
        "context_gathering 未使用 get_weighted_memory_manager 工厂"
    )


def check_memory_manager_forwarded() -> None:
    """persona prompt 构建链必须把 memory_manager 一路传下去"""
    src = _read_source("core/agents/chat_agent_components/context_persona.py")
    block = src.split("agent._get_dynamic_system_prompt,", 1)[-1].split(")", 1)[0]
    assert "memory_manager=memory_manager" in block, (
        "resolve_persona_prompt 调用 _get_dynamic_system_prompt 时未透传 memory_manager"
    )

    lifespan_src = _read_source("core/lifecycle/lifespan.py")
    assert "shutdown_all_weighted_memory_managers()" in lifespan_src, (
        "lifespan 退出流程未调用 shutdown_all_weighted_memory_managers()，"
        "常驻自动保存线程不会停止"
    )


def check_signature_chain() -> None:
    """透传链路上的每个函数都必须接受 memory_manager"""
    from core.agents.chat_agent import ChatAgent

    targets = [
        ("build_persona_prompt", build_persona_prompt),
        ("build_persona_prompt_split", build_persona_prompt_split),
        ("get_prompt_data", data.get_prompt_data),
        ("ChatAgent._get_dynamic_system_prompt", ChatAgent._get_dynamic_system_prompt),
        ("get_context_injection", context_gathering.get_context_injection),
    ]
    for name, func in targets:
        params = inspect.signature(func).parameters
        assert "memory_manager" in params, f"{name} 缺少 memory_manager 参数"


def check_factory_ensure_loaded_param() -> None:
    """工厂需要支持 ensure_loaded=False，避免同步路径阻塞事件循环"""
    from memory.weighted_memory_manager import get_weighted_memory_manager

    params = inspect.signature(get_weighted_memory_manager).parameters
    assert "ensure_loaded" in params, "get_weighted_memory_manager 缺少 ensure_loaded 参数"
    assert params["ensure_loaded"].default is True, "ensure_loaded 默认值应为 True"


# ---------------------------------------------------------------------------
# 2. 运行时检查：memory_manager 缺失时不再新建实例 / 线程
# ---------------------------------------------------------------------------

def check_no_instance_created_when_missing() -> None:
    """memory_manager 为 None 时，必须复用工厂单例，不得新建实例和线程

    用一个桩替换工厂：如果代码回退到直接构造，桩不会被调用，
    同时会新增真实实例（表现为 auto-save 线程数增长）。
    """
    calls: list[str] = []

    class _StubLock:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    stub = SimpleNamespace(lock=_StubLock(), short_term_memory=[])

    def _stub_factory(user_id: str, ensure_loaded: bool = True):
        calls.append(user_id)
        return stub

    original = context_gathering.get_weighted_memory_manager
    threads_before = _auto_save_threads()
    context_gathering.get_weighted_memory_manager = _stub_factory
    try:
        for _ in range(3):
            # memory_manager 缺省，模拟修复前的泄漏路径
            context_gathering.get_context_injection("verify_no_leak_scope")
    finally:
        context_gathering.get_weighted_memory_manager = original

    threads_after = _auto_save_threads()

    assert calls, "get_context_injection 未调用记忆管理器工厂（桩未被触发）"
    assert threads_after == threads_before, (
        f"get_context_injection 仍然新建了记忆管理器实例："
        f"auto-save 线程 {threads_before} -> {threads_after}"
    )


def check_reuses_passed_manager() -> None:
    """传入 memory_manager 时应直接复用，不触碰工厂"""

    class _StubLock:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    # 必须是真正的 WeightedMemoryManager 子类实例，否则会走进 else 分支
    mm = WeightedMemoryManager.__new__(WeightedMemoryManager)
    mm.lock = _StubLock()
    mm.short_term_memory = [{"timestamp": 1.0}]

    def _boom_factory(*_args, **_kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("传入 memory_manager 时不应再走工厂")

    original = context_gathering.get_weighted_memory_manager
    context_gathering.get_weighted_memory_manager = _boom_factory
    try:
        ctx = context_gathering.get_context_injection(
            "verify_no_leak_scope", memory_manager=mm
        )
    finally:
        context_gathering.get_weighted_memory_manager = original

    assert ctx.get("last_conversation_seconds") is not None, (
        "传入 memory_manager 时未取到最后对话时间"
    )


# ---------------------------------------------------------------------------

def main() -> int:
    checks = [
        ("静态：不再直接构造 WeightedMemoryManager", check_no_direct_construction),
        ("静态：memory_manager 全链路透传", check_memory_manager_forwarded),
        ("静态：透传链签名完整", check_signature_chain),
        ("静态：工厂支持 ensure_loaded", check_factory_ensure_loaded_param),
        ("运行：memory_manager 缺失时不新建实例", check_no_instance_created_when_missing),
        ("运行：传入 memory_manager 时直接复用", check_reuses_passed_manager),
    ]

    failed = 0
    for name, func in checks:
        try:
            func()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[ERROR] {name}: {type(e).__name__}: {e}")
        else:
            print(f"[PASS] {name}")

    print("-" * 60)
    if failed:
        print(f"结果：{len(checks) - failed} 通过 / {failed} 失败")
        return 1
    print(f"结果：全部 {len(checks)} 项通过 —— 逐轮对话不再新建记忆管理器实例")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
