"""P0-15 验证脚本：patch_sandbox.py 真隔离 + 禁止 import 执行 LLM 代码

验证目标：
1. 真隔离：_check_import 和 _check_ruff 不再写回真实项目文件，改用临时文件
2. 禁止 import 执行 LLM 代码：不再用 `python -c "import xxx"`，改为 py_compile + AST 扫描
3. AST 危险代码检测：模块级 os.system/eval/exec/subprocess/import socket 等被拒绝
4. 不误伤：re.compile/os.path.join/函数体内危险调用不被拒绝
5. 端到端：安全补丁通过，含模块级危险代码的补丁被拒绝

修复要点：
- _check_import 写入 tempfile.TemporaryDirectory，不再 write_text 到真实 file_path
- _check_import 用 py_compile.compile(doraise=True) 替代 `python -c "import xxx"`
- 新增 _check_dangerous_ast 检测模块级危险调用和危险 import
- _check_ruff 同样改用临时文件，不再写回真实项目文件
"""
import asyncio
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# 1. 源码静态检查：确认不再写回真实文件、不再用 import 执行
# ============================================================================

def check_check_import_no_real_file_write() -> list[str]:
    """场景1：_check_import 不应再写回真实项目文件。"""
    issues: list[str] = []
    from core.services.auto_heal.patch_sandbox import PatchSandbox

    src = inspect.getsource(PatchSandbox._check_import)

    # 不应出现直接写回真实 file_path 的模式
    # 旧代码：file_path.write_text(patch.patched_code, ...)
    # 旧代码：file_path.read_text(...) 作为备份
    if "file_path.write_text" in src:
        issues.append(
            "_check_import 仍包含 file_path.write_text，会写回真实项目文件"
        )
    if "file_path.read_text" in src:
        issues.append(
            "_check_import 仍包含 file_path.read_text（旧备份逻辑），应改用临时文件"
        )

    # 应使用临时文件
    if "tempfile" not in src and "TemporaryDirectory" not in src:
        issues.append("_check_import 未使用 tempfile/TemporaryDirectory，缺少真隔离")

    return issues


def check_check_import_no_import_execution() -> list[str]:
    """场景2：_check_import 不应再用 `python -c "import xxx"` 执行 LLM 代码。"""
    issues: list[str] = []
    from core.services.auto_heal.patch_sandbox import PatchSandbox

    src = inspect.getsource(PatchSandbox._check_import)

    # 旧代码：f"import {module_path}" 作为 -c 参数
    # 这种模式会实际执行模块级代码，对 LLM 生成代码不安全
    if 'f"import {module_path}"' in src or "f'import {module_path}'" in src:
        issues.append("_check_import 仍用 `import {module_path}` 执行 LLM 代码")

    # 不应再出现 module_path 变量（旧逻辑用于构造 import 语句）
    if "module_path" in src and "module_path =" in src:
        issues.append("_check_import 仍构造 module_path，可能仍走 import 执行路径")

    # 应使用 py_compile 替代
    if "py_compile" not in src:
        issues.append("_check_import 未使用 py_compile，无法安全验证编译")

    return issues


def check_check_ruff_no_real_file_write() -> list[str]:
    """场景3：_check_ruff 不应再写回真实项目文件。"""
    issues: list[str] = []
    from core.services.auto_heal.patch_sandbox import PatchSandbox

    src = inspect.getsource(PatchSandbox._check_ruff)

    if "file_path.write_text" in src:
        issues.append("_check_ruff 仍包含 file_path.write_text，会写回真实项目文件")
    if "file_path.read_text" in src:
        issues.append(
            "_check_ruff 仍包含 file_path.read_text（旧备份逻辑），应改用临时文件"
        )

    if "tempfile" not in src and "TemporaryDirectory" not in src:
        issues.append("_check_ruff 未使用 tempfile/TemporaryDirectory，缺少真隔离")

    return issues


def check_dangerous_ast_method_exists() -> list[str]:
    """场景4：应存在 _check_dangerous_ast 方法。"""
    issues: list[str] = []
    from core.services.auto_heal.patch_sandbox import PatchSandbox

    if not hasattr(PatchSandbox, "_check_dangerous_ast"):
        issues.append("PatchSandbox 缺少 _check_dangerous_ast 方法")
        return issues

    src = inspect.getsource(PatchSandbox._check_dangerous_ast)
    # 应检查模块级 Call
    if "ast.Call" not in src:
        issues.append("_check_dangerous_ast 未检查 ast.Call 节点")
    # 应检查模块级 Import
    if "ast.Import" not in src:
        issues.append("_check_dangerous_ast 未检查 ast.Import 节点")

    return issues


