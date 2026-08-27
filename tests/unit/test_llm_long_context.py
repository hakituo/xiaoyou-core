import os
import time
import pytest
from config.integrated_config import get_settings


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


def test_long_context():
    print("Loading configuration...")
    settings = get_settings()
    model_path = settings.model.text_path or "./models/qwen"
    print(f"Model path: {model_path}")

    n_ctx = _get_int_env("XIAOYOU_LLAMA_N_CTX", 2048)
    n_gpu_layers = _get_int_env("XIAOYOU_LLAMA_N_GPU_LAYERS", 0)
    n_batch = _get_int_env("XIAOYOU_LLAMA_N_BATCH", 256)
    if n_batch > n_ctx:
        n_batch = n_ctx

    print(f"Initializing Llama with n_ctx={n_ctx}, n_gpu_layers={n_gpu_layers}, n_batch={n_batch}...")
    try:
        llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_batch=n_batch,
            verbose=True
        )
    except Exception as e:
        print(f"Failed to load model: {e}")
        return

    # Create a long prompt (~6000 chars)
    # Using repeating text to simulate length without complexity
    base_text = "This is a test sentence to simulate a long conversation history and system prompt. "
    repeat = _get_int_env("XIAOYOU_LONG_CONTEXT_REPEAT", 20)
    long_prompt = "System: You are a helpful assistant.\n\nUser: " + (base_text * repeat) + "\n\nUser: Please summarize the above."
    
    print(f"\nPrompt length: {len(long_prompt)} characters")
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": long_prompt}
    ]

    print("Starting generation...")
    start_time = time.time()
    
    # Stream=True to measure time to first token
    stream = llm.create_chat_completion(
        messages=messages,
        max_tokens=100,
        stream=True
    )
    
    print("Stream iterator created. Waiting for first chunk...")
    
    first_token_time = None
    chunk_count = 0
    
    for chunk in stream:
        if chunk_count == 0:
            first_token_time = time.time()
            duration = first_token_time - start_time
            print("\n!!! FIRST TOKEN RECEIVED !!!")
            print(f"Time to first token (Prompt Eval): {duration:.4f} seconds")
            
            content = chunk['choices'][0]['delta'].get('content', '')
            print(f"First chunk content: {content}")
        
        chunk_count += 1
        if chunk_count >= 5: # Just check a few chunks
            break
            
    print(f"\nTest finished. Total chunks received: {chunk_count}")

if __name__ == "__main__":
    test_long_context()
