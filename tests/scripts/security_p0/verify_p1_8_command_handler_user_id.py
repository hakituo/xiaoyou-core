"""P1-8 command/handler.py 共享 user_id 修复 — 验证脚本

验证 CommandHandler 不再持有固定 user_id="command_system" 的共享 memory_manager，
且 /clear 命令作用于调用方传入的 memory（用户会话级 memory），不会跨用户污染。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p1_8_command_handler_user_id.py
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'-' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _has_attr_assign(class_ast, method_name, attr_name):
    """检查类中某方法是否包含 self.<attr_name> = ... 赋值。"""
    method = next(
        (n for n in class_ast.body
         if isinstance(n, ast.FunctionDef) and n.name == method_name),
        None,
    )
    if method is None:
        return False
    for stmt in ast.walk(method):
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"
                        and tgt.attr == attr_name):
                    return True
    return False


def _method_refs_attr(class_ast, method_name, attr_name):
    """检查类中某方法是否引用 self.<attr_name>（任意形式：读取/调用）。"""
    method = next(
        (n for n in class_ast.body
         if isinstance(n, ast.FunctionDef) and n.name == method_name),
        None,
    )
    if method is None:
        return False
    for stmt in ast.walk(method):
        if (isinstance(stmt, ast.Attribute)
                and isinstance(stmt.value, ast.Name)
                and stmt.value.id == "self"
                and stmt.attr == attr_name):
            return True
    return False


# ──────────────────────────────────────────────────────────────
# 测试 1：__init__ 不再赋值 self.memory_manager / self.chat_agent
# ──────────────────────────────────────────────────────────────
def test_init_no_shared_attrs() -> list[str]:
    issues: list[str] = []
    _section("测试 1：__init__ 不再赋值 self.memory_manager / self.chat_agent")

    from core.services.command import handler as handler_mod

    src = inspect.getsource(handler_mod)
    tree = ast.parse(src)
    cls = next(
        (n for n in tree.body
         if isinstance(n, ast.ClassDef) and n.name == "CommandHandler"),
        None,
    )
    if cls is None:
        issues.append("未找到 CommandHandler 类定义")
        return issues

    if _has_attr_assign(cls, "__init__", "memory_manager"):
        issues.append("__init__ 中仍存在 self.memory_manager = ... 赋值")
    if _has_attr_assign(cls, "__init__", "chat_agent"):
        issues.append("__init__ 中仍存在 self.chat_agent = ... 赋值")

    # 实例化后实例属性也不应有 memory_manager / chat_agent
    h = handler_mod.CommandHandler()
    if hasattr(h, "memory_manager"):
        issues.append(f"实例仍持有 memory_manager 属性: {h.memory_manager!r}")
    if hasattr(h, "chat_agent"):
        issues.append(f"实例仍持有 chat_agent 属性: {h.chat_agent!r}")

    if not issues:
        _ok("__init__ 已不再创建 self.memory_manager / self.chat_agent")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 2：_handle_clear 不再引用 self.memory_manager
# ──────────────────────────────────────────────────────────────
def test_clear_no_self_memory_manager() -> list[str]:
    issues: list[str] = []
    _section("测试 2：_handle_clear 不再引用 self.memory_manager")

    from core.services.command.handler import CommandHandler

    src = inspect.getsource(CommandHandler)
    tree = ast.parse(src)
    cls = next(
        (n for n in tree.body
         if isinstance(n, ast.ClassDef) and n.name == "CommandHandler"),
        None,
    )
    if cls is None:
        issues.append("未找到 CommandHandler 类定义")
        return issues

    if _method_refs_attr(cls, "_handle_clear", "memory_manager"):
        issues.append("_handle_clear 仍引用 self.memory_manager")

    if not issues:
        _ok("_handle_clear 已不引用 self.memory_manager，仅使用传入的 memory 参数")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 3：/clear 端到端，传入 mock memory，验证仅作用于传入对象
# ──────────────────────────────────────────────────────────────
class _MockMemory:
    """轻量 mock，避免触发 WeightedMemoryManager 的后台加载线程与磁盘 IO。"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.short_term_memory = []
        self.lock = __import__("threading").Lock()
        self._use_rw_lock = False
        self.saved = False

    def save_memory(self):
        self.saved = True


