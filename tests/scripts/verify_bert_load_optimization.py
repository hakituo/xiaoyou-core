#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BERT 加载优化验证脚本

验证 BERT C++ 引擎冗余 import 已清理，启动期不再加载 bert_engine_py：
1. bert_runtime_mixin.py 不包含 bert_engine_py 字符串
2. bert_runtime_mixin.py 不包含 _HAS_CPP_BERT 字符串
3. bert_runtime_mixin.py 不包含 find_spec("bert_engine_py") 调用
4. stream_utils/__init__.py 模块顶层不包含 from core.services.data_ops.bert_analyzer import get_bert_analyzer
5. stream_utils/__init__.py 的 detect_wants_long 函数体内包含延迟 import
6. py_compile 编译修改的两个文件通过
7. 新 Python 进程 import streaming 后，sys.modules 不包含 BERT 相关模块
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BERT_RUNTIME_FILE = PROJECT_ROOT / "core" / "services" / "data_ops" / "bert_runtime_mixin.py"
STREAM_UTILS_FILE = (
    PROJECT_ROOT / "core" / "agents" / "chat_agent_components" / "stream_utils" / "__init__.py"
)


def read_file(file_path: Path) -> str:
    """读取文件内容"""
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        sys.exit(1)
    return file_path.read_text(encoding="utf-8")


def check_no_bert_engine_py(content: str) -> bool:
    """检查 1：bert_runtime_mixin.py 不包含 bert_engine_py 字符串"""
    if "bert_engine_py" in content:
        # 找出所有匹配行
        matches = [
            f"  L{i+1}: {line.strip()}"
            for i, line in enumerate(content.split("\n"))
            if "bert_engine_py" in line
        ]
        print(f"❌ bert_runtime_mixin.py 仍包含 bert_engine_py 字符串（{len(matches)} 处）")
        for m in matches:
            print(m)
        return False
    print("✅ 检查 1 通过：bert_runtime_mixin.py 不包含 bert_engine_py 字符串")
    return True


def check_no_has_cpp_bert(content: str) -> bool:
    """检查 2：bert_runtime_mixin.py 不包含 _HAS_CPP_BERT 字符串"""
    if "_HAS_CPP_BERT" in content:
        matches = [
            f"  L{i+1}: {line.strip()}"
            for i, line in enumerate(content.split("\n"))
            if "_HAS_CPP_BERT" in line
        ]
        print(f"❌ bert_runtime_mixin.py 仍包含 _HAS_CPP_BERT 字符串（{len(matches)} 处）")
        for m in matches:
            print(m)
        return False
    print("✅ 检查 2 通过：bert_runtime_mixin.py 不包含 _HAS_CPP_BERT 字符串")
    return True


def check_no_find_spec_bert(content: str) -> bool:
    """检查 3：bert_runtime_mixin.py 不包含 find_spec("bert_engine_py") 调用"""
    pattern = r'find_spec\(\s*["\']bert_engine_py["\']'
    matches = re.findall(pattern, content)
    if matches:
        print(f"❌ bert_runtime_mixin.py 仍包含 find_spec(\"bert_engine_py\") 调用（{len(matches)} 处）")
        return False
    print("✅ 检查 3 通过：bert_runtime_mixin.py 不包含 find_spec(\"bert_engine_py\") 调用")
    return True


def check_no_top_level_bert_import(content: str) -> bool:
    """检查 4：stream_utils/__init__.py 模块顶层不包含 get_bert_analyzer 顶层 import"""
    # 匹配行首（无缩进）的 import 语句
    pattern = r"^from\s+core\.services\.data_ops\.bert_analyzer\s+import\s+get_bert_analyzer"
    matches = re.findall(pattern, content, re.MULTILINE)
    if matches:
        print(f"❌ stream_utils/__init__.py 仍存在顶层 import get_bert_analyzer（{len(matches)} 处）")
        return False
    print("✅ 检查 4 通过：stream_utils/__init__.py 模块顶层不包含 get_bert_analyzer import")
    return True


