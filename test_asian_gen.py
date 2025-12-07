
import asyncio
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from core.modules.image.module import ImageModule

async def main():
    print("Initializing ImageModule...")
    # Ensure output directory exists
    output_dir = r"D:\AI\xiaoyou-core\output\img"
    os.makedirs(output_dir, exist_ok=True)
    
    module = ImageModule()
    
    # Switch to Asian model
    print("Switching to Asian model...")
    module.switch_model("asian")
    print(f"Current model path: {module.image_gen_model_path}")
    
    # Realistic/3D prompts for ArienmixxlAsian
    prompt = "photorealistic, raw photo, 8k uhd, dslr, soft lighting, high quality, film grain, Fujifilm XT3, 1girl, solo, asian, beautiful face, detailed eyes, long black hair, white dress, garden, sunlight, looking at viewer, depth of field"
    negative_prompt = "(semi-realistic, cgi, 3d, render, sketch, cartoon, drawing, anime:1.4), text, close up, cropped, out of frame, worst quality, low quality, jpeg artifacts, ugly, duplicate, morbid, mutilated, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, blurry, dehydrated, bad anatomy, bad proportions, extra limbs, cloned face, disfigured, gross proportions, malformed limbs, missing arms, missing legs, extra arms, extra legs, fused fingers, too many fingers, long neck"
    
    print("Starting generation with Asian model...")
    start_time = datetime.now()
    
    # Using appropriate resolution for SDXL (1024x1024)
    result = await module.generate_image(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=1024,
        height=1024,
        num_inference_steps=30, # Slightly more steps for realistic details
        guidance_scale=7.0
    )
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    if result.get("status") == "success":
        image = result["image"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"asian_test_{timestamp}.png"
        save_path = os.path.join(output_dir, filename)
        image.save(save_path)
        print(f"Success! Image saved to: {save_path}")
        print(f"Generation time: {duration:.2f} seconds")
    else:
        print(f"Failed: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
