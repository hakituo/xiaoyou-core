#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像生成配置类
从 image_manager.py 拆分而来，供 ImageManager 与外部调用方共用。
"""

from typing import Optional


class ImageGenerationConfig:
    """
    图像生成配置类
    """

    def __init__(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        lora_path: Optional[str] = None,  # 用作LoRA名称
        lora_weight: float = 0.7,
        provider: Optional[str] = None,
        **kwargs,
    ):
        self.width = width
        self.height = height
        self.num_inference_steps = num_inference_steps
        self.guidance_scale = guidance_scale
        self.seed = seed
        self.negative_prompt = negative_prompt
        self.lora_path = lora_path
        self.lora_weight = lora_weight
        self.provider = provider
        self.additional_params = kwargs
