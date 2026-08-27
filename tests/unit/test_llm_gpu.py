import os
import sys

import pytest


pytestmark = pytest.mark.gpu

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.getenv("XIAOYOU_RUN_GPU_TESTS") != "1":
    pytest.skip("需要设置 XIAOYOU_RUN_GPU_TESTS=1 才运行 GPU 推理测试", allow_module_level=True)

llama_cpp = pytest.importorskip("llama_cpp")
Llama = llama_cpp.Llama

torch = pytest.importorskip("torch")

def test_llm_gpu():
    print("Testing llama-cpp-python GPU support...")
    
    if torch.cuda.is_available():
        print(f"CUDA is available: {torch.cuda.get_device_name(0)}")
    else:
        print("CUDA is NOT available (according to torch)")

    model_path = os.path.abspath("models/llm/Qwen2___5-7B-Instruct-Q4_K_M.gguf")
    
    if not os.path.exists(model_path):
        print(f"Model path not found: {model_path}")
        # Try the other one
        model_path = os.path.abspath("models/llm/L3-8B-Stheno-v3.2-Q5_K_M.gguf")
        if not os.path.exists(model_path):
            print("No models found.")
            return

    print(f"Loading model from: {model_path}")
    try:
        n_gpu_layers_raw = os.getenv("XIAOYOU_LLAMA_N_GPU_LAYERS", "0")
        try:
            n_gpu_layers = int(n_gpu_layers_raw)
        except Exception:
            n_gpu_layers = 0

        llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            verbose=True,
            n_ctx=2048
        )
        print("Model loaded successfully.")
        
        # Simple generation
        output = llm.create_chat_completion(
            messages=[{"role": "user", "content": "Hello, are you running on GPU?"}],
            max_tokens=50
        )
        print(f"Generation output: {output}")
        
    except Exception as e:
        pytest.fail(f"Error loading/running model: {e}")

if __name__ == "__main__":
    test_llm_gpu()