def check_lazy_import_in_detect_wants_long(content: str) -> bool:
    """检查 5：detect_wants_long 函数体内包含延迟 import"""
    # 提取 detect_wants_long 函数体
    pattern = r"def\s+detect_wants_long\s*\([^)]*\)\s*->\s*\w+\s*:.*?(?=\n    @staticmethod|\n    def |\nclass |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("❌ 未找到 detect_wants_long 方法定义")
        return False
    func_body = match.group(0)
    if "from core.services.data_ops.bert_analyzer import get_bert_analyzer" not in func_body:
        print("❌ detect_wants_long 函数体内未包含延迟 import get_bert_analyzer")
        return False
    print("✅ 检查 5 通过：detect_wants_long 函数体内包含延迟 import get_bert_analyzer")
    return True


def check_py_compile() -> bool:
    """检查 6：py_compile 编译修改的两个文件通过"""
    files = [str(BERT_RUNTIME_FILE), str(STREAM_UTILS_FILE)]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", *files],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"❌ py_compile 失败（返回码 {result.returncode}）")
            print(f"   stderr: {result.stderr.strip()}")
            return False
        print("✅ 检查 6 通过：py_compile 编译两个文件通过")
        return True
    except subprocess.TimeoutExpired:
        print("❌ py_compile 超时")
        return False
    except Exception as e:
        print(f"❌ py_compile 异常: {e}")
        return False


def check_streaming_import_no_bert() -> bool:
    """检查 7：新 Python 进程 import streaming 后，sys.modules 不包含 BERT 相关模块"""
    # 子进程代码：import streaming 后检查 sys.modules
    child_code = (
        "import sys, time\n"
        "t0 = time.time()\n"
        "from core.agents.chat_agent_components import streaming\n"
        "elapsed_ms = (time.time() - t0) * 1000\n"
        "forbidden = ['bert_engine_py',\n"
        "             'core.services.data_ops.bert_runtime_mixin',\n"
        "             'core.services.data_ops.bert_analyzer']\n"
        "loaded = [m for m in forbidden if m in sys.modules]\n"
        "if loaded:\n"
        "    print(f'FAIL: 不应加载的模块: {loaded}')\n"
        "    sys.exit(1)\n"
        "else:\n"
        "    print(f'OK: streaming 加载耗时 {elapsed_ms:.1f}ms, 无 BERT 模块加载')\n"
        "    sys.exit(0)\n"
    )
    env = os.environ.copy()
    # 确保子进程能找到项目根目录
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            [sys.executable, "-c", child_code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            print(f"❌ 子进程 import streaming 后仍加载了 BERT 模块")
            if stdout:
                print(f"   stdout: {stdout}")
            if stderr:
                print(f"   stderr: {stderr[-500:]}")
            return False
        print(f"✅ 检查 7 通过：{stdout}")
        return True
    except subprocess.TimeoutExpired:
        print("❌ 子进程 import streaming 超时（60s）")
        return False
    except Exception as e:
        print(f"❌ 检查 7 异常: {e}")
        return False


def main():
    print("=" * 70)
    print("BERT 加载优化验证脚本")
    print(f"  bert_runtime_mixin.py: {BERT_RUNTIME_FILE.relative_to(PROJECT_ROOT)}")
    print(f"  stream_utils/__init__.py: {STREAM_UTILS_FILE.relative_to(PROJECT_ROOT)}")
    print("=" * 70)

    bert_content = read_file(BERT_RUNTIME_FILE)
    stream_content = read_file(STREAM_UTILS_FILE)

    results = [
        check_no_bert_engine_py(bert_content),
        check_no_has_cpp_bert(bert_content),
        check_no_find_spec_bert(bert_content),
        check_no_top_level_bert_import(stream_content),
        check_lazy_import_in_detect_wants_long(stream_content),
        check_py_compile(),
        check_streaming_import_no_bert(),
    ]

    all_pass = all(results)

    print("\n" + "=" * 70)
    if all_pass:
        print("✅ 所有检查通过！BERT 加载优化已正确实施。")
    else:
        failed = sum(1 for r in results if not r)
        print(f"❌ {failed} 项检查未通过，请查看上方详情。")
    print("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
