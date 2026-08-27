"""验证 C++ LLM 配置构建器能访问调度器绑定。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_check() -> int:
    from core.services.scheduler.client.cpp_config_builder import (
        CPPConfigBuilder,
        _get_scheduler_class,
    )

    if _get_scheduler_class is None:
        print("FAIL: cpp_config_builder 未导入 scheduler_wrapper")
        return 1

    config_type = _get_scheduler_class("LLMModelConfig")
    worker_type = _get_scheduler_class("GPULLMWorker")
    if config_type is None or worker_type is None:
        print("FAIL: scheduler_py 缺少 LLMModelConfig 或 GPULLMWorker")
        return 2

    config = CPPConfigBuilder.build_llm_config(
        {
            "model_path": "models/llm/test.gguf",
            "max_context_size": 4096,
            "max_batch_size": 512,
            "n_gpu_layers": -1,
        }
    )
    if not isinstance(config, config_type):
        print(f"FAIL: 构建结果类型错误: {type(config)!r}")
        return 3

    print("PASS: CPPConfigBuilder 已连接真实 scheduler_py LLM 绑定")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_check())
