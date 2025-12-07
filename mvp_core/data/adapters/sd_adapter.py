import logging
import asyncio
import os
import torch
from typing import Dict, Any, Optional, Union
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
from domain.interfaces.base_interfaces import ImageGenInterface

logger = logging.getLogger("SDAdapter")

class SDAdapter(ImageGenInterface):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_path = config.get('sd_model_path')
        self.device = config.get('device', 'cuda' if torch.cuda.is_available() else 'cpu')
        self.pipe = None
        self._lock = asyncio.Lock()
        
    async def _ensure_loaded(self):
        if self.pipe is None:
            await self._load_model()
            
    async def _load_model(self):
        logger.info(f"Loading SD Model from {self.model_path}")
        try:
            # Run in thread to avoid blocking event loop
            def load():
                dtype = torch.float16 if self.device == 'cuda' else torch.float32
                pipe = StableDiffusionPipeline.from_single_file(
                    self.model_path, 
                    torch_dtype=dtype,
                    use_safetensors=True
                )
                pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
                
                if self.device == 'cuda':
                    pipe.to("cuda")
                    # Enable memory optimizations
                    pipe.enable_attention_slicing()
                    if self.config.get('generation', {}).get('low_vram_mode', False):
                        pipe.enable_model_cpu_offload()
                        
                return pipe
                
            self.pipe = await asyncio.to_thread(load)
            logger.info("SD Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load SD model: {e}")
            raise

    async def generate_image(self, prompt: str, **kwargs) -> Any:
        """
        Generates an image and returns the PIL Image object (or path if we were saving it inside, 
        but interface says return string path... wait, the interface says return path, 
        but experiment expects PIL image object or dict).
        
        Let's stick to returning a dictionary like the original adapter or just the image.
        The experiment code expects:
        res = self.ctx.sd.generate_image("A cat")
        if isinstance(res, dict) and res.get('status') == 'success' and res.get('images'): ...
        
        So I should return a dict.
        """
        async with self._lock:
            await self._ensure_loaded()
            
            width = kwargs.get('width', self.config.get('generation', {}).get('width', 512))
            height = kwargs.get('height', self.config.get('generation', {}).get('height', 512))
            steps = kwargs.get('num_inference_steps', self.config.get('generation', {}).get('num_inference_steps', 20))
            
            def run_inference():
                return self.pipe(
                    prompt,
                    negative_prompt=kwargs.get('negative_prompt', "ugly, blurry, low quality"),
                    width=width,
                    height=height,
                    num_inference_steps=steps
                ).images
            
            images = await asyncio.to_thread(run_inference)
            
            return {
                "status": "success",
                "images": images
            }
