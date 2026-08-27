import os
import time
from pathlib import Path
import pytest
from core.utils.common import get_project_root


pytestmark = pytest.mark.gpu


def _get_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


if os.getenv("XIAOYOU_RUN_GPU_TESTS") != "1":
    pytest.skip("需要设置 XIAOYOU_RUN_GPU_TESTS=1 才运行 GPU 推理测试", allow_module_level=True)

llama_cpp = pytest.importorskip("llama_cpp")
Llama = llama_cpp.Llama

# Configuration from app.yaml and module.py
_default_model_path = get_project_root() / "models" / "llm" / "Qwen2___5-7B-Instruct-Q4_K_M.gguf"
MODEL_PATH = os.getenv("XIAOYOU_TEXT_MODEL_PATH", str(_default_model_path))
N_CTX = _get_int_env("XIAOYOU_LLAMA_N_CTX", 2048)
N_GPU_LAYERS = _get_int_env("XIAOYOU_LLAMA_N_GPU_LAYERS", 0)
N_BATCH = _get_int_env("XIAOYOU_LLAMA_N_BATCH", 256)

# Generation parameters from app.yaml
GEN_PARAMS = {
    "temperature": 1.1,
    "min_p": 0.05,
    "repeat_penalty": 1.1,
    "top_p": 0.95,
    "top_k": 40,
    "max_tokens": _get_int_env("XIAOYOU_LLAMA_MAX_TOKENS", 128),
    "stream": True
}

def test_llm():
    print(f"Loading model from: {MODEL_PATH}")
    if not Path(MODEL_PATH).exists():
        pytest.skip(f"Model file not found at {MODEL_PATH}")

    n_batch = int(N_BATCH)
    n_ctx = int(N_CTX)
    if n_batch > n_ctx:
        n_batch = n_ctx

    try:
        start_load = time.time()
        llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=n_ctx,
            n_gpu_layers=int(N_GPU_LAYERS),
            n_batch=n_batch,
            verbose=True
        )
        print(f"Model loaded in {time.time() - start_load:.2f} seconds.")
    except Exception as e:
        print(f"Failed to load model: {e}")
        return

    print("\nStarting inference test...")
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Test. Who are you?"}
    ]

    print(f"Prompt: {messages}")
    print("-" * 20)

    try:
        start_gen = time.time()
        first_token_received = False
        
        stream = llm.create_chat_completion(
            messages=messages,
            **GEN_PARAMS
        )

        full_response = ""
        for chunk in stream:
            if not first_token_received:
                print(f"\n[First token received in {time.time() - start_gen:.2f} seconds]")
                first_token_received = True
            
            if "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    print(content, end="", flush=True)
                    full_response += content

        print(f"\n\nTotal generation time: {time.time() - start_gen:.2f} seconds")
        print("-" * 20)
        print("Test completed successfully.")

    except Exception as e:
        print(f"\nInference failed: {e}")

if __name__ == "__main__":
    test_llm()
