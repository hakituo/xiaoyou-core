"""P0-13 验证脚本：hybrid_module.py 初始化标志设置时机

验证目标：
1. 非预加载路径下，local_module 创建后必须调用 initialize()
2. 预加载路径下，工厂失败时 _local_initialized 应被重置，允许下次重试
3. 预加载路径下，工厂返回 None 时 _local_initialized 应被重置
4. 预加载路径下，工厂成功后 local_module 才被赋值
5. 工厂成功但 initialize() 失败时，local_module 仍被保留（不再重置）

修复要点：
- 非预加载路径补充 local_module.initialize() 调用
- 工厂失败/返回 None 时重置 _local_initialized = False
- 工厂成功后先赋值 self.local_module，再调用 initialize
- initialize() 失败不重置标志（保留 local_module 引用，避免反复重试一个会失败的 init）
"""
import asyncio
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class _FakeLocalModule:
    """模拟本地 LLM 模块。"""

    def __init__(self, init_should_fail: bool = False):
        self.initialized = False
        self.init_should_fail = init_should_fail
        self.init_call_count = 0

    async def initialize(self):
        self.init_call_count += 1
        if self.init_should_fail:
            raise RuntimeError("模拟 initialize 失败")
        self.initialized = True

    def get_status(self):
        return {"init_state": "INITIALIZED" if self.initialized else "NOT_INITIALIZED"}


class _FakeCloudModule:
    """模拟云端 LLM 模块。"""

    def __init__(self):
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    def get_status(self):
        return {"init_state": "INITIALIZED" if self.initialized else "NOT_INITIALIZED"}


def check_non_preload_path_initializes_local() -> list[str]:
    """场景1：非预加载路径下，local_module 创建后必须调用 initialize()。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    fake_local = _FakeLocalModule()
    cloud = _FakeCloudModule()

    def factory():
        return fake_local

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=False,  # 走非预加载路径
        default_provider="local",
        lazy_local_factory=factory,
    )

    asyncio.run(module.initialize())

    if module.local_module is not fake_local:
        issues.append("非预加载路径未正确赋值 local_module")
        return issues

    if fake_local.init_call_count != 1:
        issues.append(
            f"非预加载路径应调用 local_module.initialize() 1 次，实际 {fake_local.init_call_count}"
        )

    if not fake_local.initialized:
        issues.append("非预加载路径执行后 local_module.initialized 应为 True")

    if not module._local_initialized:
        issues.append("非预加载路径执行后 _local_initialized 应为 True")

    return issues


def check_preload_factory_failure_resets_flag() -> list[str]:
    """场景2：预加载路径下，工厂抛异常时 _local_initialized 应被重置，允许重试。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    cloud = _FakeCloudModule()
    factory_call_count = {"n": 0}

    def failing_factory():
        factory_call_count["n"] += 1
        raise RuntimeError("模拟工厂失败")

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=True,
        default_provider="local",
        lazy_local_factory=failing_factory,
    )

    async def run():
        await module.initialize()
        # 等待后台任务完成
        task = getattr(module, "_local_init_task", None)
        if task:
            await task

    asyncio.run(run())

    if module._local_initialized is not False:
        issues.append(
            f"工厂失败后 _local_initialized 应被重置为 False，实际 {module._local_initialized}"
        )

    if module.local_module is not None:
        issues.append("工厂失败后 local_module 应保持 None")

    # 第二次 initialize 应能再次调用工厂（标志已重置）
    asyncio.run(run())
    if factory_call_count["n"] != 2:
        issues.append(
            f"工厂失败后第二次 initialize 应重试工厂，期望调用 2 次，实际 {factory_call_count['n']}"
        )

    return issues


