# Import local model adapter
from core.model_adapter import ModelAdapter
import logging
from PIL import Image
import os

# 配置日志
logger = logging.getLogger(__name__)

class QianwenModel:
    """
    完整功能模型类，支持文本生成、图像描述和图像生成。
    使用本地模型替代外部API调用，提供完整的多模态功能。
    """
    def __init__(self, config=None):
        """
        初始化模型类
        
        Args:
            config: 包含各种模型路径和参数的配置字典
        """
        # 使用配置初始化模型适配器，包含所有模态模型路径
        self.config = config or {
            "device": "auto",  # 自动选择设备
            "text_model_path": "./models/qwen",  # 文本模型路径
            "vision_model_path": "./models/Qwen2-VL-7B-Instruct/qwen",  # 视觉模型路径
            "image_gen_model_path": "./models/sd"  # 图像生成模型路径
        }
        
        # 初始化模型适配器
        self.model_adapter = ModelAdapter(self.config)
        logger.info("多模态模型适配器初始化完成")
        
        # 默认AI个性：Xiaoyou - 友好的AI助手
        self.system_prompt = {
            "role": "system",
            "content": "You are Xiaoyou, a friendly, intelligent, and patient AI assistant. You always answer users' questions in natural, friendly language, help users solve problems, and maintain a positive and optimistic attitude."
        }

    def set_personality(self, personality_prompt: str):
        """
        设置AI个性/角色提示
        
        Args:
            personality_prompt: 描述AI角色的提示文本
        """
        self.system_prompt = {
            "role": "system",
            "content": personality_prompt
        }
        logger.info(f"AI个性已更新: {personality_prompt[:50]}...")
    
    def generate(self, messages: list) -> str:
        """
        使用本地模型生成文本响应
        
        Args:
            messages: 消息列表，包含对话历史
            
        Returns:
            生成的文本响应
        """
        try:
            # 添加系统提示到消息列表开头
            full_messages = [self.system_prompt] + messages
            
            # 转换消息格式为模型期望的格式
            prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in full_messages])
            
            # 使用本地模型生成响应
            response_obj = self.model_adapter.chat(prompt)
            
            if response_obj.get("status") == "success":
                return response_obj.get("response", "")
            else:
                error_msg = response_obj.get("error", "生成失败")
                logger.error(f"模型生成错误: {error_msg}")
                return f"生成错误: {error_msg}"

        except Exception as e:
            logger.error(f"模型生成异常: {str(e)}")
            return f"错误: {str(e)}"
    
    def describe_image(self, image_path: str, prompt: str = None) -> str:
        """
        使用视觉模型描述图像
        
        Args:
            image_path: 图像文件路径
            prompt: 可选的描述提示
            
        Returns:
            图像描述文本
        """
        try:
            # 验证图像文件是否存在
            if not os.path.exists(image_path):
                return f"错误: 图像文件不存在: {image_path}"
            
            # 如果没有提供提示，使用默认提示
            if prompt is None:
                prompt = "详细描述这张图片中的内容"
            
            logger.info(f"开始描述图像: {image_path}")
            
            # 使用模型适配器描述图像
            response_obj = self.model_adapter.describe_image(
                image=image_path,
                prompt=prompt
            )
            
            if response_obj.get("status") == "success":
                return response_obj.get("response", "")
            else:
                error_msg = response_obj.get("error", "描述失败")
                logger.error(f"图像描述错误: {error_msg}")
                return f"描述错误: {error_msg}"
                
        except Exception as e:
            logger.error(f"图像描述异常: {str(e)}")
            return f"错误: {str(e)}"
    
    def generate_image(self, prompt: str, save_path: str = "./output.png", 
                      negative_prompt: str = None, 
                      height: int = 512, width: int = 512) -> str:
        """
        使用图像生成模型从文本提示创建图像
        
        Args:
            prompt: 图像生成的文本提示
            save_path: 保存生成图像的路径
            negative_prompt: 可选的负面提示
            height: 图像高度
            width: 图像宽度
            
        Returns:
            生成结果信息，成功时返回图像保存路径
        """
        try:
            logger.info(f"开始生成图像: {prompt[:50]}...")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            
            # 使用模型适配器生成图像
            response_obj = self.model_adapter.generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=height,
                width=width
            )
            
            if response_obj.get("status") == "success":
                # 获取生成的图像
                image = response_obj.get("image")
                if image:
                    # 保存图像
                    image.save(save_path)
                    logger.info(f"图像生成成功并保存至: {save_path}")
                    return f"图像生成成功，已保存至: {save_path}"
                else:
                    return "错误: 生成的图像为空"
            else:
                error_msg = response_obj.get("error", "生成失败")
                logger.error(f"图像生成错误: {error_msg}")
                return f"生成错误: {error_msg}"
                
        except Exception as e:
            logger.error(f"图像生成异常: {str(e)}")
            return f"错误: {str(e)}"
    
    def process_multimodal_request(self, request_type: str, **kwargs) -> str:
        """
        处理多模态请求的统一接口
        
        Args:
            request_type: 请求类型 ('text', 'image_description', 'image_generation')
            **kwargs: 特定请求类型的参数
            
        Returns:
            处理结果
        """
        if request_type == "text":
            messages = kwargs.get("messages", [])
            return self.generate(messages)
        elif request_type == "image_description":
            image_path = kwargs.get("image_path")
            prompt = kwargs.get("prompt")
            return self.describe_image(image_path, prompt)
        elif request_type == "image_generation":
            prompt = kwargs.get("prompt")
            save_path = kwargs.get("save_path", "./output.png")
            negative_prompt = kwargs.get("negative_prompt")
            height = kwargs.get("height", 512)
            width = kwargs.get("width", 512)
            return self.generate_image(prompt, save_path, negative_prompt, height, width)
        else:
            return f"错误: 不支持的请求类型: {request_type}"