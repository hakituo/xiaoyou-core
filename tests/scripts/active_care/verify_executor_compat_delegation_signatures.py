"""验证 executor_compat.py 的兼容委托层参数传递契约（关键字/位置参数必须匹配）

背景（2026-09-23）：
    `0538d2f9` 把 executor.py 里 1600+ 行的私有方法机械抽到 `executor_compat.py`
    时，`complete_reminder` 的转发从 `triggered_at=triggered_at` 被改成了位置参数
    `triggered_at`，而 `ReminderHandler.complete_reminder` 的该形参是 keyword-only：

        async def complete_reminder(self, msg_id: str, *, triggered_at: float | None = None)

    于是运行期直接抛
        TypeError: ReminderHandler.complete_reminder() takes 2 positional arguments but 3 were given
    表现为「起床提醒到期 → 推迟/完成路径必崩 → 提醒反复重发」。

    单测没兜住是因为 `tests/unit/test_active_care_due_reminder_and_loop.py` 把
    `executor.complete_reminder` 整体 AsyncMock 掉了，永远走不到真实转发层。

本脚本做两件事：
    1. 静态契约检查：用 AST 取出兼容层里每一处 `self.<子模块>.<方法>(...)` 转发调用，
       解析出真实目标类，用 `inspect.signature().bind()` 按源码里的实参形态试绑定；
       位置参数撞上 keyword-only 形参、少传必填参数、多传参数都会当场暴露。
    2. 运行期端到端检查：用真实的 ReminderHandler + 打桩 workspace service，
       真跑一次 `complete_reminder(msg_id, triggered_at=...)`，确认转发生效。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_executor_compat_delegation_signatures
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_CORE_DIR = _PROJECT_ROOT / "core" / "services" / "active_care" / "core"
_COMPAT_PATH = _CORE_DIR / "executor_compat.py"
_EXECUTOR_PATH = _CORE_DIR / "executor.py"

_PASSED = 0
_FAILED = 0
_SKIPPED: list[str] = []

# 兼容层里不指向「类方法」的调用目标（模块级函数、logger、内置函数等），无需绑定校验
_NON_DELEGATE_CALLS = {
    "is_debug_enabled",
    "get_active_care_config",
    "get_active_care_content_model",
    "get_active_care_content_model",
    "str",
    "float",
    "int",
    "bool",
    "len",
    "list",
    "dict",
    "set",
    "max",
    "min",
    "getattr",
    "hasattr",
    "isinstance",
    "logger.info",
    "logger.warning",
    "logger.debug",
    "logger.error",
    "logger.exception",
}


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [OK] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _skip(msg: str) -> None:
    _SKIPPED.append(msg)
    print(f"  [SKIP] {msg}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


# ==================== 静态契约检查 ====================


def _parse_import_map(paths: list[Path]) -> dict[str, str]:
    """收集 `from x.y import A, B` 形态的 类名 → 模块路径 映射。"""
    mapping: dict[str, str] = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    mapping[alias.asname or alias.name] = node.module
    return mapping


def _parse_executor_submodule_types() -> dict[str, str]:
    """从 executor.py 的 __init__ 里取 `self.<attr> = <ClassName>(...)` 映射。"""
    tree = ast.parse(_EXECUTOR_PATH.read_text(encoding="utf-8"), filename=str(_EXECUTOR_PATH))
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        target = node.targets[0] if node.targets else None
        if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
            continue
        if target.value.id != "self":
            continue
        func = node.value.func
        if isinstance(func, ast.Name):
            result[target.attr] = func.id
    return result


def _dummy_for(arg: ast.expr):
    """给实参造一个占位值——bind() 只校验形态，不校验类型。"""
    if isinstance(arg, ast.Starred):
        return "dummy"
    return "dummy"


def _iter_delegate_calls():
    """产出兼容层里的转发调用：(行号, 宿主属性名或类名, 方法名, ast.Call)。"""
    tree = ast.parse(_COMPAT_PATH.read_text(encoding="utf-8"), filename=str(_COMPAT_PATH))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        owner = node.func.value
        # self.<sub>.<method>(...)
        if (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            yield node.lineno, owner.attr, method, node
        # <ClassName>.<method>(...)（静态方法转发）
        elif isinstance(owner, ast.Name):
            yield node.lineno, owner.id, method, node


def test_delegation_signature_binding() -> None:
    _section("测试 1: 兼容层每一处转发的实参形态都能被真实签名接受")

    import_map = _parse_import_map([_COMPAT_PATH, _EXECUTOR_PATH])
    submodule_types = _parse_executor_submodule_types()
    if not submodule_types:
        _fail("未能从 executor.py 解析出子模块类型映射")
        return
    _ok(f"解析出 {len(submodule_types)} 个子模块类型映射")

    checked = 0
    for lineno, host, method, call in _iter_delegate_calls():
        # 排除非类方法调用（logger.xxx / 模块级函数）
        if f"{host}.{method}" in _NON_DELEGATE_CALLS or host in _NON_DELEGATE_CALLS:
            continue
        if method in _NON_DELEGATE_CALLS:
            continue

        class_name = submodule_types.get(host, host)
        module_path = import_map.get(class_name)
        if not module_path:
            _skip(f"L{lineno} {host}.{method}：找不到 {class_name} 的导入来源")
            continue
        try:
            module = importlib.import_module(module_path)
            target_cls = getattr(module, class_name)
        except Exception as exc:  # pragma: no cover - 导入失败时只提示不判失败
            _skip(f"L{lineno} {host}.{method}：导入 {module_path}.{class_name} 失败 ({exc})")
            continue

        raw_attr = inspect.getattr_static(target_cls, method, None)
        if raw_attr is None:
            _fail(f"L{lineno} {host}.{method}：{class_name} 上不存在该方法")
            continue
        func = getattr(target_cls, method)
        is_static = isinstance(raw_attr, staticmethod)
        is_class = isinstance(raw_attr, classmethod)
        if not callable(func) or not (inspect.isfunction(func) or inspect.ismethod(func)):
            _skip(f"L{lineno} {host}.{method}：非普通方法，跳过")
            continue

        args = [_dummy_for(arg) for arg in call.args]
        kwargs = {kw.arg: "dummy" for kw in call.keywords if kw.arg}
        if any(kw.arg is None for kw in call.keywords):
            _skip(f"L{lineno} {host}.{method}：含 **kwargs 展开，跳过")
            continue

        try:
            signature = inspect.signature(func)
            if is_static:
                signature.bind(*args, **kwargs)
            else:
                signature.bind(None, *args, **kwargs)
        except TypeError as exc:
            _fail(
                f"L{lineno} {host}.{method}：实参形态与 {class_name}.{method} 不匹配",
                f"{exc} | 签名: {inspect.signature(func)} | "
                f"实参: args={args} kwargs={list(kwargs)}",
            )
            continue
        checked += 1
        _ok(f"L{lineno} {host}.{method} 绑定通过（{'static' if is_static else 'instance' if not is_class else 'class'}）")

    if checked == 0:
        _fail("没有任何转发调用被实际校验到，脚本本身可能已失效")
    else:
        _ok(f"共校验 {checked} 处转发调用")


# ==================== 运行期端到端检查 ====================


class _FakeWorkspaceService:
    """记录 complete_message 调用参数的假 workspace service。"""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    async def complete_message(self, msg_id: str, *, triggered_at=None) -> bool:
        self.calls.append((msg_id, triggered_at))
        return True


def _build_compat_harness():
    """构造只挂真实 ReminderHandler 的兼容层宿主。"""
    from core.services.active_care.core.executor_compat import ActiveCareCompatMixin
    from core.services.active_care.core.reminder_handler import ReminderHandler

    class _Harness(ActiveCareCompatMixin):
        def __init__(self):
            self._reminder_handler = ReminderHandler()

    return _Harness()


def test_complete_reminder_runtime() -> None:
    _section("测试 2: 真实 ReminderHandler 下 complete_reminder 转发可用（回归 0538d2f9）")

    harness = _build_compat_harness()
    fake_ws = _FakeWorkspaceService()

    with mock.patch(
        "core.services.workspace.service.get_workspace_service", return_value=fake_ws
    ):
        result = asyncio.run(harness.complete_reminder("r_wakeup", triggered_at=1234.5))

    if result is not True:
        _fail(f"complete_reminder 返回值异常: {result!r}")
    else:
        _ok("complete_reminder 返回 True")

    if fake_ws.calls != [("r_wakeup", 1234.5)]:
        _fail(f"complete_message 收到的参数不符: {fake_ws.calls!r}")
    else:
        _ok("complete_message 收到 (msg_id, triggered_at=1234.5)")


def test_complete_reminder_default_triggered_at() -> None:
    _section("测试 3: triggered_at 缺省时不传该参数也能转发")

    harness = _build_compat_harness()
    fake_ws = _FakeWorkspaceService()

    with mock.patch(
        "core.services.workspace.service.get_workspace_service", return_value=fake_ws
    ):
        result = asyncio.run(harness.complete_reminder("r_plain"))

    if result is not True or fake_ws.calls != [("r_plain", None)]:
        _fail(f"缺省 triggered_at 转发异常: result={result!r} calls={fake_ws.calls!r}")
    else:
        _ok("缺省 triggered_at 转发为 None")


def test_wakeup_defer_path_no_typeerror() -> None:
    _section("测试 4: 起床提醒推迟路径不再抛 TypeError（复现原始报错栈）")

    from core.services.active_care.checker.checker_event_handler import CheckerEventHandler
    from core.services.active_care.decision.decision_context import DecisionFlowContext

    harness = _build_compat_harness()
    fake_ws = _FakeWorkspaceService()

    # checker 只需要 executor / storage / set_next_decision_ts
    checker = SimpleNamespace(
        executor=harness,
        storage=None,
        set_next_decision_ts=mock.AsyncMock(),
    )
    handler = CheckerEventHandler(checker)
    handler._auto_complete_wakeup_plan_item = mock.AsyncMock()

    ctx = DecisionFlowContext(now=2000.0, state_data={}, client_type="qq")
    # persona_filename 不是 dataclass 字段，运行时由决策流程动态挂载
    ctx.persona_filename = "core_ye.json"
    reminder = SimpleNamespace(
        id="r_wakeup_2",
        message="起来，二十分钟到点了——别睡沉，回我一句",
        metadata={"type": "start"},
    )

    with mock.patch(
        "core.services.workspace.service.get_workspace_service", return_value=fake_ws
    ):
        try:
            handled = asyncio.run(
                handler._defer_due_reminder(
                    ctx, reminder, defer_reason="role_sleep:sleeping", allow_nudge=False
                )
            )
        except TypeError as exc:
            _fail("推迟起床提醒仍抛 TypeError", repr(exc))
            return

    if handled is not True:
        _fail(f"_defer_due_reminder 返回值异常: {handled!r}")
    elif fake_ws.calls != [("r_wakeup_2", 2000.0)]:
        _fail(f"起床提醒未按 ctx.now 完成: {fake_ws.calls!r}")
    else:
        _ok("起床提醒推迟路径正常完成提醒，triggered_at=ctx.now")


def main() -> int:
    print("验证 executor_compat 兼容委托层参数传递契约")
    test_delegation_signature_binding()
    test_complete_reminder_runtime()
    test_complete_reminder_default_triggered_at()
    test_wakeup_defer_path_no_typeerror()

    print(f"\n结果: 通过 {_PASSED}，失败 {_FAILED}，跳过 {len(_SKIPPED)}")
    if _SKIPPED:
        print("跳过项（需人工确认，非本次改动范围）：")
        for item in _SKIPPED:
            print(f"  - {item}")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
