#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉语言模型适配器
专门用于处理视觉语言任务，如图像描述、视觉问答等
"""

import os
import logging
import torch
from typing import Dict, Optional, Any, Union
from PIL import Image

from .utils.base_adapter import BaseAdapter
from .core_engine.model_manager import get_model_manager

logger = logging.getLogger(__name__)


class VLModelAdapter(BaseAdapter):
    """
    视觉语言模型适配器
    处理图像描述、视觉问答等多模态任务
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 获取项目根目录
        # core/vl_model_adapter.py -> core -> xiaoyou-core
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(project_root, 'models')
        
        # 默认查找 Qwen2-VL-2B (支持 Instruct 版本)
        candidate_paths = [
            os.path.join(models_dir, 'vision', 'Qwen2-VL-2B'),
            os.path.join(models_dir, 'Qwen2-VL-2B'),
            os.path.join(models_dir, 'vision', 'Qwen2-VL-2B-Instruct'),
            os.path.join(models_dir, 'Qwen2-VL-2B-Instruct')
        ]
        
        default_model_path = candidate_paths[0]
        for path in candidate_paths:
            if os.path.exists(path):
                default_model_path = path
                break

        # 默认配置
        default_config = {
            'model_type': 'qwen2-vl',  # 默认为 Qwen2-VL
            'vl_model_path': default_model_path,
            'device': 'auto',
            'quantization': {
                'enabled': True,
                'load_in_8bit': False,
                'load_in_4bit': True,
                'torch_dtype': torch.float16 if torch.cuda.is_available() else torch.float32
            },
            'timeout': 60,
            'max_retries': 3
        }
        
        # 合并配置
        self.config = default_config.copy()
        if config:
            self.config.update(config)
        
        # 设置模型类型
        self._model_type = self.config['model_type']
        
        # 设置模型名称
        model_name = f"vl_{self._model_type}_{hash(self.config['vl_model_path'])}" if self.config['vl_model_path'] else f"vl_{self._model_type}"
        
        # 调用父类初始化
        super().__init__(get_model_manager(), 'vl', model_name)
        
        # 注册模型到管理器
        self._register_model()

    def _register_model(self):
        """注册模型到模型管理器"""
        try:
            if self.config['vl_model_path']:
                self.model_manager.register_model(
                    model_name=self._model_name,
                    model_type='vl',
                    model_path=self.config['vl_model_path']
                )
            logger.info(f"视觉语言模型已注册: {self._model_name}")
        except Exception as e:
            logger.error(f"注册视觉语言模型失败: {str(e)}")

    def _prepare_model_load_params(self) -> Dict[str, Any]:
        """
        准备模型加载参数
        
        Returns:
            Dict: 模型加载参数
        """
        # 准备加载参数
        load_kwargs = {
            'device': self.config['device'],
            'torch_dtype': self.config['quantization']['torch_dtype'],
            'quantized': self.config['quantization']['enabled'],
            'quantization_config': {
                'load_in_8bit': self.config['quantization']['load_in_8bit'],
                'load_in_4bit': self.config['quantization']['load_in_4bit']
            },
            'model_kwargs': {}
        }
        
        # 添加量化参数
        if self.config['quantization']['load_in_8bit']:
            load_kwargs['model_kwargs']['load_in_8bit'] = True
        elif self.config['quantization']['load_in_4bit']:
            load_kwargs['model_kwargs']['load_in_4bit'] = True
            
        return load_kwargs
        
    def load_model(self) -> bool:
        """
        加载视觉语言模型
        
        Returns:
            bool: 是否加载成功
        """
        try:
            # 根据模型类型加载相应的模型和processor
            if self._model_type == 'blip':
                return self._load_blip_model()
            elif self._model_type == 'qwen2-vl' or 'qwen' in self._model_type.lower():
                return self._load_qwen_model()
            else:
                # 其他模型类型的处理
                logger.warning(f"暂不支持的VL模型类型: {self._model_type}")
                return False
        except Exception as e:
            logger.error(f"加载视觉语言模型时出错: {str(e)}")
            return False

    def _load_qwen_model(self) -> bool:
        """
        加载Qwen2-VL模型
        """
        try:
            # 准备加载参数
            load_kwargs = self._prepare_model_load_params()
            
            # 调用ModelManager加载
            # ModelManager已经内置了对Qwen2-VL的支持（通过_load_llm_model）
            model = self.model_manager.load_model(self._model_name, **load_kwargs)
            
            if model:
                # 获取processor (在ModelManager中存储为tokenizer_obj)
                processor = self.model_manager.get_tokenizer(self._model_name)
                if processor:
                    self.model_manager.set_processor(self._model_name, processor)
                
                self._is_loaded = True
                logger.info(f"Qwen2-VL模型加载成功: {self._model_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"加载Qwen2-VL模型时出错: {str(e)}")
            return False

    def _load_blip_model(self) -> bool:
        """
        加载BLIP模型
        
        Returns:
            bool: 是否加载成功
        """
        try:
            from transformers import BlipProcessor, BlipForConditionalGeneration
            
            # 加载processor和模型
            processor = BlipProcessor.from_pretrained(self.config['vl_model_path'])
            model = BlipForConditionalGeneration.from_pretrained(
                self.config['vl_model_path'],
                torch_dtype=self.config['quantization']['torch_dtype']
            )
            
            # 将模型和processor存储到模型管理器中
            self.model_manager.set_model(self._model_name, model)
            self.model_manager.set_processor(self._model_name, processor)
            
            self._is_loaded = True
            logger.info(f"BLIP模型加载成功: {self._model_name}")
            return True
        except Exception as e:
            logger.error(f"加载BLIP模型时出错: {str(e)}")
            return False

    def describe_image(self, 
                      image: Union[Image.Image, str], 
                      prompt: Optional[str] = None, 
                      max_tokens: int = 512) -> Dict[str, Any]:
        """
        使用视觉语言模型描述图像
        
        Args:
            image: PIL Image对象或图像路径
            prompt: 可选的提示文本
            max_tokens: 生成的最大token数
            
        Returns:
            包含状态和描述的字典
        """
        try:
            # 验证参数
            if not image:
                return {"status": "error", "error": "无效的图像输入"}
            
            # 使用默认提示如果没有提供
            if prompt is None:
                prompt = "Describe this image in detail."
            
            # 确保模型已加载
            if not self._ensure_model_loaded():
                if not self.load_model():
                    return {"status": "error", "error": "模型加载失败"}
            
            # 处理图像输入
            processed_image = self._process_image_input(image)
            if isinstance(processed_image, dict) and "error" in processed_image:
                return processed_image
            
            # 根据模型类型调用不同的描述方法
            if self._model_type == 'blip':
                description = self._describe_with_blip(processed_image, prompt, max_tokens)
            elif self._model_type == 'qwen2-vl' or 'qwen' in self._model_type.lower():
                description = self._describe_with_qwen(processed_image, prompt, max_tokens)
            else:
                # 其他模型类型的处理
                description = self._generic_vl_processing(processed_image, prompt, max_tokens)
            
            return {"status": "success", "response": description}
            
        except Exception as e:
            logger.error(f"描述图像时出错: {str(e)}")
            return {"status": "error", "error": f"错误: {str(e)}"}

    def _describe_with_qwen(self, 
                           image: Image.Image, 
                           prompt: str, 
                           max_tokens: int) -> str:
        """
        使用Qwen2-VL模型描述图像
        """
        try:
            # 获取模型和processor
            model = self.model_manager.get_model(self._model_name)
            processor = self.model_manager.get_processor(self._model_name)
            
            if not model or not processor:
                raise Exception("视觉语言模型或处理器未加载")
            
            # 准备消息
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            
            # 准备输入
            try:
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception as e:
                logger.warning(f"apply_chat_template failed: {e}")
                text = ""
            
            if not text or not text.strip():
                logger.warning("apply_chat_template returned empty, using manual prompt construction")
                # Qwen2-VL default template approximation
                text = f"<|vision_start|><|image_pad|><|vision_end|>User: {prompt}\nAssistant:"
                
            logger.info(f"Qwen2-VL Prompt Text: {text}")
            
            # 处理输入
            inputs = processor(
                text=[text],
                images=[image],
                padding=True,
                return_tensors="pt"
            )
            
            # 移动到设备
            device = next(model.parameters()).device
            inputs = inputs.to(device)
            
            # 生成
            with torch.no_grad():
                generated_ids = model.generate(**inputs, max_new_tokens=max_tokens)
            
            logger.info(f"Generated IDs shape: {generated_ids.shape}")
            logger.info(f"Input IDs shape: {inputs.input_ids.shape}")
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            output_text = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
            return output_text
            
        except Exception as e:
            logger.error(f"使用Qwen2-VL模型描述图像时出错: {str(e)}")
            return f"Error processing image with Qwen2-VL: {str(e)}"

    def _process_image_input(self, image: Union[Image.Image, str]) -> Union[Image.Image, Dict[str, str]]:
        """
        处理图像输入
        
        Args:
            image: PIL Image对象或图像路径
            
        Returns:
            处理后的PIL Image对象或错误信息
        """
        try:
            if isinstance(image, str):
                # 如果是文件路径，加载图像
                if not os.path.exists(image):
                    return {"status": "error", "error": f"图像文件不存在: {image}"}
                image = Image.open(image).convert("RGB")
            elif not isinstance(image, Image.Image):
                return {
                    "status": "error",
                    "error": "无效的图像输入，需要PIL Image对象或图像路径",
                }
            
            # 确保是RGB格式
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            return image
            
        except Exception as e:
            logger.error(f"处理图像输入时出错: {str(e)}")
            return {"status": "error", "error": f"图像处理错误: {str(e)}"}

    def _describe_with_blip(self, 
                           image: Image.Image, 
                           prompt: str, 
                           max_tokens: int) -> str:
        """
        使用BLIP模型描述图像
        """
        try:
            # 获取模型和processor
            model = self.model_manager.get_model(self._model_name)
            processor = self.model_manager.get_processor(self._model_name)
            
            if not model or not processor:
                raise Exception("视觉语言模型或处理器未加载")
            
            # 准备输入
            inputs = processor(image, prompt, return_tensors="pt")
            
            # 将输入移动到模型设备
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            
            # 生成描述
            with torch.no_grad():
                output = model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    num_beams=3,
                    temperature=0.7
                )
            
            # 解码输出
            description = processor.decode(output[0], skip_special_tokens=True)
            return description
            
        except Exception as e:
            logger.error(f"使用BLIP模型描述图像时出错: {str(e)}")
            # 回退到通用方法
            return self._generic_vl_processing(image, prompt, max_tokens)

    def _generic_vl_processing(self, 
                              image: Image.Image, 
                              prompt: str, 
                              max_tokens: int) -> str:
        """
        通用视觉语言处理方法
        """
        # 这是一个占位实现
        # 实际使用时应该使用适当的视觉语言模型处理
        width, height = image.size
        return f"Image size: {width}x{height}. Prompt: {prompt}. (Need to use appropriate vision-language model for detailed description)"

    def visual_question_answering(self, 
                                  image: Union[Image.Image, str], 
                                  question: str) -> Dict[str, Any]:
        """
        视觉问答
        
        Args:
            image: PIL Image对象或图像路径
            question: 问题文本
            
        Returns:
            包含答案的字典
        """
        try:
            # 确保模型已加载
            if not self._ensure_model_loaded():
                if not self.load_model():
                    return {"status": "error", "error": "模型加载失败"}
            
            # 处理图像输入
            processed_image = self._process_image_input(image)
            if isinstance(processed_image, dict) and "error" in processed_image:
                return processed_image
            
            # 根据模型类型调用不同的VQA方法
            if self._model_type == 'blip':
                answer = self._vqa_with_blip(processed_image, question)
            elif self._model_type == 'qwen2-vl' or 'qwen' in self._model_type.lower():
                # Qwen2-VL的处理方式与描述图像类似，只是提示词不同
                answer = self._describe_with_qwen(processed_image, question, 100)
            else:
                # 其他模型类型的处理
                answer = f"Answer to '{question}' based on the image. (Placeholder result)"
            
            return {
                "status": "success",
                "answer": answer
            }
            
        except Exception as e:
            logger.error(f"视觉问答时出错: {str(e)}")
            return {"status": "error", "error": f"错误: {str(e)}"}

    def _vqa_with_blip(self, image: Image.Image, question: str) -> str:
        """
        使用BLIP模型进行视觉问答
        """
        try:
            # 获取模型和processor
            model = self.model_manager.get_model(self._model_name)
            processor = self.model_manager.get_processor(self._model_name)
            
            if not model or not processor:
                raise Exception("视觉语言模型或处理器未加载")
            
            # 准备输入 (BLIP VQA需要特定的提示格式)
            prompt = f"Question: {question} Answer:"
            inputs = processor(image, prompt, return_tensors="pt")
            
            # 将输入移动到模型设备
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            
            # 生成回答
            with torch.no_grad():
                output = model.generate(
                    **inputs,
                    max_new_tokens=100,
                    num_beams=3,
                    temperature=0.7
                )
            
            # 解码输出
            answer = processor.decode(output[0], skip_special_tokens=True)
            # 移除提示部分，只保留回答
            if answer.startswith(prompt):
                answer = answer[len(prompt):].strip()
            return answer
            
        except Exception as e:
            logger.error(f"使用BLIP模型进行视觉问答时出错: {str(e)}")
            return f"Unable to answer the question: {question}"

    def unload(self) -> bool:
        """
        卸载模型
        
        Returns:
            bool: 是否卸载成功
        """
        try:
            if self.is_loaded:
                self.model_manager.remove_model(self._model_name)
                self.model_manager.remove_processor(self._model_name)
                self._is_loaded = False
            return True
        except Exception as e:
            logger.error(f"卸载视觉语言模型时出错: {str(e)}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            Dict: 健康状态信息
        """
        try:
            return {
                "status": "healthy",
                "model": self._model_name,
                "type": self._model_type,
                "loaded": self.is_loaded
            }
        except Exception as e:
            logger.error(f"健康检查时出错: {str(e)}")
            return {"status": "error", "error": str(e)}


def create_vl_adapter(config: Optional[Dict[str, Any]] = None) -> VLModelAdapter:
    """
    创建视觉语言模型适配器实例
    
    Args:
        config: 配置参数
        
    Returns:
        VLModelAdapter实例
    """
    return VLModelAdapter(config)