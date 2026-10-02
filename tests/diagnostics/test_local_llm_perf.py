import sys
import time
import os
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

def test_performance():
    from config.integrated_config import get_settings

    print("=== Local LLM Performance Test ===")
    
    # 1. Get Model Path
    settings = get_settings()
    model_path = settings.model.text_path
    
    if not model_path:
        print("Error: settings.model.text_path is not set!")
        return
        
    # Handle relative paths
    if not os.path.isabs(model_path):
        model_path = str(project_root / model_path)
        
    print(f"Target Model: {model_path}")
    if not os.path.exists(model_path):
        print(f"Error: Model file not found at {model_path}")
        return

    # 2. Import Llama
    # Set CUDA environment variables BEFORE importing llama_cpp
    os.environ["GGML_CUDA_FORCE_MMQ"] = "0" 
    os.environ["GGML_CUDA_NO_GRAPHS"] = "1"
    os.environ["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = "0" # Force use of first GPU

    print("Importing llama_cpp...")
    try:
        from llama_cpp import Llama
    except ImportError:
        print("Error: llama-cpp-python not installed. Run 'pip install llama-cpp-python'")
        return

    # 3. Measure Load Time
    print("\n--- Phase 1: Model Loading ---")
    
    start_load = time.time()
    
    # Use settings similar to what the core uses (from my research)
    # n_gpu_layers = settings.model.n_gpu_layers if hasattr(settings.model, 'n_gpu_layers') else -1
    n_gpu_layers = 0 # Reduce layers to 0 for safe mode test
    n_ctx = 2048 # Reduce context window
    n_threads = 8 # Attempt to optimize CPU threads
    
    # Cap n_ctx for safety during test
    if n_ctx > 2048:
        n_ctx = 2048
        
    print(f"Config: n_gpu_layers={n_gpu_layers}, n_ctx={n_ctx}, n_threads={n_threads}")
    
    try:
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=32, # Increase batch size slightly for CPU
            n_ubatch=32, # Set ubatch to batch
            verbose=True, # Enable verbose to check for BLAS/CUDA
            use_mmap=True, # Re-enable mmap for speed
            use_mlock=False
        )
    except Exception as e:
        print(f"Failed to load model: {e}")
        return
        
    load_time = time.time() - start_load
    print(f"Model Loaded in: {load_time:.2f} seconds")

    # 4. Measure Generation Time
    print("\n--- Phase 2: Generation Test ---")
    prompt = "你好，请做个简单的自我介绍。"
    print(f"Prompt: {prompt}")
    
    start_gen = time.time()
    
    # Simple generation
    output = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        stream=False
    )
    
    gen_time = time.time() - start_gen
    
    response_text = output['choices'][0]['message']['content']
    token_count = output['usage']['completion_tokens']
    
    print(f"\nResponse: {response_text}")
    print("-" * 30)
    print(f"Generation Time: {gen_time:.2f} seconds")
    print(f"Tokens Generated: {token_count}")
    print(f"Speed: {token_count / gen_time:.2f} tokens/second")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_performance()
