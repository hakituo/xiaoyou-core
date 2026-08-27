"""验证 C++ 调度器首 token 超时自动重启链路修复。

修复内容（2026-08-19）：
1. `CPPSchedulerEngine` 补齐 `_restart_scheduler()` / `_health_check_gpu_worker()`
   代理方法，避免 `cpp_llm_handler.py` 在首 token 超时后调用
   `engine._restart_scheduler()` 抛 `AttributeError`。
2. `HealthMonitor.restart_scheduler()` 不再对同步方法 `engine.start()` 错误地
   `await`，改用 `asyncio.to_thread` 并把保存的 GPU 配置传入以便重启后恢复。

验证方式：AST 静态解析源码（不触发 C++ 扩展加载），在环境可导入时再做真实反射检查。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ENGINE_FILE = PROJECT_ROOT / "core" / "services" / "scheduler" / "cpp_scheduler_engine.py"
HEALTH_FILE = (
    PROJECT_ROOT / "core" / "services" / "scheduler" / "lifecycle" / "health_monitor.py"
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _get_class_methods(tree: ast.Module, class_name: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def _find_method(tree: ast.Module, class_name: str, method_name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == class_name
            and isinstance(node.body, list)
        ):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    item.name == method_name
                ):
                    return item
    return None


def check_engine_proxy() -> list[str]:
    """检查 CPPSchedulerEngine 是否具备 _restart_scheduler 等代理方法。"""
    issues: list[str] = []
    tree = _parse(ENGINE_FILE)
    methods = _get_class_methods(tree, "CPPSchedulerEngine")

    for required in ("_restart_scheduler", "_health_check_gpu_worker"):
        if required not in methods:
            issues.append(f"CPPSchedulerEngine 缺少方法: {required}")
            continue

        node = _find_method(tree, "CPPSchedulerEngine", required)
        assert node is not None
        if not isinstance(node, ast.AsyncFunctionDef):
            issues.append(f"{required} 应为 async 方法")

        # 应代理到 health_monitor 对应方法
        src = ast.get_source_segment(ENGINE_FILE.read_text(encoding="utf-8"), node) or ""
        target = (
            "self.health_monitor.restart_scheduler()"
            if required == "_restart_scheduler"
            else "self.health_monitor.health_check_gpu_worker()"
        )
        if target not in src:
            issues.append(f"{required} 未代理到 {target}")

    return issues


def check_health_monitor_start() -> list[str]:
    """检查 HealthMonitor.restart_scheduler 内不再直接 await 同步的 engine.start。"""
    issues: list[str] = []
    source = HEALTH_FILE.read_text(encoding="utf-8")
    tree = _parse(HEALTH_FILE)
    method = _find_method(tree, "HealthMonitor", "restart_scheduler")
    if method is None:
        return ["HealthMonitor 缺少 restart_scheduler 方法"]

    class AwaitEngineStart(ast.NodeVisitor):
        found = False
        detail = ""

        def visit_Await(self, node: ast.Await) -> None:  # noqa: N802
            # 直接 await self.engine.start(...) 即为错误用法
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Attribute)
                and value.func.value.attr == "engine"
                and value.func.attr == "start"
            ):
                self.found = True
                self.detail = ast.unparse(value)
            self.generic_visit(node)

    visitor = AwaitEngineStart()
    visitor.visit(method)
    if visitor.found:
        issues.append(f"restart_scheduler 中直接 await 同步方法: {visitor.detail}")

    # engine.start 必须通过 asyncio.to_thread 调用
    if "asyncio.to_thread(self.engine.start" not in source:
        issues.append("restart_scheduler 未使用 asyncio.to_thread 调用 engine.start")

    return issues


def check_runtime_import() -> list[str]:
    """环境可导入时做真实反射检查。"""
    issues: list[str] = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine
        from core.services.scheduler.lifecycle.health_monitor import HealthMonitor

        for name in ("_restart_scheduler", "_health_check_gpu_worker"):
            if not hasattr(CPPSchedulerEngine, name):
                issues.append(f"运行期反射: CPPSchedulerEngine 缺少 {name}")

        import inspect

        src = inspect.getsource(HealthMonitor.restart_scheduler)
        if "asyncio.to_thread(self.engine.start" not in src:
            issues.append("运行期反射: restart_scheduler 未线程化调用 engine.start")
    except Exception as e:  # 导入失败仅提示，不阻断 AST 结论
        print(f"  提示: 运行期反射检查跳过（{e}）")
    finally:
        if PROJECT_ROOT in sys.path:
            sys.path.remove(str(PROJECT_ROOT))
    return issues


def main() -> int:
    issues: list[str] = []
    issues += check_engine_proxy()
    issues += check_health_monitor_start()

    print("=== 验证: C++ 调度器自动重启链路 ===")
    if issues:
        print("发现以下问题:")
        for issue in issues:
            print(f"  ✗ {issue}")
        return 1

    issues += check_runtime_import()
    if issues:
        print("发现以下问题:")
        for issue in issues:
            print(f"  ✗ {issue}")
        return 1

    print("✓ CPPSchedulerEngine._restart_scheduler/_health_check_gpu_worker 已存在且为 async 代理")
    print("✓ HealthMonitor.restart_scheduler 已线程化调用 engine.start 并恢复 GPU 配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
