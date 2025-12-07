import logging
import asyncio
import torch
from PIL import Image
from typing import Dict, Any
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from domain.interfaces.base_interfaces import VisionInterface

logger = logging.getLogger("VLAdapter")

class VLAdapter(VisionInterface):
    def __init__(self, model_path: str, device: str = "cuda"):
        self.model_path = model_path
        self.device = device
        self.model = None
        self.processor = None
        self._lock = asyncio.Lock()
        
    async def _ensure_loaded(self):
        if self.model is None:
            await self._load_model()
            
    async def _load_model(self):
        logger.info(f"Loading VL Model from {self.model_path}")
        try:
            def load():
                # Load model
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self.model_path,
                    torch_dtype=torch.float16 if self.device == "cuda" else "auto",
                    device_map="auto" if self.device == "cuda" else None
                )
                processor = AutoProcessor.from_pretrained(self.model_path)
                return model, processor
                
            self.model, self.processor = await asyncio.to_thread(load)
            logger.info("VL Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load VL model: {e}")
            raise

    async def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        async with self._lock:
            await self._ensure_loaded()
            
            def run_inference():
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "image": image_path,
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ]
                
                # Preparation for inference
                text = self.processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                image_inputs, video_inputs = process_vision_info(messages)
                inputs = self.processor(
                    text=[text],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt",
                )
                inputs = inputs.to(self.model.device)

                # Inference: Generation of the output
                generated_ids = self.model.generate(**inputs, max_new_tokens=128)
                generated_ids_trimmed = [
                    out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
                ]
                output_text = self.processor.batch_decode(
                    generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
                )
                return output_text[0]

            return await asyncio.to_thread(run_inference)
