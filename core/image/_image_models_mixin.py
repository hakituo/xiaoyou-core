#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像模型查询 Mixin
负责查询可用模型列表（Forge 动态模型 + 默认回退结构）与兼容性存根方法。
从 image_manager.py 拆分而来，方法体保持原样。

设计说明：
    本模块为 Mixin 类，方法在 ImageManager 实例上调用，
    self 即为 ImageManager 实例，等价于把 manager 整体注入。
"""

import asyncio
from typing import Any, Dict

from config.integrated_config import get_settings
from core.utils.logger import get_logger

logger = get_logger("IMAGE_MANAGER")


class _ImageModelsMixin:
    """图像模型查询 Mixin"""

    async def get_available_models(self) -> Dict[str, Any]:
        """
        Get currently available/loaded models.
        Maintains compatibility with legacy callers like llm_connector.
        """
        settings = get_settings()
        default_model = settings.model.default_image_model or "illustrious"

        # 如果可用，添加SiliconFlow模型
        models = {default_model: {"model_id": default_model, "status": "ready"}}

        if self.siliconflow_client and self.siliconflow_client.api_key:
            models["Kwai-Kolors/Kolors"] = {
                "model_id": "Kwai-Kolors/Kolors",
                "status": "cloud_ready",
            }

        return models

    async def list_models(self) -> Dict[str, Any]:
        """
        Return available models structure in a format the frontend expects.
        """
        # 默认回退结构
        res = {
            "sd1.5": {
                "checkpoints": [{"name": "ChilloutMix (Built-in)", "path": "sd1.5"}],
                "loras": [],
            },
            "sdxl": {
                "models": [
                    {"name": "Illustrious XL (Recommended)", "path": "illustrious"},
                    {"name": "NoobAI XL", "path": "noobai"},
                    {"name": "Pony Diffusion V6", "path": "pony"},
                ],
                "loras": [],
            },
        }

        if not self.forge_client:
            return res

        try:
            # 尝试从Forge获取动态模型
            # P1-1: 使用 asyncio.to_thread 替代 get_event_loop().run_in_executor
            forge_models = await asyncio.to_thread(self.forge_client.get_models)
            forge_loras = await asyncio.to_thread(self.forge_client.get_loras)

            if forge_models:
                sd15_ckpts = []
                sdxl_models = []

                for m in forge_models:
                    model_info = {
                        "name": m.get("title", m.get("model_name", "Unknown")),
                        "path": m.get("filename", m.get("model_name", "")),
                    }

                    # 启发式区分SD1.5和SDXL
                    name_lower = model_info["name"].lower()
                    if "xl" in name_lower or "pony" in name_lower:
                        sdxl_models.append(model_info)
                    else:
                        sd15_ckpts.append(model_info)

                if sd15_ckpts:
                    res["sd1.5"]["checkpoints"] = sd15_ckpts
                if sdxl_models:
                    res["sdxl"]["models"] = sdxl_models

            if forge_loras:
                sd15_loras = []
                sdxl_loras = []

                for lora in forge_loras:
                    lora_info = {
                        "name": lora.get("name", "Unknown"),
                        "path": lora.get(
                            "name", ""
                        ),  # LoRA usually uses name for triggering
                    }
                    # We don't easily know if a LoRA is for SD1.5 or SDXL from just the name
                    # Put it in both or just SD1.5 for now
                    sd15_loras.append(lora_info)
                    sdxl_loras.append(lora_info)

                if sd15_loras:
                    res["sd1.5"]["loras"] = sd15_loras
                if sdxl_loras:
                    res["sdxl"]["loras"] = sdxl_loras

        except Exception as e:
            logger.warning(f"Failed to fetch dynamic models from Forge: {e}")

        return res

    # 兼容性存根方法
    async def load_model(self, *args, **kwargs):
        logger.info("load_model called but managed by Forge now.")
        return True

    async def unload_model(self, *args, **kwargs):
        logger.info("unload_model called but managed by Forge now.")
        return True
