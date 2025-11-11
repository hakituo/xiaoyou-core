#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多模态调度脚本 - 针对8GB显存优化
实现文本、图像生成和语音的协同工作
"""

import os
import sys
import torch
import gc
import asyncio
from concurrent.futures import ThreadPoolExecutor
import psutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置信息
class Config:
    # 设备配置
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    GPU_MEMORY_LIMIT = 8 * 1024 * 1024 * 1024  # 8GB显存限制
    
    # 模型路径
    TEXT_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "Qwen2.5-7B-Instruct", "Qwen")
    VISION_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "Qwen2-VL-7B-Instruct", "qwen")
    IMAGE_GEN_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "FLUX.1-dev", "black-forest-labs")
    
    # 量化和优化设置
    USE_QUANTIZATION = True  # 使用量化以节省显存
    QUANTIZATION_BITS = 4    # 4-bit量化
    
    # 图像生成配置
    IMAGE_WIDTH = 512
    IMAGE_HEIGHT = 512
    IMAGE_BATCH_SIZE = 1
    
    # 语音配置
    VOICE_ON_CPU = True

# 模型管理器
class ModelManager:
    def __init__(self):
        """初始化模型管理器"""
        self.text_model = None
        self.text_tokenizer = None
        self.vision_model = None
        self.vision_processor = None
        self.image_gen_pipeline = None
        self.voice_model = None
        
        # 模型状态
        self.current_active_model = None  # 当前激活的模型类型
        self.models_loaded = {"text": False, "vision": False, "image_gen": False, "voice": False}
        
        # CPU线程池用于语音处理
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        
        print(f"🚀 模型管理器初始化完成")
        print(f"💻 设备: {Config.DEVICE}")
        if Config.DEVICE == "cuda":
            print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
            print(f"💾 显存限制: 8GB")
    
    def _clear_memory(self, keep_model_type=None):
        """清理内存和显存，保留指定类型的模型"""
        print("🧹 清理内存和显存...")
        
        # 清理不需要保留的模型
        if keep_model_type != "text":
            self.text_model = None
            self.text_tokenizer = None
            self.models_loaded["text"] = False
            
        if keep_model_type != "vision":
            self.vision_model = None
            self.vision_processor = None
            self.models_loaded["vision"] = False
            
        if keep_model_type != "image_gen":
            self.image_gen_pipeline = None
            self.models_loaded["image_gen"] = False
        
        # 语音模型始终在CPU，不需要清理
        
        # 清理GPU缓存
        torch.cuda.empty_cache()
        gc.collect()
        
        # 显示显存使用情况
        if Config.DEVICE == "cuda":
            used = torch.cuda.memory_allocated() / (1024 ** 3)
            reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            print(f"📊 显存使用: {used:.2f}GB / {reserved:.2f}GB 已保留")
    
    def _check_memory_availability(self):
        """检查显存是否足够"""
        if Config.DEVICE != "cuda":
            return True
        
        available = Config.GPU_MEMORY_LIMIT - torch.cuda.memory_allocated()
        return available > 2 * 1024 * 1024 * 1024  # 至少需要2GB可用显存
    
    def load_text_model(self):
        """加载文本模型（支持量化和CPU offload）"""
        if self.models_loaded["text"]:
            print("✅ 文本模型已加载")
            return True
        
        try:
            # 确保有足够显存
            if not self._check_memory_availability():
                self._clear_memory(keep_model_type="text")
            
            print("🔄 加载文本模型...")
            
            # 动态导入以避免不必要的依赖加载
            from transformers import AutoTokenizer, AutoModelForCausalLM
            
            # 加载tokenizer
            self.text_tokenizer = AutoTokenizer.from_pretrained(
                Config.TEXT_MODEL_PATH,
                trust_remote_code=True
            )
            
            # 准备模型配置
            model_kwargs = {
                "device_map": "auto",
                "torch_dtype": torch.float16,
                "trust_remote_code": True
            }
            
            # 添加量化配置
            if Config.USE_QUANTIZATION:
                print(f"🔍 启用{Config.QUANTIZATION_BITS}-bit量化")
                from transformers import BitsAndBytesConfig
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True if Config.QUANTIZATION_BITS == 4 else False,
                    load_in_8bit=True if Config.QUANTIZATION_BITS == 8 else False,
                    bnb_4bit_compute_dtype=torch.float16
                )
                model_kwargs["quantization_config"] = quantization_config
            
            # 加载模型
            self.text_model = AutoModelForCausalLM.from_pretrained(
                Config.TEXT_MODEL_PATH,
                **model_kwargs
            )
            
            self.models_loaded["text"] = True
            self.current_active_model = "text"
            print("✅ 文本模型加载完成")
            return True
            
        except Exception as e:
            print(f"❌ 文本模型加载失败: {str(e)}")
            return False
    
    def load_vision_model(self):
        """加载视觉模型"""
        if self.models_loaded["vision"]:
            print("✅ 视觉模型已加载")
            return True
        
        try:
            # 确保有足够显存
            if not self._check_memory_availability():
                self._clear_memory(keep_model_type="vision")
            
            print("🔄 加载视觉模型...")
            
            # 动态导入
            from transformers import AutoProcessor, AutoModelForVision2Seq
            
            self.vision_processor = AutoProcessor.from_pretrained(
                Config.VISION_MODEL_PATH,
                trust_remote_code=True
            )
            
            self.vision_model = AutoModelForVision2Seq.from_pretrained(
                Config.VISION_MODEL_PATH,
                device_map="auto",
                torch_dtype=torch.float16,
                trust_remote_code=True
            )
            
            self.models_loaded["vision"] = True
            self.current_active_model = "vision"
            print("✅ 视觉模型加载完成")
            return True
            
        except Exception as e:
            print(f"❌ 视觉模型加载失败: {str(e)}")
            return False
    
    def load_image_gen_model(self):
        """加载图像生成模型"""
        if self.models_loaded["image_gen"]:
            print("✅ 图像生成模型已加载")
            return True
        
        try:
            # 图像生成模型需要较多显存，清理其他模型
            self._clear_memory(keep_model_type="image_gen")
            
            print("🔄 加载图像生成模型...")
            
            # 动态导入
            from diffusers import AutoPipelineForText2Image
            
            # 准备配置
            pipe_kwargs = {
                "torch_dtype": torch.float16,
                "trust_remote_code": True
            }
            
            # 尝试启用xformers优化
            try:
                import xformers
                pipe_kwargs["use_xformers_memory_efficient_attention"] = True
                print("⚡ 启用xformers优化")
            except ImportError:
                print("ℹ️ xformers不可用，使用默认注意力机制")
            
            # 加载pipeline
            self.image_gen_pipeline = AutoPipelineForText2Image.from_pretrained(
                Config.IMAGE_GEN_MODEL_PATH,
                **pipe_kwargs
            )
            
            # 移动到GPU
            if Config.DEVICE == "cuda":
                self.image_gen_pipeline = self.image_gen_pipeline.to(Config.DEVICE)
            
            self.models_loaded["image_gen"] = True
            self.current_active_model = "image_gen"
            print("✅ 图像生成模型加载完成")
            return True
            
        except Exception as e:
            print(f"❌ 图像生成模型加载失败: {str(e)}")
            return False
    
    def load_voice_model(self):
        """加载语音模型（始终在CPU）"""
        if self.models_loaded["voice"]:
            print("✅ 语音模型已加载")
            return True
        
        try:
            print("🔄 加载语音模型（CPU模式）...")
            # 语音模型实现（这里是占位符，根据实际使用的语音模型修改）
            self.voice_model = "VOICE_MODEL_PLACEHOLDER"
            self.models_loaded["voice"] = True
            print("✅ 语音模型加载完成（运行在CPU上）")
            return True
            
        except Exception as e:
            print(f"❌ 语音模型加载失败: {str(e)}")
            return False
    
    async def chat(self, prompt, max_new_tokens=300):
        """文本对话接口"""
        # 加载模型
        if not self.load_text_model():
            return {"status": "error", "error": "无法加载文本模型"}
        
        try:
            # 使用线程池避免阻塞事件循环
            def _generate_text():
                with torch.no_grad():
                    inputs = self.text_tokenizer(prompt, return_tensors="pt").to(Config.DEVICE)
                    outputs = self.text_model.generate(
                        **inputs,
                        max_new_tokens=max_new_tokens,
                        temperature=0.7,
                        top_p=0.9
                    )
                    response = self.text_tokenizer.decode(outputs[0], skip_special_tokens=True)
                    
                    # 提取生成的部分
                    if response.startswith(prompt):
                        response = response[len(prompt):].strip()
                    
                    return response
            
            response = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool, _generate_text
            )
            
            return {
                "status": "success",
                "response": response,
                "model_type": "text"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "model_type": "text"
            }
    
    async def describe_image(self, image_path, prompt="描述这张图片的内容"):
        """图像描述接口"""
        # 加载模型
        if not self.load_vision_model():
            return {"status": "error", "error": "无法加载视觉模型"}
        
        try:
            from PIL import Image
            
            def _describe_image():
                with torch.no_grad():
                    # 加载图像
                    image = Image.open(image_path).convert("RGB")
                    
                    # 处理输入
                    inputs = self.vision_processor(
                        text=prompt,
                        images=image,
                        return_tensors="pt"
                    ).to(Config.DEVICE)
                    
                    # 生成描述
                    outputs = self.vision_model.generate(
                        **inputs,
                        max_new_tokens=512,
                        temperature=0.7
                    )
                    
                    # 解码输出
                    description = self.vision_processor.decode(
                        outputs[0], 
                        skip_special_tokens=True
                    )
                    
                    return description
            
            description = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool, _describe_image
            )
            
            return {
                "status": "success",
                "description": description,
                "model_type": "vision"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "model_type": "vision"
            }
    
    async def generate_image(self, prompt, save_path="output.png", width=None, height=None):
        """图像生成接口"""
        # 设置默认分辨率
        width = width or Config.IMAGE_WIDTH
        height = height or Config.IMAGE_HEIGHT
        
        # 加载模型
        if not self.load_image_gen_model():
            return {"status": "error", "error": "无法加载图像生成模型"}
        
        try:
            def _generate_image():
                # 确保输出目录存在
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                
                with torch.no_grad():
                    # 生成图像
                    image = self.image_gen_pipeline(
                        prompt=prompt,
                        width=width,
                        height=height,
                        guidance_scale=0.0,
                        num_inference_steps=4
                    ).images[0]
                    
                    # 保存图像
                    image.save(save_path)
                    return save_path
            
            image_path = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool, _generate_image
            )
            
            return {
                "status": "success",
                "image_path": image_path,
                "model_type": "image_gen"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "model_type": "image_gen"
            }
    
    async def process_voice(self, audio_path, text=None):
        """语音处理接口（运行在CPU上）"""
        # 加载模型
        if not self.load_voice_model():
            return {"status": "error", "error": "无法加载语音模型"}
        
        try:
            # 这里是语音处理的占位实现
            # 根据实际使用的语音模型（如RVC、so-vits等）修改
            def _process_voice():
                # 模拟语音处理
                # 实际实现应调用相应的语音处理库
                return "语音处理结果"
            
            result = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool, _process_voice
            )
            
            return {
                "status": "success",
                "result": result,
                "model_type": "voice"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "model_type": "voice"
            }
    
    async def process_request(self, request_data):
        """统一处理请求接口"""
        mode = request_data.get("mode", "chat")
        
        if mode == "chat":
            return await self.chat(request_data.get("prompt", ""))
        elif mode == "describe_image":
            return await self.describe_image(
                request_data.get("image_path", ""),
                request_data.get("prompt", "描述这张图片的内容")
            )
        elif mode == "generate_image":
            return await self.generate_image(
                request_data.get("prompt", ""),
                request_data.get("save_path", "output.png"),
                request_data.get("width", None),
                request_data.get("height", None)
            )
        elif mode == "process_voice":
            return await self.process_voice(
                request_data.get("audio_path", ""),
                request_data.get("text", None)
            )
        else:
            return {
                "status": "error",
                "error": f"不支持的模式: {mode}"
            }

# 资源监控
class ResourceMonitor:
    @staticmethod
    def get_system_status():
        """获取系统资源状态"""
        status = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "ram_used": psutil.virtual_memory().used / (1024 ** 3),
            "ram_total": psutil.virtual_memory().total / (1024 ** 3)
        }
        
        if torch.cuda.is_available():
            status["gpu_memory_used"] = torch.cuda.memory_allocated() / (1024 ** 3)
            status["gpu_memory_total"] = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        
        return status

# 主程序示例
async def main():
    print("""🎯 多模态调度系统 - 8GB显存优化版
