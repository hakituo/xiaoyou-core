#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 scripts/model_registry/register_cloud_model.py 的注册逻辑。

在项目里注册一个新模型要动 5 个注册点，脚本一旦写错就会污染真实配置。
本脚本把全部注册点复制到临时目录，让注册脚本在副本上真实写盘，校验：
1. 多模态模型：provider 模型池 / VISION_MODEL_KEYWORDS / 视觉测试多模态用例 /
   OpenRouter 连通性用例 / provider_default_models 全部写入正确
2. 纯文本模型：只进 provider 模型池与视觉测试的纯文本用例，不进多模态名单
3. 幂等：同一模型重复注册不产生重复条目
4. 临时目录外的真实仓库文件不被改动

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\model_registry\\verify_register_cloud_model.py

退出码：0=全部通过；非0=存在失败项。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "model_registry" / "register_cloud_model.py"

# 注册脚本会改动的全部文件（相对仓库根）
TARGET_FILES = [
    "config/settings_model.py",
    "core/llm/model_capabilities.py",
    "tests/scripts/verify_vision_routing.py",
    "tests/scripts/llm/verify_openrouter_models.py",
    "config/yaml/sections/model_routing.yaml",
]

_failures: list[str] = []


def _check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [OK] {message}")
    else:
        print(f"  [FAIL] {message}")
        _failures.append(message)


def _load_module():
    spec = importlib.util.spec_from_file_location("register_cloud_model", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_sandbox(module, tmp_root: Path) -> None:
    """把注册点复制到临时目录，并把模块里的路径常量重定向过去。"""
    for rel in TARGET_FILES:
        src = PROJECT_ROOT / rel
        dst = tmp_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)

    module.REPO_ROOT = tmp_root
    module.SETTINGS_MODEL = tmp_root / "config/settings_model.py"
    module.MODEL_CAPABILITIES = tmp_root / "core/llm/model_capabilities.py"
    module.VISION_ROUTING_TEST = tmp_root / "tests/scripts/verify_vision_routing.py"
    module.OPENROUTER_VERIFY = tmp_root / "tests/scripts/llm/verify_openrouter_models.py"
    module.MODEL_ROUTING_YAML = tmp_root / "config/yaml/sections/model_routing.yaml"


def _run_register(module, provider: str, model: str, vision: bool, set_default: bool) -> list[str]:
    edits = module._build_edits(provider, model, vision, model.rsplit("/", 1)[-1], set_default)
    return module._apply_edits(edits, dry_run=False)


def main() -> int:
    print("=" * 70)
    print("注册脚本验证")
    print("=" * 70)

    module = _load_module()

    with tempfile.TemporaryDirectory(prefix="register_cloud_model_") as tmp:
        tmp_root = Path(tmp)
        _make_sandbox(module, tmp_root)

        # ---- 场景 1：多模态模型 ----
        print("\n[1] 注册多模态模型 openrouter / x-ai/grok-4.6（含 --set-default）")
        changed = _run_register(module, "openrouter", "x-ai/grok-4.6", vision=True, set_default=True)

        settings = (tmp_root / "config/settings_model.py").read_text(encoding="utf-8")
        caps = (tmp_root / "core/llm/model_capabilities.py").read_text(encoding="utf-8")
        vision_test = (tmp_root / "tests/scripts/verify_vision_routing.py").read_text(encoding="utf-8")
        or_test = (tmp_root / "tests/scripts/llm/verify_openrouter_models.py").read_text(encoding="utf-8")
        yaml_text = (tmp_root / "config/yaml/sections/model_routing.yaml").read_text(encoding="utf-8")

        _check(any("settings_model.py" in c for c in changed), "settings_model.py 被改动")
        _check('"x-ai/grok-4.6",' in settings, "PROVIDER_DEFAULT_MODELS 写入型号")
        _check('"grok-4.6",' in caps, "VISION_MODEL_KEYWORDS 写入关键词")
        _check('"cloud:openrouter:x-ai/grok-4.6",' in vision_test, "视觉测试写入 cloud 路径用例")
        _check('"x-ai/grok-4.6",' in vision_test, "视觉测试写入裸模型名用例")
        _check('"x-ai/grok-4.6",' in or_test, "OpenRouter 连通性测试写入型号")
        _check("openrouter: x-ai/grok-4.6" in yaml_text, "model_routing.yaml 设置 provider 默认模型")

        # 关键：只改 openrouter 段，不能串到别的 provider
        _check("zhipu" in settings, "settings_model.py 结构未被破坏（其余 provider 仍在）")

        # ---- 场景 2：幂等 ----
        print("\n[2] 重复注册同一模型（应全部跳过）")
        changed_again = _run_register(module, "openrouter", "x-ai/grok-4.6", vision=True, set_default=True)
        _check(not changed_again, f"重复注册无新增改动（实际 {changed_again}）")
        caps_again = (tmp_root / "core/llm/model_capabilities.py").read_text(encoding="utf-8")
        _check(caps_again.count('"grok-4.6",') == 1, "VISION_MODEL_KEYWORDS 未出现重复条目")

        # ---- 场景 3：纯文本模型 ----
        print("\n[3] 注册纯文本模型 deepseek / deepseek-v9-text-test")
        changed_text = _run_register(module, "deepseek", "deepseek-v9-text-test", vision=False, set_default=False)
        caps_text = (tmp_root / "core/llm/model_capabilities.py").read_text(encoding="utf-8")
        vision_test_text = (tmp_root / "tests/scripts/verify_vision_routing.py").read_text(encoding="utf-8")
        or_test_text = (tmp_root / "tests/scripts/llm/verify_openrouter_models.py").read_text(encoding="utf-8")

        _check("model_capabilities.py" not in " ".join(changed_text), "纯文本模型不进多模态名单")
        _check('"deepseek-v9-text-test",' in vision_test_text, "纯文本模型写入 text_models 用例")
        _check(
            '"deepseek-v9-text-test",' not in or_test_text,
            "非 openrouter 模型不写进 OpenRouter 连通性用例",
        )
        _check(caps_text == caps_again, "多模态名单在纯文本注册后保持原样")

    # ---- 场景 4：真实仓库文件未被污染 ----
    print("\n[4] 真实仓库文件完整性")
    for rel in TARGET_FILES:
        original = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        _check("deepseek-v9-text-test" not in original, f"{rel} 未被测试写入污染")

    print("\n" + "=" * 70)
    if _failures:
        print(f"❌ {len(_failures)} 项失败")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
