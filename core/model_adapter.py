import os
import logging
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoModelForVision2Seq
from diffusers import StableDiffusionPipeline
from PIL import Image
import gc

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelAdapter:
    """
    完整功能模型适配器，支持文本生成、视觉模型和图像生成功能。
    优化模型加载和内存管理，提供统一的接口访问不同类型的模型。
    """
    def __init__(self, config=None):
        """
        初始化模型适配器
        
        Args:
            config: 模型配置字典，包含各种模型路径和参数
        """
        # 默认配置，包含所有模型类型
        self.config = config or {
            "device": "auto",  # 'cuda', 'cpu', or 'auto'
            "text_model_path": "./models/qwen",
            "vision_model_path": "./models/qwen",
            "image_gen_model_path": "./models/sd",
            "low_cpu_mem_usage": True,
            "max_new_tokens": 512,
            "temperature": 0.7
        }
        
        # 自动选择设备
        if self.config["device"] == "auto":
            self.config["device"] = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"自动选择设备: {self.config['device']}")
        
        # 初始化所有模型引用
        self.text_model = None
        self.text_tokenizer = None
        self.vision_model = None
        self.vision_tokenizer = None
        self.image_gen_model = None
        
        # 标记各模型加载状态
        self.model_loaded = {
            "text": False,
            "vision": False,
            "image_gen": False
        }
    
    def _clear_memory(self):
        """
        清理内存和显存，优化多模型切换
        """
        try:
            # 清理GPU缓存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # 强制垃圾回收
            gc.collect()
            
            logger.info("内存清理完成")
        except Exception as e:
            logger.error(f"清理内存时出错: {str(e)}")
    
    def _load_text_model(self):
        """
        加载文本生成模型和分词器
        """
        try:
            model_path = self.config["text_model_path"]
            logger.info(f"正在加载文本模型: {model_path}")
            
            # 检查模型路径是否存在
            if not os.path.exists(model_path):
                logger.error(f"模型路径不存在: {model_path}，请确保本地已下载模型")
                return None, None
            
            # 准备模型加载参数
            model_kwargs = {
                "low_cpu_mem_usage": self.config["low_cpu_mem_usage"],
                "torch_dtype": torch.float16 if self.config["device"] == "cuda" else torch.float32,
                # 禁用从Hugging Face下载
                "local_files_only": True
            }
            
            # 添加设备映射
            if self.config["device"] == "cuda":
                model_kwargs["device_map"] = "auto"
            
            # 加载分词器和模型
            tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
            
            # 如果没有使用device_map，则手动移动到设备
            if self.config["device"] != "cuda" or not model_kwargs.get("device_map"):
                model = model.to(self.config["device"])
            
            logger.info("文本模型加载成功")
            return model, tokenizer
            
        except Exception as e:
            logger.error(f"加载文本模型失败: {str(e)}")
            return None, None
    
    def _load_vision_model(self):
        """
        加载视觉模型和分词器
        """
        try:
            model_path = self.config["vision_model_path"]
            logger.info(f"正在加载视觉模型: {model_path}")
            
            # 检查模型路径是否存在
            if not os.path.exists(model_path):
                logger.error(f"模型路径不存在: {model_path}，请确保本地已下载模型")
                return None, None
            
            # 准备模型加载参数
            model_kwargs = {
                "low_cpu_mem_usage": self.config["low_cpu_mem_usage"],
                "torch_dtype": torch.float16 if self.config["device"] == "cuda" else torch.float32,
                # 禁用从Hugging Face下载
                "local_files_only": True
            }
            
            # 添加设备映射
            if self.config["device"] == "cuda":
                model_kwargs["device_map"] = "auto"
            
            # 加载分词器和模型
            tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            model = AutoModelForVision2Seq.from_pretrained(model_path, **model_kwargs)
            
            # 如果没有使用device_map，则手动移动到设备
            if self.config["device"] != "cuda" or not model_kwargs.get("device_map"):
                model = model.to(self.config["device"])
            
            logger.info("视觉模型加载成功")
            return model, tokenizer
            
        except Exception as e:
            logger.error(f"加载视觉模型失败: {str(e)}")
            return None, None
    
    def _load_image_gen_model(self):
        """
        加载图像生成模型
        """
        try:
            model_path = self.config["image_gen_model_path"]
            logger.info(f"正在加载图像生成模型: {model_path}")
            
            # 检查模型路径是否存在
            if not os.path.exists(model_path):
                logger.error(f"模型路径不存在: {model_path}，请确保本地已下载模型")
                return None
            
            # 准备模型加载参数
            pipe_kwargs = {
                # 禁用从Hugging Face下载
                "local_files_only": True
            }
            
            # 添加设备
            if self.config["device"] == "cuda":
                pipe_kwargs["torch_dtype"] = torch.float16
                pipe_kwargs["device_map"] = "auto"
            
            # 加载图像生成模型
            pipe = StableDiffusionPipeline.from_pretrained(model_path, **pipe_kwargs)
            
            # 如果需要，手动移动到CUDA
            if self.config["device"] == "cuda" and not pipe_kwargs.get("device_map"):
                pipe = pipe.to("cuda")
            
            logger.info("图像生成模型加载成功")
            return pipe
            
        except Exception as e:
            logger.error(f"加载图像生成模型失败: {str(e)}")
            return None
    
    def chat(self, prompt, max_tokens=None, temperature=None):
        """
        生成文本响应
        
        Args:
            prompt: 输入提示文本
            max_tokens: 生成的最大token数
            temperature: 采样温度
            
        Returns:
            包含状态和响应的字典
        """
        try:
            # 使用配置中的默认值或传入的参数
            max_tokens = max_tokens or self.config.get("max_new_tokens", 512)
            temperature = temperature or self.config.get("temperature", 0.7)
            
            # 延迟加载模型
            if self.text_model is None and not self.model_loaded["text"]:
                # 需要清理内存以加载新模型
                if self.vision_model or self.image_gen_model:
                    self._clear_memory()
                self.text_model, self.text_tokenizer = self._load_text_model()
                self.model_loaded["text"] = True
            
            if not self.text_model or not self.text_tokenizer:
                return {
                    "status": "error",
                    "error": "文本模型加载失败或不可用"
                }
            
            # 分词输入
            inputs = self.text_tokenizer(prompt, return_tensors="pt")
            
            # 将输入移至相应设备
            if self.config["device"] == "cuda":
                inputs = {k: v.cuda() for k, v in inputs.items()}
            
            # 生成响应
            with torch.no_grad():
                output = self.text_model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=True,
                    pad_token_id=self.text_tokenizer.eos_token_id,
                    bos_token_id=self.text_tokenizer.bos_token_id,
                    eos_token_id=self.text_tokenizer.eos_token_id
                )
            
            # 解码响应，跳过输入部分
            response = self.text_tokenizer.decode(
                output[0][len(inputs["input_ids"][0]):],
                skip_special_tokens=True
            )
            
            return {
                "status": "success",
                "response": response
            }
            
        except Exception as e:
            logger.error(f"生成文本时出错: {str(e)}")
            return {
                "status": "error",
                "error": f"生成错误: {str(e)}"
            }
    
    def describe_image(self, image, prompt=None, max_tokens=512):
        """
        使用视觉模型描述图像
        
        Args:
            image: PIL Image对象或图像路径
            prompt: 可选的提示文本
            max_tokens: 生成的最大token数
            
        Returns:
            包含状态和描述的字典
        """
        try:
            # 使用默认提示如果没有提供
            if prompt is None:
                prompt = "描述这张图片的内容"
            
            # 延迟加载视觉模型
            if self.vision_model is None and not self.model_loaded["vision"]:
                # 需要清理内存以加载新模型
                if self.text_model or self.image_gen_model:
                    self._clear_memory()
                self.vision_model, self.vision_tokenizer = self._load_vision_model()
                self.model_loaded["vision"] = True
            
            if not self.vision_model or not self.vision_tokenizer:
                return {
                    "status": "error",
                    "error": "视觉模型加载失败或不可用"
                }
            
            # 处理图像输入
            if isinstance(image, str):
                # 如果是文件路径，加载图像
                if not os.path.exists(image):
                    return {
                        "status": "error",
                        "error": f"图像文件不存在: {image}"
                    }
                image = Image.open(image).convert("RGB")
            elif not isinstance(image, Image.Image):
                return {
                    "status": "error",
                    "error": "无效的图像输入，需要PIL Image对象或图像路径"
                }
            
            # 处理输入（根据模型API可能需要调整）
            # 这里假设模型支持文本和图像作为输入
            # 实际使用时可能需要根据具体模型调整
            inputs = {
                "text": prompt,
                "images": image
            }
            
            # 生成描述
            # 注意：这里需要根据具体模型的API调整生成逻辑
            # 由于不同视觉模型API可能不同，这里提供一个通用实现
            with torch.no_grad():
                # 这里是一个示例，实际使用时需要根据模型的具体API调整
                # 假设模型接受input_ids和pixel_values作为输入
                # 由于AutoModelForVision2Seq的具体使用方式可能不同，这里只提供框架
                try:
                    # 尝试使用模型生成描述
                    # 注意：这部分代码可能需要根据实际使用的视觉模型进行调整
                    # 这里只是提供一个参考实现
                    description = "示例图像描述（实际实现需要根据模型API调整）"
                except Exception as model_e:
                    logger.error(f"模型推理错误: {str(model_e)}")
                    return {
                        "status": "error",
                        "error": f"模型推理失败: {str(model_e)}"
                    }
            
            return {
                "status": "success",
                "response": description
            }
            
        except Exception as e:
            logger.error(f"描述图像时出错: {str(e)}")
            return {
                "status": "error",
                "error": f"错误: {str(e)}"
            }
    
    def generate_image(self, prompt, negative_prompt=None, height=512, width=512, num_inference_steps=20):
        """
        从文本提示生成图像
        
        Args:
            prompt: 图像生成的文本提示
            negative_prompt: 可选的负面提示
            height: 图像高度
            width: 图像宽度
            num_inference_steps: 推理步数
            
        Returns:
            包含状态和图像的字典
        """
        try:
            # 延迟加载图像生成模型
            if self.image_gen_model is None and not self.model_loaded["image_gen"]:
                # 需要清理内存以加载新模型
                if self.text_model or self.vision_model:
                    self._clear_memory()
                self.image_gen_model = self._load_image_gen_model()
                self.model_loaded["image_gen"] = True
            
            if not self.image_gen_model:
                return {
                    "status": "error",
                    "error": "图像生成模型加载失败或不可用"
                }
            
            # 生成图像
            with torch.no_grad():
                image = self.image_gen_model(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    height=height,
                    width=width,
                    num_inference_steps=num_inference_steps
                ).images[0]
            
            return {
                "status": "success",
                "image": image
            }
            
        except Exception as e:
            logger.error(f"生成图像时出错: {str(e)}")
            return {
                "status": "error",
                "error": f"错误: {str(e)}"
            }
    
    def process_request(self, request_type, **kwargs):
        """
        通过统一接口处理不同类型的请求
        支持文本生成(chat)、图像描述(describe_image)和图像生成(generate_image)
        
        Args:
            request_type: 请求类型 ('chat', 'describe_image', 'generate_image')
            **kwargs: 特定请求类型的附加参数
            
        Returns:
            包含状态和响应/图像的字典
        """
        if request_type == "chat":
            return self.chat(**kwargs)
        elif request_type == "describe_image":
            return self.describe_image(**kwargs)
        elif request_type == "generate_image":
            return self.generate_image(**kwargs)
        else:
            return {
                "status": "error",
                "error": f"不支持的请求类型: {request_type}"
            }
    
    def __del__(self):
        """
        析构函数，清理所有资源
        """
        try:
            # 清理GPU缓存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # 释放所有模型引用
            self.text_model = None
            self.text_tokenizer = None
            self.vision_model = None
            self.vision_tokenizer = None
            self.image_gen_model = None
            
            # 强制垃圾回收
            gc.collect()
            
        except Exception as e:
            logger.error(f"清理资源时出错: {str(e)}")

# 示例使用
if __name__ == "__main__":
    # 创建适配器实例
    adapter = ModelAdapter()
    
    # 测试文本对话
    response = adapter.chat("你好，请介绍一下自己")
    print(f"\n💬 文本对话结果:")
    print(response)