# ============================================================================
# 2. AST 危险代码检测：模块级危险调用应被拒绝
# ============================================================================

def _ast_check(code: str) -> dict:
    """辅助：直接调用 _check_dangerous_ast。"""
    from core.services.auto_heal.patch_sandbox import PatchSandbox

    sandbox = PatchSandbox()
    return sandbox._check_dangerous_ast(code)


def check_ast_rejects_os_system() -> list[str]:
    """场景5：模块级 os.system(...) 应被拒绝。"""
    issues: list[str] = []
    code = "import os\nos.system('rm -rf /')\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 os.system 未被拒绝：{result}")
    return issues


def check_ast_rejects_eval() -> list[str]:
    """场景6：模块级 eval(...) 应被拒绝。"""
    issues: list[str] = []
    code = "x = eval('__import__(\"os\").system(\"ls\")')\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 eval 未被拒绝：{result}")
    return issues


def check_ast_rejects_exec() -> list[str]:
    """场景7：模块级 exec(...) 应被拒绝。"""
    issues: list[str] = []
    code = "exec('print(1)')\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 exec 未被拒绝：{result}")
    return issues


def check_ast_rejects_subprocess_popen() -> list[str]:
    """场景8：模块级 subprocess.Popen(...) 应被拒绝。"""
    issues: list[str] = []
    code = "import subprocess\nsubprocess.Popen(['ls'])\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 subprocess.Popen 未被拒绝：{result}")
    return issues


def check_ast_rejects_module_level_import_socket() -> list[str]:
    """场景9：模块级 import socket 应被拒绝。"""
    issues: list[str] = []
    code = "import socket\ns = socket.socket()\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 import socket 未被拒绝：{result}")
    return issues


def check_ast_rejects_module_level_import_http() -> list[str]:
    """场景10：模块级 from http.client import ... 应被拒绝。"""
    issues: list[str] = []
    code = "from http.client import HTTPConnection\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 from http.client import 未被拒绝：{result}")
    return issues


def check_ast_rejects_open_call() -> list[str]:
    """场景11：模块级 open(...) 应被拒绝。"""
    issues: list[str] = []
    code = "f = open('/etc/passwd')\n"
    result = _ast_check(code)
    if result["ok"]:
        issues.append(f"模块级 open(...) 未被拒绝：{result}")
    return issues


# ============================================================================
# 3. AST 不误伤：合法的模块级代码不应被拒绝
# ============================================================================

def check_ast_allows_re_compile() -> list[str]:
    """场景12：模块级 re.compile(...) 不应被拒绝（避免误伤）。"""
    issues: list[str] = []
    code = "import re\nMY_REGEX = re.compile(r'\\d+')\n"
    result = _ast_check(code)
    if not result["ok"]:
        issues.append(f"模块级 re.compile 被误判为危险：{result}")
    return issues


def check_ast_allows_os_path_join() -> list[str]:
    """场景13：模块级 os.path.join(...) 不应被拒绝（避免误伤）。"""
    issues: list[str] = []
    code = "import os\nMY_PATH = os.path.join('a', 'b')\n"
    result = _ast_check(code)
    if not result["ok"]:
        issues.append(f"模块级 os.path.join 被误判为危险：{result}")
    return issues


def check_ast_allows_dangerous_call_in_function() -> list[str]:
    """场景14：函数体内的 os.system(...) 不应被拒绝（只检查模块级）。"""
    issues: list[str] = []
    code = (
        "import os\n"
        "def run_cmd(cmd):\n"
        "    return os.system(cmd)\n"
    )
    result = _ast_check(code)
    if not result["ok"]:
        issues.append(f"函数体内的 os.system 被误判为危险：{result}")
    return issues


def check_ast_allows_normal_imports() -> list[str]:
    """场景15：正常的 import os / import sys 不应被拒绝。"""
    issues: list[str] = []
    code = (
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from typing import Optional\n"
    )
    result = _ast_check(code)
    if not result["ok"]:
        issues.append(f"正常 import 被误判为危险：{result}")
    return issues


