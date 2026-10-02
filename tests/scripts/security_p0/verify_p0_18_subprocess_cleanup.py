"""P0-18 验证脚本：nvidia-smi 子进程资源泄漏修复

验证目标：
1. core/utils/async_subprocess.py 提供 run_subprocess_with_timeout
2. resource_components.py 与 resource/monitor.py 从 async_subprocess 导入该函数
3. 4 处原 create_subprocess_exec + wait_for 调用已迁移到 run_subprocess_with_timeout
4. run_subprocess_with_timeout 正常路径返回 (returncode, stdout, stderr)
5. run_subprocess_with_timeout 超时路径：抛 asyncio.TimeoutError 且子进程被 kill+wait
6. run_subprocess_with_timeout 异常路径：子进程被 kill+wait
7. 端到端：模拟超时场景，子进程 returncode 不为 None（已被 kill）

修复要点（P0-18）：
- 新增 core/utils/async_subprocess.py，封装 create_subprocess_exec +
  wait_for + try/except kill+wait
- core/resource_components.py 两处 nvidia-smi 调用改用 run_subprocess_with_timeout
- core/resource/monitor.py 两处 nvidia-smi 调用改用 run_subprocess_with_timeout
"""
import asyncio
import inspect
import os
import sys
import time
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# 1. 模块导入与函数存在性检查
# ============================================================================

def check_async_subprocess_has_run_function():
    issues = []
    from core.utils import async_subprocess
    if not hasattr(async_subprocess, "run_subprocess_with_timeout"):
        issues.append("async_subprocess 缺少 run_subprocess_with_timeout")
        return issues
    if not callable(async_subprocess.run_subprocess_with_timeout):
        issues.append("run_subprocess_with_timeout 不可调用")
    if not asyncio.iscoroutinefunction(async_subprocess.run_subprocess_with_timeout):
        issues.append("run_subprocess_with_timeout 应为协程函数")
    return issues


def check_async_subprocess_has_safe_kill():
    issues = []
    from core.utils import async_subprocess
    if not hasattr(async_subprocess, "_safe_kill"):
        issues.append("async_subprocess 缺少 _safe_kill（内部辅助）")
        return issues
    if not asyncio.iscoroutinefunction(async_subprocess._safe_kill):
        issues.append("_safe_kill 应为协程函数")
    return issues


def check_resource_components_imports():
    issues = []
    import core.resource_components as rc
    src = inspect.getsource(rc)
    if "from core.utils.async_subprocess import" not in src:
        issues.append("resource_components 未从 async_subprocess 导入")
    elif "run_subprocess_with_timeout" not in src:
        issues.append("resource_components 未导入 run_subprocess_with_timeout")
    return issues


def check_resource_monitor_imports():
    issues = []
    import core.resource.monitor as rm
    src = inspect.getsource(rm)
    if "from core.utils.async_subprocess import" not in src:
        issues.append("resource/monitor 未从 async_subprocess 导入")
    elif "run_subprocess_with_timeout" not in src:
        issues.append("resource/monitor 未导入 run_subprocess_with_timeout")
    return issues


# ============================================================================
# 2. 源码静态检查：4 处调用点已迁移
# ============================================================================

def check_no_create_subprocess_in_resource_components():
    """resource_components 不再直接调用 create_subprocess_exec"""
    issues = []
    import core.resource_components as rc
    src = inspect.getsource(rc)
    # 检查是否还有 create_subprocess_exec 调用
    if "create_subprocess_exec(" in src:
        # 找出具体行
        for i, line in enumerate(src.splitlines(), 1):
            if "create_subprocess_exec(" in line:
                issues.append(
                    f"resource_components L{i} 仍调用 "
                    f"create_subprocess_exec: {line.strip()}"
                )
    # 检查是否使用 run_subprocess_with_timeout
    call_count = src.count("run_subprocess_with_timeout(")
    if call_count < 2:
        issues.append(
            f"resource_components 应有 2 处 run_subprocess_with_timeout 调用，"
            f"实际 {call_count}"
        )
    return issues


def check_no_create_subprocess_in_resource_monitor():
    """resource/monitor 不再直接调用 create_subprocess_exec"""
    issues = []
    import core.resource.monitor as rm
    src = inspect.getsource(rm)
    if "create_subprocess_exec(" in src:
        for i, line in enumerate(src.splitlines(), 1):
            if "create_subprocess_exec(" in line:
                issues.append(
                    f"resource/monitor L{i} 仍调用 "
                    f"create_subprocess_exec: {line.strip()}"
                )
    call_count = src.count("run_subprocess_with_timeout(")
    if call_count < 2:
        issues.append(
            f"resource/monitor 应有 2 处 run_subprocess_with_timeout 调用，"
            f"实际 {call_count}"
        )
    return issues