def test_clear_end_to_end_isolated() -> list[str]:
    issues: list[str] = []
    _section("测试 3：/clear 仅作用于传入的 memory（mock 隔离测试）")

    from core.services.command.handler import CommandHandler

    user_a = _MockMemory("user_A")
    user_b = _MockMemory("user_B")

    for i in range(3):
        user_a.short_term_memory.append({"role": "user", "content": f"A-{i}"})
        user_b.short_term_memory.append({"role": "user", "content": f"B-{i}"})

    user_b_before = list(user_b.short_term_memory)

    h = CommandHandler()
    is_cmd, resp = h.handle("/clear", user_a)

    if not is_cmd:
        issues.append("/clear 未被识别为命令")
    if "History cleared" not in resp:
        issues.append(f"/clear 响应异常: {resp!r}")
    if user_a.short_term_memory:
        issues.append(f"user_a.short_term_memory 未被清空: {user_a.short_term_memory!r}")
    if not user_a.saved:
        issues.append("user_a.save_memory 未被调用")
    # 关键：user_b 不应受影响
    if user_b.short_term_memory != user_b_before:
        issues.append(
            f"user_b.short_term_memory 被 /clear 污染: "
            f"before={user_b_before!r}, after={user_b.short_term_memory!r}"
        )
    if user_b.saved:
        issues.append("user_b.save_memory 不应被调用")

    if not issues:
        _ok("A 用户 /clear 仅作用于 A 的 memory，B 的 memory 完全不变")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 4：handle 传入不同 user_id 的 memory，互不影响
# ──────────────────────────────────────────────────────────────
def test_handle_isolation_across_users() -> list[str]:
    issues: list[str] = []
    _section("测试 4：handle 多用户隔离（mock 端到端）")

    from core.services.command.handler import CommandHandler

    h = CommandHandler()
    users = [_MockMemory(f"user_{i}") for i in range(5)]
    for i, u in enumerate(users):
        u.short_term_memory.append({"role": "user", "content": f"msg-{i}"})

    # 每个 user 都执行 /clear
    for u in users:
        is_cmd, resp = h.handle("/clear", u)
        if not is_cmd or "History cleared" not in resp:
            issues.append(f"user={u.user_id} /clear 失败: {resp!r}")

    # 验证：每个 user 自己的 memory 被清空，且没有交叉污染
    for u in users:
        if u.short_term_memory:
            issues.append(
                f"user={u.user_id} short_term_memory 未被清空: {u.short_term_memory!r}"
            )
        if not u.saved:
            issues.append(f"user={u.user_id} save_memory 未被调用")

    if not issues:
        _ok("5 个用户分别执行 /clear，各自 memory 独立清空，无交叉影响")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 5：模块导入正常（无 get_default_chat_agent 残留）
# ──────────────────────────────────────────────────────────────
def test_module_imports_clean() -> list[str]:
    issues: list[str] = []
    _section("测试 5：模块导入正常，无 get_default_chat_agent 残留")

    try:
        import importlib
        from core.services.command import handler as handler_mod

        importlib.reload(handler_mod)
        src = inspect.getsource(handler_mod)
        # 检查模块级是否还导入 get_default_chat_agent
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "get_default_chat_agent":
                        issues.append("模块仍从 chat_agent 导入 get_default_chat_agent")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "chat_agent" in (alias.name or ""):
                        issues.append(f"模块仍导入 chat_agent: {alias.name}")
    except Exception as e:
        issues.append(f"模块导入失败: {e!r}")

    if not issues:
        _ok("模块导入正常，无 get_default_chat_agent / chat_agent 残留依赖")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 6：/help 命令仍可用（回归测试）
# ──────────────────────────────────────────────────────────────
def test_help_still_works() -> list[str]:
    issues: list[str] = []
    _section("测试 6：/help 与未知命令回归测试")

    from core.services.command.handler import CommandHandler

    h = CommandHandler()
    user = _MockMemory("user_help")

    is_cmd, resp = h.handle("/help", user)
    if not is_cmd:
        issues.append("/help 未被识别为命令")
    if "Available commands" not in resp:
        issues.append(f"/help 响应异常: {resp!r}")

    # 未知命令也应有响应
    is_cmd, resp = h.handle("/no_such_cmd", user)
    if not is_cmd:
        issues.append("未知命令未返回 is_cmd=True")
    if "Unknown command" not in resp:
        issues.append(f"未知命令响应异常: {resp!r}")

    # 非命令文本应返回 (False, "")
    is_cmd, resp = h.handle("hello world", user)
    if is_cmd:
        issues.append(f"非命令文本被误判为命令: resp={resp!r}")

    if not issues:
        _ok("/help、未知命令、非命令文本三种场景均正常")
    else:
        for it in issues:
            _fail(it)
    return issues


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────
def main() -> int:
    print("P1-8 command/handler.py 共享 user_id 修复验证")

    all_issues: list[str] = []
    for test in [
        test_init_no_shared_attrs,
        test_clear_no_self_memory_manager,
        test_clear_end_to_end_isolated,
        test_handle_isolation_across_users,
        test_module_imports_clean,
        test_help_still_works,
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
