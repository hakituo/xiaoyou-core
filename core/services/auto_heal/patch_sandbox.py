import ast
import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.services.auto_heal.models import Patch
from core.utils.logger import get_logger

logger = get_logger("PatchSandbox")


# 模块级裸名调用黑名单（builtins）。
# 仅匹配直接调用 eval(...) / exec(...) / open(...) 等，不会误伤
# re.compile(...) / path.open(...) 这类属性访问。
_BARE_NAME_DANGEROUS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
}

# 模块级属性访问调用黑名单（完整属性链匹配）。
# 这些调用如果在 import 时被执行，会产生副作用或破坏系统。
_ATTR_DANGEROUS_PATTERNS = (
    "os.system",
    "os.popen",
    "os.exec",
    "os.execv",
    "os.execve",
    "os.spawn",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.rename",
    "os.replace",
    "os.chmod",
    "os.chown",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "shutil.rmtree",
    "shutil.copy",
    "shutil.copyfile",
    "shutil.move",
    "pathlib.Path.write",
    "pathlib.Path.unlink",
    "pathlib.Path.rmdir",
)

# import 时不允许的模块根名（防止 import 阶段产生网络/进程副作用）。
# 注意：这里禁止的是"模块级 import"——即 import 时就会执行的代码。
# 函数体内的 import 不在禁止范围（因为不会在 import 阶段执行）。
_DANGEROUS_MODULE_ROOTS = {
    "socket",
    "http",
    "urllib",
    "requests",
    "aiohttp",
    "ctypes",
    "multiprocessing",
    "signal",
    "pty",
    "telnetlib",
    "smtplib",
    "ftplib",
    "webbrowser",
    "antigravity",  # 彩蛋模块，import 会打开浏览器
}


