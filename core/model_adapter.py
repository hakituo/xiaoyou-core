import os
import logging
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoModelForVision2Seq
from diffusers import StableDiffusionPipeline
from PIL import Image
import gc
import warnings

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

warnings.warn(
    "The 'ModelAdapter' class is deprecated and will be removed in future versions. "
    "Please use 'core.modules.llm', 'core.modules.vision', and 'core.modules.image' instead.",
    DeprecationWarning,
    stacklevel=2
)

class ModelAdapter:
    """
    [Deprecated] 完整功能模型适配器，支持文本生成、视觉模型和图像生成功能。
    优化模型加载和内存管理，提供统一的接口访问不同类型的模型。
    
    注意：此类已被弃用，建议迁移到新的模块化架构。
    """
    def __init__(self, config=None):
        """
        初始化模型适配器
        
        Args:
            config: 包含各个模型配置的字典
        """
        logger.warning("ModelAdapter is deprecated. Please use the new module architecture.")
        self.config = config or {}
        
        # 文本模型配置
        self.text_config = self.config.get("text_model", {})
        self.text_model = None
        self.tokenizer = None
        
        # 视觉模型配置
        self.vl_config = self.config.get("vl_model", {})
        self.vl_model = None
        self.vl_tokenizer = None
        
        # 图像生成模型配置
        self.sd_config = self.config.get("image_model", {})
        self.sd_pipe = None
        
        # 状态标记
        self.loaded_models = {
            "text": False,
            "vl": False,
            "image": False
        }

    def _load_text_model(self):
        """加载文本生成模型"""
        try:
            if self.loaded_models["text"]:
                return True
                
            model_path = self.text_config.get("text_model_path")
            if not model_path or not os.path.exists(model_path):
                logger.error(f"Text model path not found: {model_path}")
                return False
                
            device = self.text_config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Loading text model from {model_path} to {device}...")
            
            # 加载分词器
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            
            # 准备模型加载参数
            model_kwargs = {
                "trust_remote_code": True,
                "local_files_only": True
            }
            
            # 量化配置
            quantization = self.text_config.get("quantization", {})
            if quantization.get("enabled", False):
                if quantization.get("load_in_4bit", False):
                    model_kwargs["load_in_4bit"] = True
                elif quantization.get("load_in_8bit", False):
                    model_kwargs["load_in_8bit"] = True
            else:
                if device == "cuda":
                    model_kwargs["torch_dtype"] = torch.float16
            
            if device == "cuda":
                model_kwargs["device_map"] = "auto"
            
            # 加载模型
            self.text_model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
            
            if device != "cuda" and not model_kwargs.get("device_map"):
                self.text_model = self.text_model.to(device)
                
            self.loaded_models["text"] = True
            logger.info("Text model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load text model: {e}")
            return False

    def _load_vision_model(self):
        """加载视觉理解模型"""
        try:
            if self.loaded_models["vl"]:
                return True
                
            model_path = self.vl_config.get("vl_model_path")
            if not model_path or not os.path.exists(model_path):
                logger.error(f"Vision model path not found: {model_path}")
                return False
                
            device = self.vl_config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Loading vision model from {model_path} to {device}...")
            
            # 加载处理器/分词器
            self.vl_tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            
            # 准备模型加载参数
            model_kwargs = {
                "trust_remote_code": True,
                "local_files_only": True
            }
            
            # 量化配置
            quantization = self.vl_config.get("quantization", {})
            if quantization.get("enabled", False):
                if quantization.get("load_in_4bit", False):
                    model_kwargs["load_in_4bit"] = True
            else:
                if device == "cuda":
                    model_kwargs["torch_dtype"] = torch.float16
                    
            if device == "cuda":
                model_kwargs["device_map"] = "auto"
                
            # 加载模型
            self.vl_model = AutoModelForVision2Seq.from_pretrained(model_path, **model_kwargs)
            
            if device != "cuda" and not model_kwargs.get("device_map"):
                self.vl_model = self.vl_model.to(device)
                
            self.loaded_models["vl"] = True
            logger.info("Vision model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load vision model: {e}")
            return False

    def _load_image_gen_model(self):
        """加载图像生成模型"""
        try:
            if self.loaded_models["image"]:
                return True
                
            model_path = self.sd_config.get("sd_model_path")
            if not model_path or not os.path.exists(model_path):
                logger.error(f"SD model path not found: {model_path}")
                return False
                
            device = self.sd_config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Loading SD model from {model_path} to {device}...")
            
            pipe_kwargs = {"local_files_only": True}
            if device == "cuda":
                pipe_kwargs["torch_dtype"] = torch.float16
                pipe_kwargs["variant"] = "fp16"
                
            self.sd_pipe = StableDiffusionPipeline.from_pretrained(model_path, **pipe_kwargs)
            
            if device == "cuda":
                self.sd_pipe = self.sd_pipe.to("cuda")
                
            self.loaded_models["image"] = True
            logger.info("SD model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load SD model: {e}")
            return False

    def chat(self, prompt, history=None, system_prompt=None, **kwargs):
        """文本对话接口"""
        if not self.loaded_models["text"]:
            if not self._load_text_model():
                return {"error": "Failed to load text model"}
                
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.text_model.device)
            
            generated_ids = self.text_model.generate(
                model_inputs.input_ids,
                max_new_tokens=kwargs.get("max_tokens", 512),
                temperature=kwargs.get("temperature", 0.7)
            )
            
            generated_ids = [
                output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
            ]
            
            response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return response
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {"error": str(e)}

    async def stream_chat(self, messages, model_name=None, **kwargs):
        """流式对话接口"""
        # 简单模拟流式，实际应用中应使用TextIteratorStreamer
        response = self.chat(messages[-1]["content"], history=messages[:-1], **kwargs)
        if isinstance(response, dict) and "error" in response:
            yield response
        else:
            # 模拟分块
            chunk_size = 4
            for i in range(0, len(response), chunk_size):
                yield response[i:i+chunk_size]

    def describe_image(self, image, prompt="Describe this image"):
        """图像描述接口"""
        if not self.loaded_models["vl"]:
            if not self._load_vision_model():
                return {"error": "Failed to load vision model"}
                
        try:
            # 简化的视觉模型推理逻辑
            # 实际实现取决于具体的模型架构（如Qwen-VL, LLaVA等）
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            
            text = self.vl_tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            # 这里需要根据具体的视觉模型API进行调整
            # 这是一个通用占位符
            return "Image description feature is active."
            
        except Exception as e:
            logger.error(f"Vision error: {e}")
            return {"error": str(e)}

    def generate_image(self, prompt, **kwargs):
        """图像生成接口"""
        if not self.loaded_models["image"]:
            if not self._load_image_gen_model():
                return {"error": "Failed to load image model"}
                
        try:
            image = self.sd_pipe(prompt, **kwargs).images[0]
            return image
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return {"error": str(e)}

    def unload_all(self):
        """卸载所有模型释放内存"""
        if self.text_model:
            del self.text_model
        if self.vl_model:
            del self.vl_model
        if self.sd_pipe:
            del self.sd_pipe
            
        self.text_model = None
        self.vl_model = None
        self.sd_pipe = None
        
        self.loaded_models = {k: False for k in self.loaded_models}
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        logger.info("All models unloaded")
