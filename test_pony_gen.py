
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
    print(f"Current model path: {module.image_gen_model_path}")
    
    # Pony specific prompt for anime style
    prompt = "score_9, score_8_up, score_7_up, source_anime, 1girl, solo, cute, smile, long hair, silver hair, blue eyes, school uniform, outdoors, cherry blossoms"
    negative_prompt = "score_4, score_5, score_6, source_furry, source_pony, source_cartoon, ugly, blurry, low quality, bad anatomy, deformity, bad hands, extra limbs"
    
    print("Starting generation with Pony model...")
    start_time = datetime.now()
    
    # Using appropriate resolution for SDXL/Pony (1024x1024 is standard for SDXL)
    result = await module.generate_image(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=1024,
        height=1024,
        num_inference_steps=28, # Pony usually needs 20-30 steps
        guidance_scale=7.0      # Pony standard CFG
    )
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    if result.get("status") == "success":
        image = result["image"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pony_test_{timestamp}.png"
        save_path = os.path.join(output_dir, filename)
        image.save(save_path)
        print(f"Success! Image saved to: {save_path}")
        print(f"Generation time: {duration:.2f} seconds")
    else:
        print(f"Failed: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
