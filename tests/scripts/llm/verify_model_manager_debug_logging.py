"""验证模型管理器调试日志默认静默、可按需开启且不泄露 API Key。"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _new_manager(model_manager_module):
    manager = object.__new__(model_manager_module.ModelManager)
    manager._models = {}
    manager._global_lock = threading.RLock()
    return manager


def _build_fake_settings(secret_value: str) -> SimpleNamespace:
    return SimpleNamespace(
        model=SimpleNamespace(
            cloud_provider_keys={
                "minimax": {
                    "default": SimpleNamespace(
                        models=["MiniMax-M2.5", "M2-her"],
                        api_key=secret_value,
                    )
                },
                "zhipu": {
                    "default": SimpleNamespace(
                        models=["glm-4.5-air"],
                        api_key=secret_value,
                    )
                },
            }
        )
    )


def run_check() -> int:
    from config import integrated_config
    from config.debug_config import DebugSettings
    from core.core_engine import model_manager as model_manager_module

    app_yaml = (ROOT / "config" / "yaml" / "app.yaml").read_text(encoding="utf-8")
    if "  model_manager: false" not in app_yaml:
        print("FAIL: app.yaml 缺少默认关闭的 debug.model_manager 开关")
        return 1

    if DebugSettings.model_fields["model_manager"].default is not False:
        print("FAIL: DebugSettings.model_manager 默认值不是 false")
        return 2

    secret_value = "verification-secret-must-not-appear"
    fake_settings = _build_fake_settings(secret_value)
    fake_env = {
        "MINIMAX_API_KEY": secret_value,
        "AVELINE_API_KEY": secret_value,
        "AVELINE_MODEL": "nalang-xl-0826-16k",
    }

    original_get_settings = integrated_config.get_settings
    try:
        integrated_config.get_settings = lambda: fake_settings

        # 默认关闭时：模型仍正常注册，但不输出逐模型调试日志。
        quiet_logger = MagicMock()
        quiet_manager = _new_manager(model_manager_module)
        with (
            patch.dict(os.environ, fake_env, clear=True),
            patch.object(model_manager_module, "logger", quiet_logger),
            patch.object(
                model_manager_module,
                "is_debug_enabled",
                return_value=False,
            ),
        ):
            quiet_manager._register_cloud_clients_from_llm_module()

        expected_models = {
            "MiniMax-M2.5",
            "MiniMax-M2-her",
            "M2-her",
            "glm-4.5-air",
            "nalang-xl-0826-16k",
        }
        if set(quiet_manager._models) != expected_models:
            print(f"FAIL: 默认关闭时模型注册结果异常: {quiet_manager._models!r}")
            return 3
        if quiet_logger.info.call_count != 0:
            print("FAIL: debug.model_manager=false 时仍输出了 INFO 调试日志")
            return 4

        # 开启时：可见候选/去重摘要，但日志不得包含密钥。
        debug_logger = MagicMock()
        debug_manager = _new_manager(model_manager_module)
        with (
            patch.dict(os.environ, fake_env, clear=True),
            patch.object(model_manager_module, "logger", debug_logger),
            patch.object(
                model_manager_module,
                "is_debug_enabled",
                return_value=True,
            ),
        ):
            debug_manager._register_cloud_clients_from_llm_module()

        debug_calls = repr(debug_logger.info.call_args_list)
        if "已脱敏" not in debug_calls or "跳过重复来源" not in debug_calls:
            print("FAIL: debug.model_manager=true 时缺少脱敏配置或去重日志")
            return 5
        if "已存在，跳过注册" in debug_calls:
            print("FAIL: 重复候选仍进入了最终注册循环")
            return 6
        if secret_value in debug_calls or "api_key=" in debug_calls.lower():
            print("FAIL: 模型管理器 debug 日志仍包含 API Key")
            return 7

        source_text = (ROOT / "core" / "core_engine" / "model_manager.py").read_text(
            encoding="utf-8"
        )
        if "[DEBUG]" in source_text:
            print("FAIL: model_manager.py 仍存在伪 [DEBUG] 文本前缀")
            return 8
    finally:
        integrated_config.get_settings = original_get_settings

    print("PASS: 模型管理器 debug 开关、默认静默、候选去重与密钥脱敏均验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_check())
