#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Image Manager
Responsible for managing image generation via Stable Diffusion WebUI Forge.
"""

import asyncio
import logging
import os
import uuid
import base64
import functools
from datetime import datetime
from typing import Dict, Any, Optional, Union
from pathlib import Path

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.modules.forge_client import ForgeClient
from core.image.prompt_processor import process_image_prompt

logger = get_logger("IMAGE_MANAGER")

class ImageGenerationConfig:
    """
    Image generation configuration class
    """
    def __init__(self,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 num_inference_steps: Optional[int] = None,
                 guidance_scale: float = 7.5,
                 seed: Optional[int] = None,
                 negative_prompt: Optional[str] = None,
                 lora_path: Optional[str] = None, # Used as LoRA name
                 lora_weight: float = 0.7,
                 **kwargs):
        settings = get_settings()
        self.width = width
        self.height = height
        self.num_inference_steps = num_inference_steps
        self.guidance_scale = guidance_scale
        self.seed = seed
        self.negative_prompt = negative_prompt
        self.lora_path = lora_path
        self.lora_weight = lora_weight
        self.additional_params = kwargs

class ImageManager:
    """
    Image Manager class
    Delegates image generation to ForgeClient.
    """
    def __init__(self):
        self._is_initialized = False
        self._lock = asyncio.Lock()
        
        settings = get_settings()
        self._output_dir = Path(settings.model.image_output_dir)
        if not self._output_dir.is_absolute():
            self._output_dir = Path.cwd() / self._output_dir
        
        self._ensure_output_dir()
        
        # Forge Client
        self.forge_client = None
        
        logger.info("Image Manager initialized (Forge Mode)")
    
    def _ensure_output_dir(self):
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Image output directory: {self._output_dir}")
        except Exception as e:
            logger.error(f"Failed to create image output directory: {e}")
    
    async def initialize(self) -> bool:
        if self._is_initialized:
            return True
        
        try:
            # Initialize ForgeClient
            # Assuming Forge is running on default port or configured one
            self.forge_client = ForgeClient(base_url="http://127.0.0.1:7860")
            
            self._is_initialized = True
            logger.info("Image Manager initialized with ForgeClient")
            return True
        except Exception as e:
            logger.error(f"Image Manager initialization failed: {e}")
            return False

    async def get_available_models(self) -> Dict[str, Any]:
        """
        Get currently available/loaded models.
        Maintains compatibility with legacy callers like llm_connector.
        """
        # Return a mock entry so callers think a model is loaded and don't try to reload endlessly,
        # or rely on load_model side effects.
        # However, llm_connector logic prefers the 'first available' if present.
        # If we return empty, it tries to load 'default_image_model' from settings.
        # Since we want to respect the settings or dynamic choice, returning empty initially 
        # might be better, but we need to track what 'load_model' was called with.
        
        # For simplicity in this Forge setup where models are always "available" (just need switching),
        # we can return the current Forge model if we knew it, or just return a placeholder.
        # But to avoid llm_connector overriding the requested model with "placeholder",
        # let's try to return what we think is the current model, or empty to force a "load" (which sets the target).
        
        # Actually, let's just return a dict containing the default model from settings
        # so llm_connector is happy and uses it.
        settings = get_settings()
        default_model = settings.model.default_image_model or "sd1.5"
        return {
            default_model: {
                "model_id": default_model,
                "status": "ready"
            }
        }
            
    async def generate_image(self,
                           prompt: str,
                           config: Optional[ImageGenerationConfig] = None,
                           model_id: Optional[str] = None,
                           save_to_file: bool = True) -> Dict[str, Any]:
        """
        Generate image using Forge
        """
        logger.info(f"[Image Gen] Prompt: {prompt[:30]}...")
        
        if not self._is_initialized:
            await self.initialize()
            
        if config is None:
            config = ImageGenerationConfig()

        # 1. Process Prompt (Optimization & Translation if needed)
        try:
            processed = await process_image_prompt(
                prompt,
                width=config.width,
                height=config.height,
                num_inference_steps=config.num_inference_steps,
                guidance_scale=config.guidance_scale,
                seed=config.seed,
                custom_negative=config.negative_prompt
            )
            final_prompt = processed.get("prompt", prompt)
            final_negative_prompt = processed.get("negative_prompt", config.negative_prompt or "")
            
            # Use processed params if they were optimized/validated
            width = processed.get("width", config.width)
            height = processed.get("height", config.height)
            steps = processed.get("num_inference_steps", config.num_inference_steps)
            cfg_scale = processed.get("guidance_scale", config.guidance_scale)
            seed = processed.get("seed", config.seed)
            
        except Exception as e:
            logger.warning(f"Prompt processing failed, using raw prompt: {e}")
            final_prompt = prompt
            final_negative_prompt = config.negative_prompt or ""
            width = config.width
            height = config.height
            steps = config.num_inference_steps
            cfg_scale = config.guidance_scale
            seed = config.seed
            
        # 2. Determine Model Type based on input or config
        # Default to sd1.5 if not specified
        model_type = "sd1.5"
        
        # Check explicit model_id first
        if model_id:
            if "sdxl" in model_id.lower():
                model_type = "sdxl"
            elif "pony" in model_id.lower():
                model_type = "pony"
            elif "sd1.5" in model_id.lower():
                model_type = "sd1.5"
        
        # Check for style preset in config.additional_params
        style_preset = config.additional_params.get("style_preset")
        if style_preset:
            if style_preset == "realistic_hq":
                model_type = "sdxl"
            elif style_preset == "anime_fast":
                model_type = "sd1.5"

        # 3. Prepare LoRA
        lora_name = None
        if config.lora_path:
            # Extract lora name from path if it's a path, or use as is
            lora_name = Path(config.lora_path).stem
            
        # 4. Execute generation in threadpool
        loop = asyncio.get_event_loop()
        try:
            image_bytes = await loop.run_in_executor(
                None,
                functools.partial(
                    self.forge_client.generate,
                    prompt=final_prompt,
                    model_type=model_type,
                    lora_name=lora_name,
                    lora_weight=config.lora_weight,
                    width=width,
                    height=height,
                    steps=steps,
                    cfg_scale=cfg_scale,
                    negative_prompt=final_negative_prompt,
                    seed=seed
                )
            )
            
            if not image_bytes:
                return {"success": False, "error": "Forge generation returned no data"}
                
            # 5. Save/Return
            result = {
                "success": True,
                "model_used": model_type,
                "prompt": final_prompt
            }
            
            if save_to_file:
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
                filepath = self._output_dir / filename
                
                with open(filepath, "wb") as f:
                    f.write(image_bytes)
                
                result["image_path"] = str(filepath)
                # Assuming standard serving path
                result["url"] = f"/output/image/{filename}" 
                logger.info(f"Image saved to {filepath}")
            else:
                result["image_data"] = base64.b64encode(image_bytes).decode('utf-8')
                
            return result

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def list_models(self) -> Dict[str, Any]:
        """
        Return available models structure.
        """
        return {
            "sd15": {"checkpoints": ["nsfw_v10 (Built-in)"], "loras": []},
            "sdxl": {"models": ["sd_xl_base_1.0 (Built-in)"], "loras": []}
        }
    
    # Stub methods for compatibility
    async def load_model(self, *args, **kwargs):
        logger.info("load_model called but managed by Forge now.")
        return True

    async def unload_model(self, *args, **kwargs):
        logger.info("unload_model called but managed by Forge now.")
        return True

_image_manager_instance = None

async def get_image_manager():
    global _image_manager_instance
    if _image_manager_instance is None:
        _image_manager_instance = ImageManager()
        await _image_manager_instance.initialize()
    return _image_manager_instance

