
import torch
from diffusers import StableDiffusionPipeline
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SD_PATH = r"D:\AI\xiaoyou-core\models\img\check_point\chilloutmix_NiPrunedFp32Fix.safetensors"

def test_sd():
    print(f"Testing SD with path: {SD_PATH}")
    
    if not torch.cuda.is_available():
        print("CUDA not available! Running on CPU.")
        device = "cpu"
    else:
        print(f"CUDA available: {torch.cuda.get_device_name(0)}")
        device = "cuda"
        
    print("Loading pipeline...")
    try:
        pipe = StableDiffusionPipeline.from_single_file(
            SD_PATH, 
            original_config_file=r"D:\AI\xiaoyou-core\models\img\check_point\v1-inference.yaml",
            torch_dtype=torch.float16 if device=="cuda" else torch.float32,
            load_safety_checker=False,
            local_files_only=True
        )
        pipe.to(device)
        print("Pipeline loaded.")
        
        # Optimization
        pipe.enable_attention_slicing()
        
        print("Generating image (4 steps)...")
        start = time.time()
        with torch.no_grad():
            # Use autocast for mixed precision
            if device == "cuda":
                with torch.cuda.amp.autocast():
                    image = pipe(
                        prompt="a cute cat", 
                        num_inference_steps=4,
                        height=512,
                        width=512
                    ).images[0]
            else:
                image = pipe(
                    prompt="a cute cat", 
                    num_inference_steps=4,
                    height=512,
                    width=512
                ).images[0]
                
        print(f"Generation complete in {time.time() - start:.2f}s")
        image.save("test_sd_output.png")
        print("Image saved to test_sd_output.png")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sd()
