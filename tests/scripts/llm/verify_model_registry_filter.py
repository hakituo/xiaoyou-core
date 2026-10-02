"""验证模型选择注册池只保留配置允许的供应商，并排除视觉投影文件。"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _new_manager(model_manager_module):
    manager = object.__new__(model_manager_module.ModelManager)
    manager._models = {}
    manager._global_lock = threading.RLock()
    return manager


def run_check() -> int:
    from config import integrated_config
    from config.integrated_config import get_settings
    from core.core_engine import model_manager as model_manager_module

    configured = {
        provider.lower()
        for provider in get_settings().model.registered_cloud_providers
    }
    expected_providers = {"deepseek", "openrouter", "minimax"}
    if configured != expected_providers:
        print(f"FAIL: 模型注册供应商配置异常: {sorted(configured)}")
        return 1

    fake_provider_keys = {
        provider: {
            "default": SimpleNamespace(models=[model_name], api_key="test-key")
        }
        for provider, model_name in {
            "deepseek": "deepseek-v4-flash",
            "openrouter": "openrouter/free",
            "minimax": "MiniMax-M2.5",
            "siliconflow": "Qwen/Qwen3-VL-32B-Instruct",
            "ark": "doubao-seed-2-0-lite-260215",
            "zhipu": "glm-4.5-air",
        }.items()
    }
    fake_settings = SimpleNamespace(
        model=SimpleNamespace(
            cloud_provider_keys=fake_provider_keys,
            registered_cloud_providers=sorted(expected_providers),
        )
    )
    fake_env = {
        "DEEPSEEK_API_KEY": "test-key",
        "OPENROUTER_API_KEY": "test-key",
        "MINIMAX_API_KEY": "test-key",
        "SILICONFLOW_API_KEY": "test-key",
        "ARK_API_KEY": "test-key",
    }

    original_get_settings = integrated_config.get_settings
    try:
        integrated_config.get_settings = lambda: fake_settings
        manager = _new_manager(model_manager_module)
        with patch.dict(os.environ, fake_env, clear=True):
            manager._register_cloud_clients_from_llm_module()
    finally:
        integrated_config.get_settings = original_get_settings

    registered_paths = [info.model_path for info in manager._models.values()]
    registered_providers = {
        path.split(":", 2)[1]
        for path in registered_paths
        if path.startswith("cloud:")
    }
    if registered_providers != expected_providers:
        print(
            "FAIL: 实际注册供应商异常: "
            f"{sorted(registered_providers)}, models={sorted(manager._models)}"
        )
        return 2
    if any("vl" in name.lower() for name in manager._models):
        print(f"FAIL: VL 模型仍进入选择注册池: {sorted(manager._models)}")
        return 3

    local_manager = _new_manager(model_manager_module)
    with tempfile.TemporaryDirectory() as temp_dir:
        llm_dir = Path(temp_dir) / "llm"
        llm_dir.mkdir()
        (llm_dir / "mmproj-BF16.gguf").touch()
        (llm_dir / "Qwen3.5-4B-Q4_K_M.gguf").touch()
        local_manager._scan_llm_models(temp_dir)

    if set(local_manager._models) != {"Qwen3.5-4B-Q4_K_M"}:
        print(f"FAIL: 本地 LLM 扫描过滤异常: {sorted(local_manager._models)}")
        return 4

    print("PASS: 注册池仅保留 DeepSeek/OpenRouter/MiniMax，VL 与 mmproj 不显示")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_check())
