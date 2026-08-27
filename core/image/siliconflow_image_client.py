#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SiliconFlow Image Client
Responsible for generating images using SiliconFlow API (Kwai-Kolors/Kolors).
"""

import os
import aiohttp
from typing import Dict, Any, Optional
from core.utils.logger import get_logger

logger = get_logger("SILICONFLOW_IMAGE")


class SiliconFlowImageClient:
    """
    Client for SiliconFlow Image Generation API
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        self.base_url = "https://api.siliconflow.cn/v1/images/generations"
        self.default_model = "Kwai-Kolors/Kolors"

        if not self.api_key:
            logger.warning(
                "SiliconFlow API Key not found for Image Client. Please set SILICONFLOW_API_KEY in .env"
            )

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate image using SiliconFlow API
        """
        if not self.api_key:
            return {"status": "error", "error": "API Key missing"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Standard OpenAI Image API format
        # Note: SiliconFlow might support extra parameters like negative_prompt
        payload = {
            "model": self.default_model,
            "prompt": prompt,
            "n": 1,
            "size": f"{width}x{height}",
        }

        # Add extra parameters if provided
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        if seed is not None:
            payload["seed"] = seed

        # Add any other kwargs
        payload.update(kwargs)

        try:
            logger.info(
                f"Sending Image Generation Request to SiliconFlow: Model={self.default_model}"
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url, json=payload, headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "data" in data and len(data["data"]) > 0:
                            image_url = data["data"][0]["url"]
                            return {
                                "status": "success",
                                "url": image_url,
                                "provider": "siliconflow",
                                "metadata": data,
                            }
                        else:
                            return {
                                "status": "error",
                                "error": "No image data returned",
                            }
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"SiliconFlow Image API Error: {response.status} - {error_text}"
                        )
                        return {
                            "status": "error",
                            "error": f"API Error: {response.status} - {error_text}",
                        }
        except Exception as e:
            logger.error(f"Image generation exception: {e}")
            return {"status": "error", "error": str(e)}
