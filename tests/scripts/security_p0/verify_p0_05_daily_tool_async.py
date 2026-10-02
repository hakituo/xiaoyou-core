#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-05 验证脚本: daily_tool.py 同步 _run 改为 async def

验证项：
1. RecordActivityTool._run 与 GetDailySummaryTool._run 均为 async def
2. 源码不存在同步 `def _run(` 重写
3. _run 可被 await（动态加载并调用，验证返回 str 而非 TypeError）
4. 关键分支逻辑保留（wakeup/sleep/meal/study/activity）
"""
import sys
import inspect
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "core" / "tools" / "daily_tool.py"


def _install_stubs():
    """预存根依赖。"""
    # config
    if "config" not in sys.modules:
        pkg = ModuleType("config")
        pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules["config"] = pkg

    # core 包
    for pkg_name in ("core", "core.utils", "core.tools", "core.services",
                     "core.services.daily", "core.services.active_care",
                     "core.services.active_care.state"):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg

    # core.utils.logger
    if "core.utils.logger" not in sys.modules:
        import logging
        m = ModuleType("core.utils.logger")
        m.get_logger = lambda name: logging.getLogger(name)
        sys.modules["core.utils.logger"] = m

    # core.tools.base
    if "core.tools.base" not in sys.modules:
        from abc import ABC, abstractmethod
        base_mod = ModuleType("core.tools.base")

        class BaseTool(ABC):
            name: str = ""
            description: str = ""
            args_schema = None
            short_description: str = ""
            category: str = "utility"
            enabled_by_default: bool = True

            def set_runtime_context(self, context):
                self._runtime_context = context

            def _get_ctx(self, key, default=None):
                return getattr(self, "_runtime_context", {}).get(key, default)

            @abstractmethod
            async def _run(self, *args, **kwargs):
                pass

            async def run(self, *args, **kwargs):
                try:
                    result = await self._run(*args, **kwargs)
                    return str(result)
                except Exception as e:
                    return f"Error executing tool {self.name}: {e}"

        base_mod.BaseTool = BaseTool
        sys.modules["core.tools.base"] = base_mod

    # core.services.daily.manager
    if "core.services.daily.manager" not in sys.modules:
        m = ModuleType("core.services.daily.manager")

        class _StubManager:
            def record_wakeup(self, time_str=None):
                return f"[stub] wakeup recorded: {time_str}"
            def record_sleep(self, time_str=None):
                return f"[stub] sleep recorded: {time_str}"
            def record_meal(self, meal_type, content):
                return f"[stub] meal recorded: {meal_type}/{content}"
            def record_study(self, topic, desc):
                return f"[stub] study recorded: {topic}/{desc}"
            def record_activity(self, activity_type, content):
                return f"[stub] activity recorded: {activity_type}/{content}"
            def get_today_summary(self):
                return "[stub] today summary"

        m.get_daily_manager = lambda: _StubManager()
        m.DailyManager = _StubManager
        sys.modules["core.services.daily.manager"] = m

    # core.services.active_care.state.get_sleep_state_manager
    if "core.services.active_care.state" in sys.modules:
        state_mod = sys.modules["core.services.active_care.state"]
        state_mod.get_sleep_state_manager = lambda: type(
            "_StubSleepStateManager", (),
            {
                "sync_sleep_time_sync": lambda self, time_str=None: True,
                "sync_wakeup_time_sync": lambda self, time_str=None: True,
            },
        )()


def load_module():
    _install_stubs()

    content = TOOL_PATH.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("daily_tool_p0_05", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_source_async() -> list[str]:
    """检查源码层面 _run 已改为 async def。"""
    issues = []
    content = TOOL_PATH.read_text(encoding="utf-8")
    # 禁止 `    def _run(` 同步重写
    if "    def _run(" in content:
        issues.append("源码仍存在同步 `def _run(` 重写")
    # 必须有 `async def _run(`
    async_count = content.count("    async def _run(")
    if async_count < 2:
        issues.append(f"源码中 `async def _run(` 数量不足: {async_count} < 2")
    return issues


def check_runtime_async(module) -> list[str]:
    """动态验证 _run 是协程且可正确 await。"""
    import asyncio

    issues = []

    RecordActivityTool = getattr(module, "RecordActivityTool", None)
    GetDailySummaryTool = getattr(module, "GetDailySummaryTool", None)

    if RecordActivityTool is None:
        issues.append("缺失 RecordActivityTool 类")
        return issues
    if GetDailySummaryTool is None:
        issues.append("缺失 GetDailySummaryTool 类")
        return issues

    # 1. _run 必须是协程函数（用 inspect 判断）
    if not inspect.iscoroutinefunction(RecordActivityTool._run):
        issues.append("RecordActivityTool._run 不是协程函数")
    if not inspect.iscoroutinefunction(GetDailySummaryTool._run):
        issues.append("GetDailySummaryTool._run 不是协程函数")

    # 2. 实际调用 _run，验证不抛 TypeError
    try:
        tool = RecordActivityTool()
        # 测试所有分支
        for category, kwargs in [
            ("wakeup", {"time_str": "07:00"}),
            ("sleep", {"time_str": "23:00"}),
            ("meal", {"content": "米饭", "detail": "lunch"}),
            ("study", {"content": "数学", "detail": "微积分"}),
            ("activity", {"content": "玩游戏"}),
        ]:
            try:
                result = asyncio.run(tool._run(category=category, **kwargs))
                if not isinstance(result, str):
                    issues.append(f"[{category}] 返回值非 str: {type(result)}")
                if "Error executing tool" in result:
                    issues.append(f"[{category}] _run 内部异常: {result}")
            except TypeError as te:
                issues.append(f"[{category}] _run 调用失败（TypeError）: {te}")
            except Exception as e:
                issues.append(f"[{category}] _run 调用失败: {e}")
    except Exception as e:
        issues.append(f"RecordActivityTool 实例化失败: {e}")

    try:
        tool2 = GetDailySummaryTool()
        try:
            result = asyncio.run(tool2._run())
            if not isinstance(result, str):
                issues.append(f"[summary] 返回值非 str: {type(result)}")
            if "Error executing tool" in result:
                issues.append(f"[summary] _run 内部异常: {result}")
        except TypeError as te:
            issues.append(f"[summary] _run 调用失败（TypeError）: {te}")
        except Exception as e:
            issues.append(f"[summary] _run 调用失败: {e}")
    except Exception as e:
        issues.append(f"GetDailySummaryTool 实例化失败: {e}")

    return issues


def check_run_method_works(module) -> list[str]:
    """通过 BaseTool.run 路径调用，验证不会触发 await str 的 TypeError。"""
    import asyncio

    issues = []
    RecordActivityTool = getattr(module, "RecordActivityTool", None)
    if RecordActivityTool is None:
        issues.append("缺失 RecordActivityTool 类")
        return issues

    tool = RecordActivityTool()
    try:
        result = asyncio.run(tool.run(category="activity", content="测试"))
        # run() 失败时返回 "Error executing tool ..."，成功时返回 str 结果
        if "Error executing tool" in result and "can't be used in 'await' expression" in result:
            issues.append(f"通过 run() 调用仍触发 await str TypeError: {result}")
    except Exception as e:
        issues.append(f"通过 run() 调用异常: {e}")

    return issues


def main() -> int:
    if not TOOL_PATH.exists():
        print(f"[ERROR] daily_tool.py 不存在: {TOOL_PATH}")
        return 2

    all_issues: list[str] = []
    all_issues.extend(check_source_async())

    try:
        module = load_module()
        all_issues.extend(check_runtime_async(module))
        all_issues.extend(check_run_method_works(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] daily_tool.py 同步 _run 已改为 async def")
    print("  - RecordActivityTool._run 与 GetDailySummaryTool._run 均为协程函数")
    print("  - 5 个分支（wakeup/sleep/meal/study/activity）全部可正常 await")
    print("  - 通过 BaseTool.run() 路径调用不再触发 await str TypeError")
    return 0


if __name__ == "__main__":
    sys.exit(main())