# ============================================================================
# 4. 真隔离端到端测试：真实项目文件不被修改
# ============================================================================

def check_real_file_not_modified_by_check_import() -> list[str]:
    """场景16：_check_import 执行后真实项目文件内容不变。"""
    issues: list[str] = []

    # 创建一个临时项目根目录
    with tempfile.TemporaryDirectory(prefix="sandbox_e2e_") as tmp_project:
        tmp_project = Path(tmp_project)
        # 在临时项目下创建一个真实的 target 文件
        target_rel = "mymodule/file.py"
        target_abs = tmp_project / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        original_content = "# original\nx = 1\n"
        target_abs.write_text(original_content, encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))

        # 补丁代码：安全的 Python 代码（不触发 AST 危险检测）
        patched_code = "# patched\ny = 2\nprint('hello')\n"
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code=original_content,
        )

        try:
            asyncio.run(sandbox._check_import(patch))
        except Exception as e:
            issues.append(f"_check_import 调用异常: {type(e).__name__}: {e}")

        # 验证真实文件未被修改
        after_content = target_abs.read_text(encoding="utf-8")
        if after_content != original_content:
            issues.append(
                f"真实文件被修改了！\n"
                f"  期望: {original_content!r}\n"
                f"  实际: {after_content!r}"
            )

    return issues


def check_real_file_not_modified_by_check_ruff() -> list[str]:
    """场景17：_check_ruff 执行后真实项目文件内容不变。"""
    issues: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sandbox_e2e_ruff_") as tmp_project:
        tmp_project = Path(tmp_project)
        target_rel = "mymodule/file.py"
        target_abs = tmp_project / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        original_content = "# original\nx = 1\n"
        target_abs.write_text(original_content, encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))
        patched_code = "# patched\ny = 2\n"
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code=original_content,
        )

        try:
            asyncio.run(sandbox._check_ruff(patch))
        except Exception as e:
            issues.append(f"_check_ruff 调用异常: {type(e).__name__}: {e}")

        after_content = target_abs.read_text(encoding="utf-8")
        if after_content != original_content:
            issues.append(
                f"真实文件被修改了！\n"
                f"  期望: {original_content!r}\n"
                f"  实际: {after_content!r}"
            )

    return issues


# ============================================================================
# 5. 端到端 verify() 测试
# ============================================================================

def check_verify_safe_patch_passes() -> list[str]:
    """场景18：安全补丁 verify() 应返回 import_ok=True。"""
    issues: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sandbox_verify_safe_") as tmp_project:
        tmp_project = Path(tmp_project)
        target_rel = "safe_module.py"
        target_abs = tmp_project / target_rel
        target_abs.write_text("# original\n", encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))
        # 安全的模块级代码：只有 import 和简单赋值
        patched_code = (
            "import os\n"
            "import sys\n"
            "from typing import Optional\n"
            "\n"
            "MY_CONST = 42\n"
            "MY_PATH = os.path.join('a', 'b')\n"
            "\n"
            "def helper():\n"
            "    return MY_CONST\n"
        )
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code="# original\n",
        )

        result = asyncio.run(sandbox.verify(patch))
        if not result["import_ok"]:
            issues.append(
                f"安全补丁 import_ok 应为 True，实际 False。warnings={result.get('warnings')}"
            )

    return issues


def check_verify_dangerous_patch_fails() -> list[str]:
    """场景19：含模块级 os.system 的补丁 verify() 应返回 import_ok=False。"""
    issues: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sandbox_verify_danger_") as tmp_project:
        tmp_project = Path(tmp_project)
        target_rel = "danger_module.py"
        target_abs = tmp_project / target_rel
        target_abs.write_text("# original\n", encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))
        # 模块级危险调用：os.system
        patched_code = (
            "import os\n"
            "os.system('echo pwned')\n"
            "def helper():\n"
            "    return 1\n"
        )
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code="# original\n",
        )

        result = asyncio.run(sandbox.verify(patch))
        if result["import_ok"]:
            issues.append(
                f"含模块级 os.system 的补丁 import_ok 应为 False，实际 True。result={result}"
            )

    return issues