🔧 核心特性：
  • 4-bit量化文本模型，显存占用降至5-6GB
  • 图像生成batch=1，低分辨率优化
  • 语音模型运行在CPU上
  • 动态显存管理和模型切换
  • 异步处理支持
""")
    
    # 创建模型管理器
    manager = ModelManager()
    
    # 打印系统状态
    print("📊 系统资源状态:")
    status = ResourceMonitor.get_system_status()
    print(f"  • CPU使用率: {status['cpu_percent']}%")
    print(f"  • 内存使用: {status['ram_used']:.2f}GB / {status['ram_total']:.2f}GB")
    if "gpu_memory_used" in status:
        print(f"  • GPU显存: {status['gpu_memory_used']:.2f}GB / {status['gpu_memory_total']:.2f}GB")
    
    print("\n💡 使用示例:")
    print("  1. 文本对话: await manager.chat('你好，请介绍一下自己')")
    print("  2. 图像描述: await manager.describe_image('image.jpg')")
    print("  3. 图像生成: await manager.generate_image('一只可爱的小猫')")
    print("  4. 语音处理: await manager.process_voice('audio.wav')")
    
    print("\n✨ 系统已就绪，可以开始使用多模态功能")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"❌ 程序运行出错: {e}")
        import traceback
        traceback.print_exc()