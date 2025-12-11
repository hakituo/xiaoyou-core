import sys
import os
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.modules.llm.module import LLMModule

async def main():
    print("Initializing LLMModule with GGUF model...")
    
    model_path = r"D:\AI\xiaoyou-core\models\llm\Qwen2___5-7B-Instruct-Q4_K_M.gguf"
    
    if not os.path.exists(model_path):
        print(f"Error: Model path does not exist: {model_path}")
        return

    config = {
        "text_model_path": model_path,
        "n_gpu_layers": -1, # Use GPU if available
        "n_ctx": 4096
    }
    
    llm = LLMModule(config=config)
    
    # Check if llama_cpp is installed
    try:
        import llama_cpp
        print(f"llama_cpp version: {llama_cpp.__version__}")
    except ImportError:
        print("Error: llama_cpp is not installed!")
        return

    print("Loading model (this might take a moment)...")
    # chat() method handles loading automatically if not loaded
    
    prompt = "你好，请用一句话介绍你自己。"
    print(f"Sending prompt: {prompt}")
    
    result = await llm.chat(prompt, max_tokens=100, temperature=0.7)
    
    if result.get("status") == "success":
        print("\n--- Response ---")
        print(result.get("response"))
        print("----------------\n")
        print("Verification SUCCESS: GGUF model loaded and generated text.")
    else:
        print(f"Verification FAILED: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
