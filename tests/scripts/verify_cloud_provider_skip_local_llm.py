"""验证：provider 为云端时跳过 LocalLLMAdapter 创建。

优化点：
    provider != "local" 时，不向 HybridLLMModule 传入 lazy_local_factory，
    避免 LocalLLMAdapter() 构造触发 torch/llama_cpp 等重模块冷导入（~30s）。

验证内容：
    1. factory.py 源码逻辑：provider != "local" 时 _lazy_factory 为 None
    2. HybridLLMModule 在 lazy_local_factory=None 时 initialize() 不会尝试创建本地模块
    3. HybridLLMModule 在 lazy_local_factory=None 时 chat() 正常路由到云端
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_factory_source_logic() -> None:
    """验证 factory.py 中 provider != 'local' 时不传 lazy_local_factory。"""
    factory_path = _PROJECT_ROOT / "core" / "llm" / "factory.py"
    source = factory_path.read_text(encoding="utf-8")

    # 确认关键逻辑存在
    assert "needs_local_adapter = (provider == \"local\")" in source, (
        "factory.py 缺少 needs_local_adapter 判断"
    )
    assert "_lazy_factory = (" in source, "factory.py 缺少 _lazy_factory 变量"
    assert "lazy_local_factory=_lazy_factory" in source, (
        "factory.py 未将 _lazy_factory 传给 HybridLLMModule"
    )

    # 确认旧的无条件传参已被移除
    old_pattern = "lazy_local_factory=_lazy_local_adapter_factory if local_adapter is None else None"
    assert old_pattern not in source, (
        "factory.py 仍保留旧的无条件传参逻辑，优化未生效"
    )

    print("[PASS] factory.py 源码逻辑验证通过")


def test_hybrid_module_no_lazy_factory() -> None:
    """验证 HybridLLMModule 在 lazy_local_factory=None 时不会创建本地模块。"""
    from core.llm.hybrid_module import HybridLLMModule

    # 模拟 provider=deepseek 的场景：不传 lazy_local_factory
    hybrid = HybridLLMModule(
        local_module=None,
        cloud_module=None,
        preload_local=False,
        default_provider="deepseek",
        lazy_local_factory=None,
    )

    assert hybrid._lazy_local_factory is None, (
        "_lazy_local_factory 应为 None，但实际有值"
    )
    assert hybrid.local_module is None, "local_module 应为 None"
    assert hybrid._local_initialized is False, "_local_initialized 应为 False"

    # 验证 initialize() 不会尝试创建本地模块
    async def _run_init() -> None:
        await hybrid.initialize()

    asyncio.run(_run_init())

    # initialize 后 local_module 仍然应该是 None
    assert hybrid.local_module is None, (
        "initialize() 后 local_module 不应为 None 之外的值"
    )

    print("[PASS] HybridLLMModule 在无 lazy_local_factory 时不创建本地模块")


def test_hybrid_module_cloud_routing() -> None:
    """验证 HybridLLMModule 在无本地模块时 chat() 路由到云端。"""

    class FakeCloudModule:
        def __init__(self) -> None:
            self.called = False

        async def chat(self, messages: list, **kwargs) -> dict:
            self.called = True
            return {"response": "fake cloud response"}

        async def stream_chat(self, messages: list, **kwargs):
            self.called = True
            yield {"response": "fake cloud stream"}

    from core.llm.hybrid_module import HybridLLMModule

    fake_cloud = FakeCloudModule()
    hybrid = HybridLLMModule(
        local_module=None,
        cloud_module=fake_cloud,
        preload_local=False,
        default_provider="deepseek",
        lazy_local_factory=None,
    )

    # chat() 应该路由到云端
    async def _run_chat() -> None:
        result = await hybrid.chat([{"role": "user", "content": "hi"}])
        assert fake_cloud.called, "cloud_module.chat 未被调用"
        assert isinstance(result, dict), "返回值应为 dict"
        assert result.get("response") == "fake cloud response", (
            f"返回值不符合预期: {result}"
        )

    asyncio.run(_run_chat())

    print("[PASS] HybridLLMModule 在无本地模块时 chat() 正常路由到云端")


def test_hybrid_module_local_provider_keeps_factory() -> None:
    """验证 provider=local 时仍然保留 lazy_local_factory（不影响本地模式）。"""

    def fake_local_factory():
        return None

    from core.llm.hybrid_module import HybridLLMModule

    hybrid = HybridLLMModule(
        local_module=None,
        cloud_module=None,
        preload_local=True,
        default_provider="local",
        lazy_local_factory=fake_local_factory,
    )

    assert hybrid._lazy_local_factory is fake_local_factory, (
        "provider=local 时 _lazy_local_factory 应为传入的工厂函数"
    )

    print("[PASS] provider=local 时仍保留 lazy_local_factory")


def main() -> int:
    tests = [
        test_factory_source_logic,
        test_hybrid_module_no_lazy_factory,
        test_hybrid_module_cloud_routing,
        test_hybrid_module_local_provider_keeps_factory,
    ]

    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__}: {exc}")
            print(f"[FAIL] {test.__name__}: {exc}")

    print()
    if failures:
        print(f"失败 {len(failures)}/{len(tests)} 项验证")
        return 1

    print(f"全部 {len(tests)} 项验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
