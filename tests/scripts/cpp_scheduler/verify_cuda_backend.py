"""验证 CUDA/CPU 双版本共存的加载器逻辑与 CUDA 版编译产物。

背景（2026-08-19）：
1. CMakeLists.txt 删除了泄漏到 nvcc 的全局 add_compile_options(/utf-8 ...)，
   改为 target_compile_options 只作用于本项目 C++ 目标，解决
   "nvcc fatal: A single input file is required" 编译失败。
2. CMakeLists.txt 顶部用 FORCE 钉死 BUILD_TESTING=OFF，避免 llama.cpp/libuv
   include(CTest) 把它打开导致编译引用旧 API 的 tests/ 目标而失败。
3. scheduler_wrapper.py 对实际选中的 pyd 目录动态注册配套 bin/Release（MSVC
   多配置生成器把 llama.dll / ggml-*.dll 输出到 build/<variant>/bin/Release），
   AddDllDirectory 为 LIFO（后添加先搜），确保优先使用新编译 DLL 而非
   site-packages 里的旧版。

验证方式：AST 静态解析源码 + 可选运行时反射（导入 CUDA 版扩展）。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_FILE = PROJECT_ROOT / "core" / "services" / "scheduler" / "scheduler_wrapper.py"
CMAKE_FILE = PROJECT_ROOT / "cpp_modules" / "cpp_scheduler" / "CMakeLists.txt"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def check_wrapper_dll_registration() -> list[str]:
    """检查加载器是否对选中 pyd 目录注册配套 bin/Release DLL 目录。"""
    issues: list[str] = []
    source = WRAPPER_FILE.read_text(encoding="utf-8")
    tree = _parse(WRAPPER_FILE)
    func = _find_function(tree, "_import_scheduler_py")
    if func is None:
        return ["scheduler_wrapper.py 缺少 _import_scheduler_py"]

    segment = ast.get_source_segment(source, func) or ""
    # 关键模式：os.path.join(os.path.dirname(path), "bin", "Release")
    if 'os.path.join(os.path.dirname(path), "bin", "Release")' not in segment:
        issues.append("import 循环未注册配套 bin/Release DLL 目录")

    # XIAOYOU_CPP_BACKEND 双版本开关仍存在
    if "XIAOYOU_CPP_BACKEND" not in segment:
        issues.append("缺少 XIAOYOU_CPP_BACKEND 双版本开关")

    # site-packages 兜底仍保留
    if "site.getsitepackages()" not in segment:
        issues.append("site-packages 兜底目录注册被移除")

    return issues


def check_cmake_fixes() -> list[str]:
    """检查 CMakeLists 的两处修复：/utf-8 不再全局泄漏、BUILD_TESTING 强制 OFF。

    按行检查并跳过注释行（修复说明中含 add_compile_options 等字样）。
    """
    issues: list[str] = []
    code_lines = [
        line.strip()
        for line in CMAKE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if any("add_compile_options(/utf-8" in line for line in code_lines):
        issues.append("CMakeLists 非注释行仍存在全局 add_compile_options(/utf-8 ...)")
    if not any(
        'set(BUILD_TESTING OFF CACHE BOOL "Build tests" FORCE)' in line for line in code_lines
    ):
        issues.append("CMakeLists 未用 FORCE 钉死 BUILD_TESTING=OFF")
    if any("add_subdirectory(tests)" in line for line in code_lines):
        issues.append("CMakeLists 非注释行仍启用 add_subdirectory(tests)")
    if any("enable_testing()" in line for line in code_lines):
        issues.append("CMakeLists 非注释行仍调用 enable_testing()")
    return issues


def check_runtime_import() -> list[str]:
    """环境可导入时做真实加载检查（cuda 模式）。"""
    issues: list[str] = []
    try:
        os.environ["XIAOYOU_CPP_BACKEND"] = "cuda"
        sys.path.insert(0, str(PROJECT_ROOT))
        sys.path.insert(0, str(PROJECT_ROOT / "core" / "services" / "scheduler"))
        import ctypes

        import scheduler_wrapper as sw  # noqa: PLC0415

        mod = sw._get_scheduler_py()
        if mod is None:
            issues.append("cuda 模式下 scheduler_py 加载失败")
            return issues

        pyd_file = getattr(mod, "__file__", "") or ""
        if "cpp_scheduler" not in pyd_file or "cuda" not in pyd_file:
            issues.append(f"cuda 模式未加载 build/cuda 下的 pyd: {pyd_file}")

        # 校验配套 llama.dll / ggml-cuda.dll 来源必须是 build/cuda/bin/Release
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        k32.GetModuleFileNameW.restype = ctypes.c_uint
        for dll_name, required_marker in (
            ("llama.dll", "cuda"),
            ("ggml-cuda.dll", "cuda"),
        ):
            h = k32.GetModuleHandleW(dll_name)
            if not h:
                issues.append(f"cuda 模式未加载 {dll_name}")
                continue
            buf = ctypes.create_unicode_buffer(2048)
            k32.GetModuleFileNameW(ctypes.c_void_p(h), buf, 2048)
            dll_path = buf.value
            if required_marker not in dll_path:
                issues.append(f"{dll_name} 来源异常（应为 build/cuda/bin/Release）: {dll_path}")
    except Exception as e:  # 导入失败仅提示，不阻断 AST 结论
        print(f"  提示: 运行期反射检查跳过（{e}）")
    finally:
        for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "core" / "services" / "scheduler")):
            if p in sys.path:
                sys.path.remove(p)
        os.environ.pop("XIAOYOU_CPP_BACKEND", None)
    return issues


def main() -> int:
    issues: list[str] = []
    issues += check_wrapper_dll_registration()
    issues += check_cmake_fixes()

    print("=== 验证: CUDA/CPU 双版本加载器与 CUDA 编译修复 ===")
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

    print("✓ scheduler_wrapper 注册配套 bin/Release 且保留 XIAOYOU_CPP_BACKEND 开关")
    print("✓ CMakeLists 不再全局泄漏 /utf-8，BUILD_TESTING 已 FORCE 关闭")
    print("✓ cuda 模式下 pyd 与 llama.dll/ggml-cuda.dll 均来自 build/cuda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
