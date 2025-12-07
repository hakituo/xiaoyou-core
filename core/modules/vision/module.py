import os
import gc
import asyncio
from typing import Optional, Dict, Any
from config.integrated_config import get_settings
from core.utils.logger import get_logger

# 配置日志
logger = get_logger("VISION_MODULE")

class VisionModule:
    """
    视觉模块，负责处理图像理解和分析任务。
    封装了视觉模型的加载和推理逻辑。
    """
    def __init__(self, config=None):
        """
        初始化视觉模块
        
        Args:
            config: 模块配置字典 (已弃用，优先使用 integrated_config)
        """
        self.settings = get_settings()
        self.config = config or {}
        
        # 优先从 integrated_config 获取路径
        self.vision_model_path = self.settings.model.vision_path
        if not self.vision_model_path:
             # 尝试从旧配置获取
             self.vision_model_path = self.config.get("vision_model_path")
        
        self.device = self.settings.model.device
        
        self.model = None
        self.tokenizer = None
        self.is_loaded = False
        self._lock = asyncio.Lock()
        
    async def _load_model(self):
        """
        加载视觉模型和分词器 (异步包装)
        """
        if not self.vision_model_path:
            logger.error("视觉模型路径未配置")
            return False
            
        return await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self):
        """
        加载视觉模型和分词器 (同步实现)
        """
        try:
            # 延迟导入重型库
            import torch
            from transformers import AutoModelForVision2Seq, AutoTokenizer
            
            # 自动选择设备
            if self.device == "auto" or not self.device:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info(f"正在加载视觉模型: {self.vision_model_path} (Device: {self.device})")
            
            if not os.path.exists(self.vision_model_path):
                logger.error(f"模型路径不存在: {self.vision_model_path}")
                return False
                
            model_kwargs = {
                "low_cpu_mem_usage": True,
                "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
                "local_files_only": True
            }
            
            if self.device == "cuda":
                model_kwargs["device_map"] = "auto"
                
            self.tokenizer = AutoTokenizer.from_pretrained(self.vision_model_path, local_files_only=True, trust_remote_code=True)
            self.model = AutoModelForVision2Seq.from_pretrained(self.vision_model_path, trust_remote_code=True, **model_kwargs)
            
            if self.device != "cuda" or not model_kwargs.get("device_map"):
                self.model = self.model.to(self.device)
                
            self.is_loaded = True
            logger.info("视觉模型加载成功")
            return True
            
        except ImportError as e:
            logger.error(f"缺少必要的依赖库: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"加载视觉模型失败: {str(e)}")
            return False
            
    async def unload_model(self):
        """卸载模型释放资源"""
        async with self._lock:
            if self.model:
                del self.model
                self.model = None
            if self.tokenizer:
                del self.tokenizer
                self.tokenizer = None
                
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
                
            gc.collect()
            self.is_loaded = False
            logger.info("视觉模型已卸载")

    async def describe_image(self, image, prompt=None):
        """
        使用视觉模型描述图像
        
        Args:
            image: PIL Image对象或图像路径
            prompt: 可选的提示文本
            
        Returns:
            包含状态和描述的字典
        """
        async with self._lock:
            try:
                if not self.is_loaded:
                    success = await self._load_model()
                    if not success:
                        return {"status": "error", "error": "模型加载失败"}

                if prompt is None:
                    prompt = "描述这张图片的内容"
                    
                # 延迟导入PIL
                from PIL import Image
                    
                # 处理图像输入
                if isinstance(image, str):
                    if not os.path.exists(image):
                        return {"status": "error", "error": f"图像文件不存在: {image}"}
                    # 异步读取图片
                    image = await asyncio.to_thread(lambda: Image.open(image).convert("RGB"))
                elif not isinstance(image, Image.Image):
                    return {"status": "error", "error": "无效的图像输入"}
                    
                # 异步执行推理
                return await asyncio.to_thread(self._inference_sync, image, prompt)
                
            except Exception as e:
                logger.error(f"描述图像时出错: {str(e)}")
                return {"status": "error", "error": str(e)}

    def _inference_sync(self, image, prompt):
        """同步推理逻辑"""
        try:
            import torch
            
            # 针对 Qwen-VL 的处理
            if hasattr(self.tokenizer, 'from_list_format'):
                inputs = self.tokenizer.from_list_format([
                    {'image': image},
                    {'text': prompt},
                ], return_tensors='pt').to(self.model.device)
            else:
                # 通用处理 (可能需要根据模型调整)
                inputs = self.tokenizer(images=image, text=prompt, return_tensors="pt").to(self.model.device)

            with torch.no_grad():
                output = self.model.generate(**inputs, max_new_tokens=512)
                
            response = self.tokenizer.decode(output[0], skip_special_tokens=True)
            
            return {
                "status": "success",
                "response": response
            }
        except Exception as e:
            logger.error(f"推理失败: {e}")
            raise

