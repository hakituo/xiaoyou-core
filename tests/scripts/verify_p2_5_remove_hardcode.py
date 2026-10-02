# -*- coding: utf-8 -*-
"""P2-5: 移除硬编码（模型名、API URL、进程名等）- 验证脚本

验证内容：
1. config/settings_model.py 定义了 PROVIDER_BASE_URLS / PROVIDER_DEFAULT_MODELS / SUPPORTED_PROVIDERS 模块级常量
2. LLM client 复用 PROVIDER_BASE_URLS（deepseek/ark/zhipu/siliconflow）
3. factory.py 通过 _load_provider_defaults() 延迟加载常量
4. dashscope_client.py 保留原生 API URL（有注释说明）
5. openai_compat/client.py 支持 OPENAI_DEFAULT_MODEL 环境变量
6. ruff check 无 syntax 错误
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv_core" / "Scripts" / "python.exe"
VENV_RUFF = PROJECT_ROOT / "venv_core" / "Scripts" / "ruff.exe"


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def check_constants_defined() -> bool:
    """检查 settings_model.py 定义了模块级常量。"""
    print("\n=== 1. 检查模块级常量定义 ===")
    sm_path = PROJECT_ROOT / "config" / "settings_model.py"
    content = sm_path.read_text(encoding="utf-8")

    expected_constants = [
        "PROVIDER_BASE_URLS",
        "PROVIDER_DEFAULT_MODELS",
        "SUPPORTED_PROVIDERS",
    ]

    all_passed = True
    for const in expected_constants:
        # 检查模块级定义（顶层缩进）
        tree = ast.parse(content)
        found = False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == const:
                        found = True
                        break
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == const:
                    found = True
        if found:
            _ok(f"模块级常量定义: {const}")
        else:
            _fail(f"未找到模块级常量定义: {const}")
            all_passed = False

    return all_passed


def check_constants_content() -> bool:
    """检查常量内容正确（7 个供应商）。"""
    print("\n=== 2. 检查常量内容 ===")
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from config.settings_model import (
            PROVIDER_BASE_URLS,
            PROVIDER_DEFAULT_MODELS,
            SUPPORTED_PROVIDERS,
        )

        expected_providers = {"deepseek", "siliconflow", "dashscope", "minimax", "ark", "zhipu", "aveline"}
        actual_providers = set(SUPPORTED_PROVIDERS)

        if actual_providers == expected_providers:
            _ok(f"SUPPORTED_PROVIDERS 包含 7 个供应商: {sorted(actual_providers)}")
        else:
            _fail(f"SUPPORTED_PROVIDERS 不匹配: 缺少 {expected_providers - actual_providers}, 多出 {actual_providers - expected_providers}")
            return False

        # 检查 base_urls
        for p in ["deepseek", "siliconflow", "dashscope", "minimax", "ark", "zhipu"]:
            url = PROVIDER_BASE_URLS.get(p)
            if url and url.startswith("https://"):
                _ok(f"PROVIDER_BASE_URLS['{p}'] = {url}")
            else:
                _fail(f"PROVIDER_BASE_URLS['{p}'] 无效: {url}")
                return False

        # aveline 可以是 None
        if "aveline" in PROVIDER_BASE_URLS:
            _ok(f"PROVIDER_BASE_URLS['aveline'] = {PROVIDER_BASE_URLS['aveline']}")
        else:
            _fail("PROVIDER_BASE_URLS 缺少 'aveline'")
            return False

        # 检查 default_models
        for p in expected_providers:
            models = PROVIDER_DEFAULT_MODELS.get(p, [])
            if isinstance(models, list) and len(models) > 0:
                _ok(f"PROVIDER_DEFAULT_MODELS['{p}'] = {models[:2]}...")
            else:
                _fail(f"PROVIDER_DEFAULT_MODELS['{p}'] 为空或非 list")
                return False

        return True
    except Exception as e:
        _fail(f"常量内容检查失败: {e}")
        return False


def check_llm_clients_reuse() -> bool:
    """检查 LLM client 复用 PROVIDER_BASE_URLS。"""
    print("\n=== 3. 检查 LLM client 复用 PROVIDER_BASE_URLS ===")

    checks = [
        ("core/llm/openai_compat/deepseek_client.py", "PROVIDER_BASE_URLS"),
        ("core/llm/openai_compat/ark_client.py", "PROVIDER_BASE_URLS"),
        ("core/llm/openai_compat/zhipu_client.py", "PROVIDER_BASE_URLS"),
        ("core/llm/siliconflow_client.py", "PROVIDER_BASE_URLS"),
        ("core/llm/factory.py", "PROVIDER_DEFAULT_MODELS"),
    ]

    all_passed = True
    for rel_path, expected_token in checks:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            _fail(f"文件不存在: {rel_path}")
            all_passed = False
            continue
        content = full_path.read_text(encoding="utf-8")
        if expected_token in content:
            _ok(f"{rel_path}: 复用 {expected_token}")
        else:
            _fail(f"{rel_path}: 未复用 {expected_token}")
            all_passed = False

    return all_passed


def check_factory_lazy_loading() -> bool:
    """检查 factory.py 通过延迟加载避免循环导入。"""
    print("\n=== 4. 检查 factory.py 延迟加载 ===")
    factory_path = PROJECT_ROOT / "core" / "llm" / "factory.py"
    content = factory_path.read_text(encoding="utf-8")

    # 检查是否有 _load_provider_defaults 函数
    if "def _load_provider_defaults" in content:
        _ok("factory.py 定义了 _load_provider_defaults() 函数")
    else:
        _fail("factory.py 未定义 _load_provider_defaults() 函数")
        return False

    # 检查函数内部是否有 import 语句（延迟加载）
    tree = ast.parse(content)
    found_lazy_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_load_provider_defaults":
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    found_lazy_import = True
                    break
            break

    if found_lazy_import:
        _ok("_load_provider_defaults() 内部包含 import 语句（延迟加载）")
    else:
        _fail("_load_provider_defaults() 内部无 import 语句")
        return False

    return True


def check_dashscope_native_url_preserved() -> bool:
    """检查 dashscope_client.py 保留原生 API URL 并有注释说明。"""
    print("\n=== 5. 检查 dashscope_client.py 原生 URL 处理 ===")
    ds_path = PROJECT_ROOT / "core" / "llm" / "dashscope_client.py"
    content = ds_path.read_text(encoding="utf-8")

    # 检查是否包含原生 API URL
    if "services/aigc/text-generation/generation" in content:
        _ok("dashscope_client.py 保留原生 API URL")
    else:
        _fail("dashscope_client.py 未保留原生 API URL")
        return False

    # 检查是否有注释说明不复用 PROVIDER_BASE_URLS
    # 简单检查：附近是否有"原生"或"native"或"compatible-mode"字样
    lines = content.split("\n")
    has_explanation = False
    for i, line in enumerate(lines):
        if "services/aigc/text-generation" in line:
            # 检查前后 5 行是否有注释
            start = max(0, i - 5)
            end = min(len(lines), i + 5)
            for check_line in lines[start:end]:
                if "#" in check_line and any(kw in check_line for kw in ["原生", "native", "compatible-mode", "非 OpenAI", "非OpenAI"]):
                    has_explanation = True
                    break
            break

    if has_explanation:
        _ok("dashscope_client.py 有注释说明为何不复用 PROVIDER_BASE_URLS")
    else:
        _fail("dashscope_client.py 缺少注释说明")
        return False

    return True


def check_openai_default_model_env() -> bool:
    """检查 openai_compat/client.py 支持 OPENAI_DEFAULT_MODEL 环境变量。"""
    print("\n=== 6. 检查 OpenAI client 支持 OPENAI_DEFAULT_MODEL ===")
    client_path = PROJECT_ROOT / "core" / "llm" / "openai_compat" / "client.py"
    content = client_path.read_text(encoding="utf-8")

    if "OPENAI_DEFAULT_MODEL" in content:
        _ok("openai_compat/client.py 支持 OPENAI_DEFAULT_MODEL 环境变量")
    else:
        _fail("openai_compat/client.py 未支持 OPENAI_DEFAULT_MODEL 环境变量")
        return False

    return True


def check_ruff() -> bool:
    """运行 ruff check 验证无 syntax 错误。"""
    print("\n=== 7. 运行 ruff check（E9 + F821）===")
    try:
        result = subprocess.run(
            [
                str(VENV_RUFF), "check",
                "config/settings_model.py",
                "core/llm",
                "--select", "E9,F821",
                "--output-format=concise",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            _ok("ruff check 通过")
            return True
        else:
            errors = [l for l in result.stdout.split("\n") if l.strip() and ("E9" in l or "F821" in l)]
            if not errors:
                _ok("ruff check 通过")
                return True
            _fail(f"ruff check 发现 {len(errors)} 个错误:")
            for e in errors[:10]:
                print(f"    {e}")
            return False
    except Exception as e:
        _fail(f"ruff check 运行失败: {e}")
        return False


def main() -> int:
    print("=" * 70)
    print("P2-5: 移除硬编码（模型名、API URL、进程名等）- 验证脚本")
    print("=" * 70)

    results = []
    results.append(check_constants_defined())
    results.append(check_constants_content())
    results.append(check_llm_clients_reuse())
    results.append(check_factory_lazy_loading())
    results.append(check_dashscope_native_url_preserved())
    results.append(check_openai_default_model_env())
    results.append(check_ruff())

    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"总计: {passed}/{total} 项通过")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
