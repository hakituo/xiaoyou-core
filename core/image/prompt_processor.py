#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
提示词处理器
负责图像生成的提示词优化、规范化和用户交互规范
"""

import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
import asyncio

from core.utils.logger import get_logger
logger = get_logger("PROMPT_PROCESSOR")

class ImageCategory(Enum):
    """图像类别枚举"""
    PORTRAIT = "portrait"  # 人物肖像
    LANDSCAPE = "landscape"  # 风景
    ANIME = "anime"  # 动漫风格
    ABSTRACT = "abstract"  # 抽象
    PRODUCT = "product"  # 产品
    ARCHITECTURE = "architecture"  # 建筑
    ANIMAL = "animal"  # 动物
    OTHER = "other"  # 其他

class PromptProcessor:
    """
    提示词处理器类
    负责提示词的解析、优化、规范化和分类
    """
    
    def __init__(self):
        # 预定义的正面提示词修饰词库
        self.positive_modifiers = {
            "quality": [
                "best quality", "highly detailed", "masterpiece", 
                "ultra high res", "cinematic lighting"
            ],
            "artistic": [
                "professional illustration", "digital painting", 
                "sharp focus", "volumetric lighting"
            ],
            "style": {
                "realistic": ["realistic", "photorealistic"],
                "anime": ["anime style", "manga style"],
                "artistic": ["oil painting", "watercolor", "cartoon"]
            }
        }
        
        # 预定义的负面提示词库
        self.negative_prompts = [
            "low quality", "blurry", "bad anatomy", "disfigured", "poorly drawn",
            "deformed", "mutated", "ugly", "text", "watermark", "signature",
            "extra limbs", "floating limbs", "disconnected limbs", "malformed hands",
            "blurry eyes", "missing fingers", "too many fingers"
        ]
        
        # 类别关键词
        self.category_keywords = {
            ImageCategory.PORTRAIT: ["person", "man", "woman", "portrait", "face", "headshot"],
            ImageCategory.LANDSCAPE: ["landscape", "scenery", "nature", "mountain", "forest", "ocean", "sky"],
            ImageCategory.ANIME: ["anime", "manga", "otaku", "chibi", "anime style"],
            ImageCategory.ABSTRACT: ["abstract", "geometric", "pattern", "shape", "colorful"],
            ImageCategory.PRODUCT: ["product", "object", "item", "goods", "merchandise"],
            ImageCategory.ARCHITECTURE: ["building", "architecture", "house", "castle", "city"],
            ImageCategory.ANIMAL: ["animal", "dog", "cat", "horse", "bird", "fish", "wildlife"]
        }
        
        # 用户交互参数限制
        self.parameter_limits = {
            "width": {"min": 256, "max": 2048, "default": 512},
            "height": {"min": 256, "max": 2048, "default": 512},
            "num_inference_steps": {"min": 1, "max": 100, "default": 30},
            "guidance_scale": {"min": 0.1, "max": 20.0, "default": 7.5}
        }
    
    def analyze_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        分析提示词内容
        
        Args:
            prompt: 用户输入的提示词
            
        Returns:
            分析结果字典，包含类别、主要主题等信息
        """
        try:
            # 基础分析
            analysis = {
                "original_prompt": prompt,
                "length": len(prompt),
                "word_count": len(prompt.split()),
                "category": self._detect_category(prompt),
                "contains_style_guide": self._has_style_guide(prompt),
                "contains_quality_guide": self._has_quality_guide(prompt)
            }
            
            # 提取主要主题
            analysis["main_subjects"] = self._extract_main_subjects(prompt)
            
            return analysis
            
        except Exception as e:
            logger.error(f"提示词分析失败: {e}")
            # 返回基本分析结果
            return {
                "original_prompt": prompt,
                "length": len(prompt),
                "word_count": len(prompt.split()),
                "category": ImageCategory.OTHER,
                "contains_style_guide": False,
                "contains_quality_guide": False,
                "main_subjects": []
            }
    
    def optimize_prompt(self, prompt: str, category: Optional[ImageCategory] = None) -> str:
        """
        优化提示词以获得更好的生成结果
        
        Args:
            prompt: 原始提示词
            category: 图像类别（可选）
            
        Returns:
            优化后的提示词
        """
        try:
            optimized = prompt.strip()
            
            # 如果没有提供类别，自动检测
            if not category:
                category = self._detect_category(prompt)
            
            # 添加质量修饰词（如果没有）
            if not self._has_quality_guide(optimized):
                quality_modifiers = " ".join(self.positive_modifiers["quality"])[:100]  # 限制长度
                optimized = f"{quality_modifiers}, {optimized}"
            
            # 根据类别添加特定的风格修饰词
            if category != ImageCategory.OTHER and not self._has_style_guide(optimized):
                # 为不同类别选择合适的风格
                if category == ImageCategory.ANIME:
                    style_type = "anime"
                elif category in [ImageCategory.PORTRAIT, ImageCategory.LANDSCAPE, ImageCategory.ARCHITECTURE]:
                    style_type = "realistic"
                else:
                    # 对于其他类别，使用更通用的艺术风格
                    style_type = "artistic"
                
                style_modifiers = " ".join(self.positive_modifiers["style"].get(style_type, []))
                if style_modifiers:
                    optimized = f"{style_modifiers}, {optimized}"
            
            # 规范化格式
            optimized = self._normalize_prompt_format(optimized)
            
            # 限制长度
            if len(optimized) > 1000:  # SD模型通常有长度限制
                logger.warning("提示词过长，将被截断")
                optimized = optimized[:1000]
            
            return optimized
            
        except Exception as e:
            logger.error(f"提示词优化失败: {e}")
            return prompt  # 失败时返回原始提示词
    
    def generate_negative_prompt(self, original_prompt: str, custom_negative: Optional[str] = None) -> str:
        """
        生成负面提示词
        
        Args:
            original_prompt: 原始提示词
            custom_negative: 用户自定义的负面提示词（可选）
            
        Returns:
            组合后的负面提示词
        """
        try:
            # 基础负面提示词
            negative_prompts = list(self.negative_prompts)
            
            # 根据原始提示词添加特定的负面提示词
            analysis = self.analyze_prompt(original_prompt)
            
            # 对于人像，添加更多与人物相关的负面提示词
            if analysis["category"] == ImageCategory.PORTRAIT:
                portrait_negative = ["bad face", "bad eyes", "bad nose", "bad mouth", "bad proportions"]
                negative_prompts.extend(portrait_negative)
            
            # 添加用户自定义的负面提示词
            if custom_negative:
                custom_parts = [p.strip() for p in custom_negative.split(",") if p.strip()]
                negative_prompts.extend(custom_parts)
            
            # 去重并组合
            unique_negatives = list(set(negative_prompts))
            combined = ", ".join(unique_negatives)
            
            # 限制长度
            if len(combined) > 1000:
                combined = combined[:1000]
            
            return combined
            
        except Exception as e:
            logger.error(f"负面提示词生成失败: {e}")
            # 失败时返回基础负面提示词
            return ", ".join(self.negative_prompts)
    
    def validate_parameters(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        验证用户提供的参数是否符合限制
        
        Args:
            params: 包含生成参数的字典
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            for param_name, limits in self.parameter_limits.items():
                if param_name in params:
                    value = params[param_name]
                    # 类型检查
                    expected_type = int if param_name in ["width", "height", "num_inference_steps"] else float
                    if not isinstance(value, expected_type):
                        return False, f"参数 {param_name} 必须是 {expected_type.__name__} 类型"
                    
                    # 范围检查
                    if value < limits["min"] or value > limits["max"]:
                        return False, f"参数 {param_name} 必须在 {limits['min']} 到 {limits['max']} 之间"
            
            # 特殊检查：宽高比例
            if "width" in params and "height" in params:
                aspect_ratio = max(params["width"], params["height"]) / min(params["width"], params["height"])
                if aspect_ratio > 3:  # 避免过于极端的宽高比
                    return False, "宽高比例不能超过3:1"
            
            return True, None
            
        except Exception as e:
            logger.error(f"参数验证失败: {e}")
            return False, f"参数验证错误: {str(e)}"
    
    def get_default_parameters(self) -> Dict[str, Any]:
        """
        获取默认参数值
        
        Returns:
            默认参数字典
        """
        return {param: limits["default"] for param, limits in self.parameter_limits.items()}
    
    def format_prompt_for_model(self, prompt: str, negative_prompt: str, 
                               params: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化完整的模型输入
        
        Args:
            prompt: 优化后的提示词
            negative_prompt: 负面提示词
            params: 生成参数
            
        Returns:
            格式化后的模型输入
        """
        # 验证并合并默认参数
        validated_params = self.get_default_parameters()
        validated_params.update(params)
        
        # 再次验证
        is_valid, error_msg = self.validate_parameters(validated_params)
        if not is_valid:
            raise ValueError(error_msg)
        
        return {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            **validated_params
        }
    
    def _detect_category(self, prompt: str) -> ImageCategory:
        """
        检测提示词的图像类别
        """
        prompt_lower = prompt.lower()
        
        # 检查每个类别的关键词
        for category, keywords in self.category_keywords.items():
            for keyword in keywords:
                if keyword.lower() in prompt_lower:
                    return category
        
        return ImageCategory.OTHER
    
    def _has_style_guide(self, prompt: str) -> bool:
        """
        检查提示词是否包含风格指导
        """
        prompt_lower = prompt.lower()
        
        # 检查所有风格关键词
        for style_type, keywords in self.positive_modifiers["style"].items():
            for keyword in keywords:
                if keyword.lower() in prompt_lower:
                    return True
        
        return False
    
    def _has_quality_guide(self, prompt: str) -> bool:
        """
        检查提示词是否包含质量指导
        """
        prompt_lower = prompt.lower()
        
        for keyword in self.positive_modifiers["quality"]:
            if keyword.lower() in prompt_lower:
                return True
        
        return False
    
    def _extract_main_subjects(self, prompt: str) -> List[str]:
        """
        提取提示词中的主要主题
        这是一个简单实现，实际应用中可能需要更复杂的NLP处理
        """
        try:
            # 简单分词和过滤
            words = prompt.split()
            
            # 过滤常见修饰词
            modifiers = set([m.lower() for sublist in self.positive_modifiers.values() 
                           for item in (sublist if isinstance(sublist, list) else 
                                      [v for val in sublist.values() for v in val]) 
                           for m in item.split()])
            
            # 过滤标点和短词
            subjects = [word.strip(",.!?:;()[]{}'\"-") for word in words 
                       if len(word.strip(",.!?:;()[]{}'\"-")) > 2 and 
                       word.lower().strip(",.!?:;()[]{}'\"-") not in modifiers]
            
            # 去重并返回前5个
            return list(set(subjects))[:5]
            
        except Exception:
            return []
    
    def _normalize_prompt_format(self, prompt: str) -> str:
        """
        规范化提示词格式
        """
        # 移除多余的空格
        normalized = re.sub(r'\s+,\s+', ', ', prompt)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # 确保格式一致性
        if not normalized.endswith('.'):
            # 不需要句点，逗号分隔更适合SD的提示词
            pass
        
        return normalized.strip()

# 全局提示词处理器实例
_prompt_processor_instance = None
_prompt_processor_lock = asyncio.Lock()

async def get_global_prompt_processor() -> PromptProcessor:
    """
    获取全局提示词处理器实例
    """
    global _prompt_processor_instance
    async with _prompt_processor_lock:
        if _prompt_processor_instance is None:
            _prompt_processor_instance = PromptProcessor()
    return _prompt_processor_instance

# 便捷函数
async def process_image_prompt(prompt: str, **kwargs) -> Dict[str, Any]:
    """
    便捷的提示词处理函数
    
    Args:
        prompt: 用户输入的提示词
        **kwargs: 额外参数
        
    Returns:
        处理后的提示词和参数
    """
    processor = await get_global_prompt_processor()
    
    # 分析提示词
    analysis = processor.analyze_prompt(prompt)
    
    # 优化提示词
    optimized_prompt = processor.optimize_prompt(prompt, analysis["category"])
    
    # 生成负面提示词
    negative_prompt = processor.generate_negative_prompt(
        prompt, kwargs.get("custom_negative")
    )
    
    # 准备参数
    params = {
        "width": kwargs.get("width"),
        "height": kwargs.get("height"),
        "num_inference_steps": kwargs.get("num_inference_steps"),
        "guidance_scale": kwargs.get("guidance_scale"),
        "seed": kwargs.get("seed")
    }
    
    # 过滤掉None值
    params = {k: v for k, v in params.items() if v is not None}
    
    # 验证参数
    is_valid, error_msg = processor.validate_parameters(params)
    if not is_valid:
        raise ValueError(error_msg)
    
    # 格式化最终输出
    formatted_input = processor.format_prompt_for_model(
        optimized_prompt, negative_prompt, params
    )
    
    # 添加分析信息
    formatted_input["analysis"] = analysis
    
    return formatted_input

# 用户交互辅助函数
def create_user_friendly_response(result: Dict[str, Any], 
                                 success: bool = True, 
                                 error_message: Optional[str] = None) -> Dict[str, Any]:
    """
    创建用户友好的响应格式
    
    Args:
        result: 生成结果
        success: 是否成功
        error_message: 错误信息（如果有）
        
    Returns:
        用户友好的响应
    """
    response = {
        "success": success,
        "timestamp": asyncio.get_event_loop().time(),
    }
    
    if success:
        # 成功响应
        response.update({
            "image_id": result.get("image_id"),
            "prompt": result.get("prompt"),
            "width": result.get("width"),
            "height": result.get("height"),
            "generation_time": result.get("generation_time"),
            "image_path": result.get("image_path"),
            "seed": result.get("seed")
        })
    else:
        # 错误响应
        response.update({
            "error": error_message or "未知错误",
            "error_code": "IMAGE_GENERATION_FAILED"
        })
    
    return response

# 模块版本
__version__ = "1.0.0"