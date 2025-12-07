
import asyncio
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from core.modules.image.module import ImageModule

async def main():
    print("Initializing ImageModule...")
    output_dir = r"D:\AI\xiaoyou-core\output\img"
    os.makedirs(output_dir, exist_ok=True)
    
    module = ImageModule()
    
    # 确保是 Pony 模型
    if "pony" not in str(module.image_gen_model_path).lower():
         print("Switching to Pony model...")
         module.switch_model("pony")
    
    # 这里我们故意不写 Pony 的前缀，测试是否会自动添加
    # 只写核心内容
    prompt = "source_anime, 1girl, solo, cute, smile, long hair, silver hair, blue eyes, school uniform, outdoors, cherry blossoms"
    
    # 简单的负面提示词，测试是否会追加 Pony 的负面前缀
    negative_prompt = "ugly, blurry, low quality, bad anatomy"
    
    print(f"Input Prompt: {prompt}")
    print(f"Input Negative Prompt: {negative_prompt}")
    print("Starting generation (Auto Prefix Test)...")
    
    result = await module.generate_image(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=1024,
        height=1024,
        num_inference_steps=28,
        guidance_scale=7.0
    )
    
    if result.get("status") == "success":
        image = result["image"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pony_auto_prefix_test_{timestamp}.png"
        save_path = os.path.join(output_dir, filename)
        image.save(save_path)
        print(f"Success! Image saved to: {save_path}")
    else:
        print(f"Failed: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