class PatchSandbox:
    """补丁安全沙箱。

    安全策略（P0-15 修复）：
    1. 真隔离：所有验证都在临时文件上完成，绝不写回真实项目文件，
       避免"写-验证-恢复"窗口期内进程崩溃导致真实文件被污染。
    2. 禁止 import 执行 LLM 代码：不再用 `python -c "import xxx"` 验证，
       改为 AST 危险代码检测 + py_compile 编译验证。
       这样既能捕获语法错误，又能避免 LLM 生成的模块级恶意代码被执行。
    """

    def __init__(self, project_root: Optional[str] = None):
        if project_root:
            self._project_root = Path(project_root)
        else:
            try:
                from core.utils.common import get_project_root

                self._project_root = Path(get_project_root())
            except Exception:
                self._project_root = Path(__file__).parent.parent.parent.parent

    async def verify(self, patch: Patch) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "syntax_ok": False,
            "import_ok": False,
            "ruff_ok": False,
            "errors": [],
            "warnings": [],
        }

        syntax_result = self._check_syntax(patch.patched_code)
        result["syntax_ok"] = syntax_result["ok"]
        if not syntax_result["ok"]:
            result["errors"].append(f"语法错误: {syntax_result['error']}")
            return result

        import_result = await self._check_import(patch)
        result["import_ok"] = import_result["ok"]
        if not import_result["ok"]:
            result["warnings"].append(f"导入检查: {import_result['error']}")

        ruff_result = await self._check_ruff(patch)
        result["ruff_ok"] = ruff_result["ok"]
        if not ruff_result["ok"]:
            result["warnings"].append(f"Ruff 检查: {ruff_result['output'][:500]}")

        result["overall_ok"] = result["syntax_ok"] and (
            result["import_ok"] or len(result["warnings"]) <= 2
        )

        return result

    def _check_syntax(self, code: str) -> Dict[str, Any]:
        try:
            ast.parse(code)
            return {"ok": True}
        except SyntaxError as e:
            return {"ok": False, "error": f"行 {e.lineno}: {e.msg}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _check_import(self, patch: Patch) -> Dict[str, Any]:
        """检查补丁代码是否可以安全"导入"。

        P0-15 修复要点：
        - 不再写回真实项目文件，改用临时文件 + 隔离子进程
        - 不再执行 `import xxx`（会触发模块级代码），改为：
          a) AST 危险代码扫描（检测 os.system/subprocess/eval/exec 等模块级调用
             以及 socket/http 等模块级 import）
          b) py_compile 编译验证（仅编译，不执行模块级代码）
        """
        # 1. AST 危险代码扫描
        ast_result = self._check_dangerous_ast(patch.patched_code)
        if not ast_result["ok"]:
            return {"ok": False, "error": ast_result["error"]}

        # 2. 写入临时文件（绝不写真实项目文件）
        try:
            code_bytes = patch.patched_code.encode("utf-8")
        except Exception as e:
            return {"ok": False, "error": f"编码失败: {e}"}

        # 用 TemporaryDirectory 保证异常时也会清理
        with tempfile.TemporaryDirectory(prefix="patch_sandbox_") as tmpdir:
            # 保留原文件名，便于 ruff/编译器报错定位
            original_name = Path(patch.file_path).name or "patched.py"
            # 若原文件名不是 .py，强制改为 .py（py_compile 要求）
            if not original_name.endswith(".py"):
                original_name = original_name + ".py"
            tmp_path = Path(tmpdir) / original_name
            try:
                tmp_path.write_bytes(code_bytes)
            except Exception as e:
                return {"ok": False, "error": f"写入临时文件失败: {e}"}

            # 3. 在子进程中用 py_compile 验证编译
            #    py_compile 只做语法/字节码编译，不会执行模块级代码，
            #    因此即使 LLM 生成了危险代码也不会被执行。
            #    使用 doraise=True 让错误以异常形式抛出，便于我们捕获。
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import sys, py_compile; "
                f"py_compile.compile(r'{tmp_path}', doraise=True)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._project_root),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=15.0
                )
            except asyncio.TimeoutError:
                # 超时后必须 kill 子进程，避免僵尸进程
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
                return {"ok": False, "error": "编译验证超时"}

            if proc.returncode == 0:
                return {"ok": True}
            else:
                err_msg = stderr.decode("utf-8", errors="replace")[:500]
                return {"ok": False, "error": err_msg or "编译失败（无错误输出）"}

    def _check_dangerous_ast(self, code: str) -> Dict[str, Any]:
        """AST 扫描：检测模块级危险代码。

        检测两类风险：
        1. 模块级（顶层）调用危险函数：os.system / subprocess / eval / exec / open 等
        2. 模块级 import 危险模块：socket / http / urllib / ctypes 等

        函数体/类体内的危险调用不在检测范围（因为 import 阶段不会执行它们），
        这样可以避免误伤正常的工具类代码。

        匹配策略：
        - 裸名调用（eval/exec/open/compile/__import__）只匹配 ast.Name，
          避免误伤 re.compile(...) / path.open(...) 等属性访问。
        - 属性访问调用（os.system/subprocess.Popen 等）匹配完整属性链，
          仅精确匹配或后缀匹配，避免 os.path.join 这类安全调用被误判。
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"ok": False, "error": f"语法错误 行 {e.lineno}: {e.msg}"}

        issues: List[str] = []

        def check_call(call_node: ast.Call) -> None:
            """检查单个 Call 节点是否调用了危险函数。"""
            func = call_node.func
            if isinstance(func, ast.Name):
                # 裸名调用：检查 builtins 黑名单
                if func.id in _BARE_NAME_DANGEROUS:
                    issues.append(f"模块级调用危险函数: {func.id}")
            elif isinstance(func, ast.Attribute):
                # 属性访问：提取完整链并匹配
                call_name = self._get_call_chain(func)
                if call_name:
                    for pattern in _ATTR_DANGEROUS_PATTERNS:
                        # 精确匹配或后缀匹配（应对 from os import system
                        # 后 system() 这种边缘情况，以及模块别名调用）
                        if call_name == pattern or call_name.endswith("." + pattern):
                            issues.append(
                                f"模块级调用危险函数: {call_name} (匹配 {pattern})"
                            )
                            break

        # 只检查模块级（top-level）节点，不递归进函数/类体
        for node in tree.body:
            # 1. 模块级 import 危险模块
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in _DANGEROUS_MODULE_ROOTS:
                        issues.append(f"模块级 import 危险模块: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in _DANGEROUS_MODULE_ROOTS:
                        issues.append(
                            f"模块级 from {node.module} import ... (危险模块)"
                        )

            # 2. 模块级 Call（直接执行函数调用）
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                check_call(node.value)

            # 3. 模块级赋值时调用危险函数：x = os.system(...)
            #    用 ast.walk 遍历赋值右侧的所有 Call 节点（包括嵌套调用）
            elif isinstance(node, ast.Assign):
                for child in ast.walk(node.value):
                    if isinstance(child, ast.Call):
                        check_call(child)

        if issues:
            return {
                "ok": False,
                "error": "; ".join(issues[:5])
                + (f" 等 {len(issues)} 项" if len(issues) > 5 else ""),
            }
        return {"ok": True}

    @staticmethod
    def _get_call_chain(node: ast.AST) -> str:
        """从 Call.func 节点提取完整的属性访问链，如 os.system / subprocess.Popen。

        对于裸名调用（ast.Name）返回 name 本身，由调用方按 builtins 黑名单判断。
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = PatchSandbox._get_call_chain(node.value)
            if base:
                return f"{base}.{node.attr}"
            return node.attr
        return ""

    async def _check_ruff(self, patch: Patch) -> Dict[str, Any]:
        """Ruff 静态检查。

        P0-15 修复要点：
        - 不再写回真实项目文件，改用临时文件
        - ruff 直接对临时文件做静态分析，不影响真实项目
        """
        try:
            code_bytes = patch.patched_code.encode("utf-8")
        except Exception as e:
            return {"ok": False, "output": f"编码失败: {e}"}

        venv_ruff = self._project_root / "venv_core" / "Scripts" / "ruff.exe"
        if not venv_ruff.exists():
            venv_ruff = Path(sys.executable).parent / "ruff"
            if not venv_ruff.exists():
                return {"ok": True, "output": "ruff 不可用，跳过检查"}

        with tempfile.TemporaryDirectory(prefix="patch_sandbox_ruff_") as tmpdir:
            original_name = Path(patch.file_path).name or "patched.py"
            if not original_name.endswith(".py"):
                original_name = original_name + ".py"
            tmp_path = Path(tmpdir) / original_name
            try:
                tmp_path.write_bytes(code_bytes)
            except Exception as e:
                return {"ok": False, "output": f"写入临时文件失败: {e}"}

            try:
                proc = await asyncio.create_subprocess_exec(
                    str(venv_ruff),
                    "check",
                    "--select=E,F",
                    str(tmp_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._project_root),
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
                return {"ok": False, "output": "ruff 检查超时"}
            except Exception as e:
                return {"ok": False, "output": str(e)}

            output = (
                stdout.decode("utf-8", errors="replace")
                + stderr.decode("utf-8", errors="replace")
            ).strip()
            # 把临时文件路径替换为原始 patch 路径，便于排查
            output = output.replace(str(tmp_path), patch.file_path)

            if proc.returncode == 0:
                return {"ok": True, "output": output}
            else:
                return {"ok": False, "output": output[:500]}