def check_verify_eval_patch_fails() -> list[str]:
    """场景20：含模块级 eval 的补丁 verify() 应返回 import_ok=False。"""
    issues: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sandbox_verify_eval_") as tmp_project:
        tmp_project = Path(tmp_project)
        target_rel = "eval_module.py"
        target_abs = tmp_project / target_rel
        target_abs.write_text("# original\n", encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))
        patched_code = "x = eval('1 + 1')\n"
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code="# original\n",
        )

        result = asyncio.run(sandbox.verify(patch))
        if result["import_ok"]:
            issues.append(
                f"含模块级 eval 的补丁 import_ok 应为 False，实际 True。result={result}"
            )

    return issues


def check_verify_no_temp_files_left() -> list[str]:
    """场景21：verify() 执行后不应在系统临时目录留下 patch_sandbox_* 残留。"""
    issues: list[str] = []

    import glob

    # 记录执行前的 patch_sandbox_* 临时目录
    tmp_root = tempfile.gettempdir()
    before = set(glob.glob(os.path.join(tmp_root, "patch_sandbox_*")))

    with tempfile.TemporaryDirectory(prefix="sandbox_verify_temp_") as tmp_project:
        tmp_project = Path(tmp_project)
        target_rel = "tmp_test.py"
        target_abs = tmp_project / target_rel
        target_abs.write_text("# original\n", encoding="utf-8")

        from core.services.auto_heal.patch_sandbox import PatchSandbox
        from core.services.auto_heal.models import Patch

        sandbox = PatchSandbox(project_root=str(tmp_project))
        patched_code = "x = 1\n"
        patch = Patch(
            file_path=target_rel,
            patched_code=patched_code,
            original_code="# original\n",
        )

        asyncio.run(sandbox.verify(patch))

    # 检查执行后是否有新增的残留（TemporaryDirectory 会在退出时清理，
    # 但若异常退出可能残留）
    after = set(glob.glob(os.path.join(tmp_root, "patch_sandbox_*")))
    leftover = after - before
    if leftover:
        # 尝试清理残留
        for p in leftover:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except Exception:
                pass
        issues.append(
            f"verify() 执行后留下临时目录残留：{leftover}（已尝试清理）"
        )

    return issues


# ============================================================================
# 主入口
# ============================================================================

def main() -> int:
    print("=" * 70)
    print("P0-15 验证：patch_sandbox.py 真隔离 + 禁止 import 执行 LLM 代码")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        # 源码静态检查
        ("_check_import 不再写回真实项目文件", check_check_import_no_real_file_write),
        ("_check_import 不再用 import 执行 LLM 代码", check_check_import_no_import_execution),
        ("_check_ruff 不再写回真实项目文件", check_check_ruff_no_real_file_write),
        ("存在 _check_dangerous_ast 方法", check_dangerous_ast_method_exists),
        # AST 危险代码检测
        ("AST 拒绝模块级 os.system", check_ast_rejects_os_system),
        ("AST 拒绝模块级 eval", check_ast_rejects_eval),
        ("AST 拒绝模块级 exec", check_ast_rejects_exec),
        ("AST 拒绝模块级 subprocess.Popen", check_ast_rejects_subprocess_popen),
        ("AST 拒绝模块级 import socket", check_ast_rejects_module_level_import_socket),
        ("AST 拒绝模块级 from http.client import", check_ast_rejects_module_level_import_http),
        ("AST 拒绝模块级 open(...)", check_ast_rejects_open_call),
        # AST 不误伤
        ("AST 不误伤模块级 re.compile", check_ast_allows_re_compile),
        ("AST 不误伤模块级 os.path.join", check_ast_allows_os_path_join),
        ("AST 不误伤函数体内 os.system", check_ast_allows_dangerous_call_in_function),
        ("AST 不误伤正常 import", check_ast_allows_normal_imports),
        # 真隔离端到端
        ("_check_import 不修改真实文件", check_real_file_not_modified_by_check_import),
        ("_check_ruff 不修改真实文件", check_real_file_not_modified_by_check_ruff),
        # verify() 端到端
        ("verify() 安全补丁通过", check_verify_safe_patch_passes),
        ("verify() os.system 补丁被拒绝", check_verify_dangerous_patch_fails),
        ("verify() eval 补丁被拒绝", check_verify_eval_patch_fails),
        ("verify() 不留临时文件残留", check_verify_no_temp_files_left),
    ]

    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            import traceback
            issues = [f"检查本身抛异常: {type(e).__name__}: {e}"]
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