def check_preload_factory_returns_none_resets_flag() -> list[str]:
    """场景3：预加载路径下，工厂返回 None 时 _local_initialized 应被重置。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    cloud = _FakeCloudModule()

    def none_factory():
        return None

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=True,
        default_provider="local",
        lazy_local_factory=none_factory,
    )

    async def run():
        await module.initialize()
        task = getattr(module, "_local_init_task", None)
        if task:
            await task

    asyncio.run(run())

    if module._local_initialized is not False:
        issues.append(
            f"工厂返回 None 后 _local_initialized 应被重置为 False，实际 {module._local_initialized}"
        )

    if module.local_module is not None:
        issues.append("工厂返回 None 后 local_module 应保持 None")

    return issues


def check_preload_factory_success_assigns_local_then_inits() -> list[str]:
    """场景4：预加载路径下，工厂成功后 local_module 被赋值且 initialize 被调用。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    cloud = _FakeCloudModule()
    fake_local = _FakeLocalModule()

    def factory():
        return fake_local

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=True,
        default_provider="local",
        lazy_local_factory=factory,
    )

    async def run():
        await module.initialize()
        task = getattr(module, "_local_init_task", None)
        if task:
            await task

    asyncio.run(run())

    if module.local_module is not fake_local:
        issues.append("工厂成功后 local_module 应被赋值为 fake_local")
        return issues

    if fake_local.init_call_count != 1:
        issues.append(
            f"工厂成功后应调用 local_module.initialize() 1 次，实际 {fake_local.init_call_count}"
        )

    if not fake_local.initialized:
        issues.append("工厂成功后 local_module.initialized 应为 True")

    if not module._local_initialized:
        issues.append("工厂成功后 _local_initialized 应保持 True")

    return issues


def check_preload_init_failure_keeps_local_module() -> list[str]:
    """场景5：工厂成功但 initialize() 失败时，local_module 应被保留。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    cloud = _FakeCloudModule()
    fake_local = _FakeLocalModule(init_should_fail=True)

    def factory():
        return fake_local

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=True,
        default_provider="local",
        lazy_local_factory=factory,
    )

    async def run():
        await module.initialize()
        task = getattr(module, "_local_init_task", None)
        if task:
            await task

    asyncio.run(run())

    # local_module 应被保留（不再重试 factory）
    if module.local_module is not fake_local:
        issues.append("initialize() 失败后 local_module 应被保留")
        return issues

    # _local_initialized 应保持 True（不重试 factory）
    if module._local_initialized is not True:
        issues.append(
            f"initialize() 失败后 _local_initialized 应保持 True，实际 {module._local_initialized}"
        )

    if fake_local.init_call_count != 1:
        issues.append(
            f"initialize() 应被调用 1 次，实际 {fake_local.init_call_count}"
        )

    return issues


def check_cloud_always_initialized() -> list[str]:
    """场景6：无论本地路径如何，cloud_module 都应被初始化。"""
    issues: list[str] = []
    from core.llm.hybrid_module import HybridLLMModule

    cloud = _FakeCloudModule()

    module = HybridLLMModule(
        local_module=None,
        cloud_module=cloud,
        preload_local=False,
        default_provider="cloud",
        lazy_local_factory=None,
    )

    asyncio.run(module.initialize())

    if not cloud.initialized:
        issues.append("cloud_module 应被初始化")

    return issues


def main() -> int:
    print("=" * 70)
    print("P0-13 验证：hybrid_module.py 初始化标志设置时机")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        ("非预加载路径调用 local_module.initialize()", check_non_preload_path_initializes_local),
        ("预加载工厂失败时重置 _local_initialized", check_preload_factory_failure_resets_flag),
        ("预加载工厂返回 None 时重置 _local_initialized", check_preload_factory_returns_none_resets_flag),
        ("预加载工厂成功后赋值并初始化 local_module", check_preload_factory_success_assigns_local_then_inits),
        ("预加载 initialize() 失败时保留 local_module", check_preload_init_failure_keeps_local_module),
        ("cloud_module 始终被初始化", check_cloud_always_initialized),
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
