from diffusers import StableDiffusionPipeline, DiffusionPipeline
import torch
import os
import time

# 全局模型实例
pipe = None


def load_image_model(model_path=None):
    """
    加载图像生成模型
    
    Args:
        model_path: 模型路径，如果未提供则使用默认路径
    
    Returns:
        DiffusionPipeline: 加载好的图像生成管道
    """
    global pipe
    
    # 如果模型已加载，则直接返回
    if pipe is not None:
        return pipe
    
    # 默认模型路径
    if model_path is None:
        # 尝试不同的可能路径
        possible_paths = [
            "models/stable-diffusion-v1-5",
            "models/stable-diffusion-xl-base-1.0",
            "models/runwayml/stable-diffusion-v1-5",
            "models/stabilityai/stable-diffusion-xl-base-1.0"
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                model_path = path
                break
        
        # 如果所有路径都不存在，使用一个公共的huggingface模型名称作为默认值
        if model_path is None:
            model_path = "runwayml/stable-diffusion-v1-5"
    
    print(f"Loading image generation model from: {model_path}")
    
    try:
        # 自动检测是否是SDXL模型
        if "xl" in model_path.lower():
            # 对于SDXL模型使用适当的加载方法
            pipe = DiffusionPipeline.from_pretrained(
                model_path,
                torch_dtype=torch.float16,
                use_safetensors=True,
                variant="fp16",
                device_map="auto"
            )
        else:
            # 对于标准SD模型
            pipe = StableDiffusionPipeline.from_pretrained(
                model_path,
                torch_dtype=torch.float16,
                device_map="auto"
            )
        
        # 启用模型优化
        if hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing()
        
        print("Image model loaded successfully")
        return pipe
    except Exception as e:
        print(f"Failed to load image model: {e}")
        raise


def generate_image(prompt, negative_prompt=None, width=512, height=512, guidance_scale=7.5, num_inference_steps=30):
    """
    生成图像
    
    Args:
        prompt: 文本提示词
        negative_prompt: 负面提示词
        width: 输出图像宽度
        height: 输出图像高度
        guidance_scale: 引导尺度
        num_inference_steps: 推理步数
    
    Returns:
        PIL.Image: 生成的图像
    """
    global pipe
    
    # 确保模型已加载
    if pipe is None:
        load_image_model()
    
    # 设置默认负面提示词
    if negative_prompt is None:
        negative_prompt = "low quality, blurry, distorted, ugly, bad anatomy, extra limbs"
    
    # Check for Anime/Pony requirement
    if "二次元" in prompt or "anime" in prompt.lower() or "manga" in prompt.lower():
        print("Detected Anime/2D style request. Checking for Pony model...")
        # Try to find Pony model
        pony_paths = [
            "models/sdxl/pony",
            "models/Pony_Diffusion_V6_XL",
            "models/pony"
        ]
        target_model = None
        for p in pony_paths:
            if os.path.exists(p):
                target_model = p
                break
        
        if target_model:
            # Check if we need to reload
            if pipe is None or getattr(pipe, "_model_path", "") != target_model:
                print(f"Switching to Pony model: {target_model}")
                try:
                    # Unload current pipe if needed (simple reassignment handles GC usually)
                    load_image_model(target_model)
                    # Tag pipe with path for future checks
                    pipe._model_path = target_model
                except Exception as e:
                    print(f"Failed to switch to Pony model: {e}")
        else:
            print("Pony model not found in common paths. Using current model.")

    try:
        print(f"Generating image with prompt: {prompt}")
        start_time = time.time()
        
        # 生成图像
        image = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps
        ).images[0]
        
        end_time = time.time()
        print(f"Image generated successfully in {end_time - start_time:.2f} seconds")
        
        return image
    except Exception as e:
        print(f"Error generating image: {e}")
        raise


def generate_and_save_image(prompt, output_path=None, **kwargs):
    """
    生成图像并保存到文件
    
    Args:
        prompt: 文本提示词
        output_path: 输出文件路径，如果未提供则自动生成
        **kwargs: 其他传递给generate_image的参数
    
    Returns:
        str: 保存的文件路径
    """
    # 生成图像
    image = generate_image(prompt, **kwargs)
    
    # 确定输出路径
    if output_path is None:
        # 创建输出目录
        os.makedirs("outputs/images", exist_ok=True)
        # 生成唯一的文件名
        timestamp = int(time.time())
        output_path = f"outputs/images/generated_{timestamp}.png"
    
    # 保存图像
    try:
        image.save(output_path)
        print(f"Image saved to: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error saving image: {e}")
        raise


# 示例使用
def example_image_generation():
    """
    示例图像生成函数，用于测试模型加载和生成
    """
    # 加载模型
    load_image_model()
    
    # 测试提示词
    prompt = "a cute robot assistant sitting on a desk, 4k, realistic lighting, digital art"
    
    # 生成并保存图像
    output_path = generate_and_save_image(prompt)
    print(f"Example image saved to: {output_path}")


if __name__ == "__main__":
    example_image_generation()