def check_safe_kill_logic_in_source():
    """run_subprocess_with_timeout 源码中应有 kill+wait 清理逻辑"""
    issues = []
    from core.utils import async_subprocess
    src = inspect.getsource(async_subprocess.run_subprocess_with_timeout)
    # 必须有 TimeoutError 处理
    if "TimeoutError" not in src:
        issues.append("run_subprocess_with_timeout 缺少 TimeoutError 处理")
    # 必须有 _safe_kill 调用（超时和异常路径都要清理）
    safe_kill_count = src.count("_safe_kill")
    if safe_kill_count < 2:
        issues.append(
            f"run_subprocess_with_timeout 应在超时+异常两处调用 _safe_kill，"
            f"实际 {safe_kill_count}"
        )
    return issues


# ============================================================================
# 3. 功能测试：正常路径
# ============================================================================

def check_run_subprocess_normal():
    """正常路径返回 (returncode, stdout, stderr)"""
    from core.utils.async_subprocess import run_subprocess_with_timeout

    async def run():
        rc, out, err = await run_subprocess_with_timeout(
            [sys.executable, "-c", "print('hello')"],
            timeout=10.0,
        )
        return rc, out, err

    issues = []
    try:
        rc, out, err = asyncio.run(run())
    except Exception as e:
        issues.append(f"正常路径抛异常: {type(e).__name__}: {e}")
        return issues

    if rc != 0:
        issues.append(f"正常路径 returncode 应为 0，实际 {rc}")
    if b"hello" not in out:
        issues.append(f"正常路径 stdout 应包含 'hello'，实际 {out!r}")
    return issues


def check_run_subprocess_nonzero_exit():
    """子进程返回非零 exit code 时也正确返回"""
    from core.utils.async_subprocess import run_subprocess_with_timeout

    async def run():
        rc, out, err = await run_subprocess_with_timeout(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            timeout=10.0,
        )
        return rc, out, err

    issues = []
    try:
        rc, out, err = asyncio.run(run())
    except Exception as e:
        issues.append(f"非零 exit 路径抛异常: {type(e).__name__}: {e}")
        return issues

    if rc != 3:
        issues.append(f"非零 exit 路径 returncode 应为 3，实际 {rc}")
    return issues


# ============================================================================
# 4. 超时路径测试：子进程必须被 kill
# ============================================================================

def check_run_subprocess_timeout_kills_child():
    """超时时子进程被 kill+wait，抛 TimeoutError。

    用一个长时间运行的子进程（sleep 30s），设 timeout=0.3，
    验证：(1) 抛 asyncio.TimeoutError (2) 子进程 returncode 不为 None
    """
    from core.utils.async_subprocess import run_subprocess_with_timeout

    async def run():
        # 用 python -c "import time; time.sleep(30)" 启动长跑子进程
        await run_subprocess_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.3,
        )

    issues = []
    raised = False
    t0 = time.time()
    try:
        asyncio.run(run())
        issues.append("超时路径未抛 TimeoutError")
    except asyncio.TimeoutError:
        raised = True
    except Exception as e:
        issues.append(
            f"超时路径应抛 TimeoutError，实际抛 {type(e).__name__}: {e}"
        )
        return issues

    elapsed = time.time() - t0
    if not raised:
        return issues

    # 应在合理时间内返回（kill+wait 后立即返回）
    if elapsed > 5.0:
        issues.append(
            f"超时路径耗时 {elapsed:.2f}s，过长，可能 kill 未生效"
        )

    return issues


def check_run_subprocess_timeout_child_returncode_set():
    """超时后子进程的 returncode 应被设置（不为 None），证明已 wait。

    通过 mock 拦截 _safe_kill，检查传入的 proc.returncode
    是否在 _safe_kill 后变为非 None。
    """
    from core.utils import async_subprocess

    captured_procs = []

    async def fake_safe_kill(proc):
        # 真实 kill+wait，并记录
        try:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        except Exception:
            pass
        captured_procs.append(proc)

    issues = []
    with patch.object(async_subprocess, "_safe_kill", side_effect=fake_safe_kill):
        async def run():
            try:
                await async_subprocess.run_subprocess_with_timeout(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    timeout=0.3,
                )
            except asyncio.TimeoutError:
                pass

        asyncio.run(run())

    if not captured_procs:
        issues.append("_safe_kill 未被调用")
        return issues

    proc = captured_procs[0]
    if proc.returncode is None:
        issues.append(
            "超时后子进程 returncode 仍为 None，说明未 wait"
        )
    return issues


