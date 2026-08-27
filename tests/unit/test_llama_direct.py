import os
from pathlib import Path
import pytest
from core.utils.common import get_project_root

pytestmark = pytest.mark.gpu


if os.getenv("XIAOYOU_RUN_GPU_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_GPU_TESTS=1 才运行 GPU 推理测试",
        allow_module_level=True,
    )


llama_cpp = pytest.importorskip("llama_cpp")
Llama = llama_cpp.Llama


def _get_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def test_llama_load():
    default_model_path = get_project_root() / "models" / "llm" / "Qwen2___5-7B-Instruct-Q4_K_M.gguf"
    model_path = os.getenv("XIAOYOU_TEXT_MODEL_PATH", str(default_model_path))
    print(f"Loading model from {model_path}...")
    if not Path(model_path).exists():
        pytest.skip(f"Model file not found at {model_path}")
    
    try:
        n_gpu_layers = _get_int_env("XIAOYOU_LLAMA_N_GPU_LAYERS", 0)
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            verbose=True
        )
        print("Model loaded successfully!")
        
        output = llm("Hello, who are you?", max_tokens=32)
        print("Inference result:", output)
        
    except Exception as e:
        pytest.fail(f"Failed to load model: {e}")

if __name__ == "__main__":
    test_llama_load()