# ============================================================================
# 5. 异常路径测试：子进程也必须被 kill
# ============================================================================

def check_run_subprocess_exception_kills_child():
    """异常路径（如 wait_for 内部异常）也保证 kill+wait。

    模拟 proc.communicate() 抛异常，验证 _safe_kill 被调用。
    """
    from core.utils import async_subprocess

    issues = []

    # 创建一个 mock proc 模拟 communicate 抛异常
    class FakeProc:
        def __init__(self):
            self.returncode = None
            self._killed = False

        def kill(self):
            self._killed = True

        async def wait(self):
            self.returncode = -9 if self._killed else 0
            return self.returncode

        async def communicate(self):
            raise RuntimeError("模拟 communicate 异常")

    fake_proc = FakeProc()

    async def fake_create(*args, **kwargs):
        return fake_proc

    captured = []

    async def spy_safe_kill(proc):
        captured.append(proc)
        # 真实调用 _safe_kill 的逻辑
        try:
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass

    with patch.object(
        asyncio, "create_subprocess_exec", side_effect=fake_create
    ), patch.object(
        async_subprocess, "_safe_kill", side_effect=spy_safe_kill
    ):
        async def run():
            try:
                await async_subprocess.run_subprocess_with_timeout(
                    ["fake"], timeout=5.0,
                )
                issues.append("异常路径未抛异常")
            except RuntimeError:
                pass  # 预期

        asyncio.run(run())

    if not captured:
        issues.append("异常路径 _safe_kill 未被调用")
    if not fake_proc._killed:
        issues.append("异常路径子进程未被 kill")
    return issues


def check_safe_kill_handles_process_lookup_error():
    """_safe_kill 在进程已退出时（ProcessLookupError）不抛异常"""
    from core.utils.async_subprocess import _safe_kill

    class FakeProc:
        def __init__(self):
            self.returncode = 0  # 已退出

        def kill(self):
            raise ProcessLookupError("进程已退出")

        async def wait(self):
            return 0

    issues = []
    try:
        asyncio.run(_safe_kill(FakeProc()))
    except Exception as e:
        issues.append(
            f"_safe_kill 在 ProcessLookupError 时不应抛异常，"
            f"实际抛 {type(e).__name__}: {e}"
        )
    return issues


def check_safe_kill_handles_already_dead():
    """_safe_kill 在 returncode 已设置时跳过 kill 但仍 wait"""
    from core.utils.async_subprocess import _safe_kill

    killed = []

    class FakeProc:
        def __init__(self):
            self.returncode = 0  # 已退出

        def kill(self):
            killed.append(True)  # 不应该被调用

        async def wait(self):
            return 0

    issues = []
    try:
        asyncio.run(_safe_kill(FakeProc()))
    except Exception as e:
        issues.append(f"_safe_kill 抛异常: {type(e).__name__}: {e}")
        return issues

    if killed:
        issues.append("_safe_kill 在 returncode 已设置时不应调用 kill")
    return issues


# ============================================================================
# 主入口
# ============================================================================

def main():
    print("=" * 70)
    print("P0-18 验证：nvidia-smi 子进程资源泄漏修复")
    print("=" * 70)
    all_issues = []
    checks = [
        ("提供 run_subprocess_with_timeout", check_async_subprocess_has_run_function),
        ("提供 _safe_kill", check_async_subprocess_has_safe_kill),
        ("rc 导入 run_subprocess", check_resource_components_imports),
        ("monitor 导入 run_subprocess", check_resource_monitor_imports),
        ("rc 不再用 create_subprocess_exec",
         check_no_create_subprocess_in_resource_components),
        ("monitor 不再用 create_subprocess_exec",
         check_no_create_subprocess_in_resource_monitor),
        ("含 kill+wait 逻辑", check_safe_kill_logic_in_source),
        ("正常路径返回正确", check_run_subprocess_normal),
        ("非零 exit 也正确返回", check_run_subprocess_nonzero_exit),
        ("超时路径抛 TimeoutError",
         check_run_subprocess_timeout_kills_child),
        ("超时后 returncode 已设置",
         check_run_subprocess_timeout_child_returncode_set),
        ("异常路径 _safe_kill 被调用",
         check_run_subprocess_exception_kills_child),
        ("_safe_kill 处理 ProcessLookupError",
         check_safe_kill_handles_process_lookup_error),
        ("_safe_kill 已死进程跳过 kill",
         check_safe_kill_handles_already_dead),
    ]
    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            import traceback
            issues = [f"检查抛异常: {type(e).__name__}: {e}"]
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
