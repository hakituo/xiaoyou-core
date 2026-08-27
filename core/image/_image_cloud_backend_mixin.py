#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
云端图像生成后端 Mixin
负责通过 SiliconFlow 云端 API 进行图像生成。
从 image_manager.py 拆分而来，方法体保持原样。

设计说明：
    本模块为 Mixin 类，方法在 ImageManager 实例上调用，
    self 即为 ImageManager 实例，等价于把 manager 整体注入。
"""

import uuid
from typing import Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("IMAGE_MANAGER")


class _ImageCloudBackendMixin:
    """云端（SiliconFlow）图像生成后端 Mixin"""

    async def _generate_with_siliconflow(
        self,
        prompt: str,
        config,
        model_id: Optional[str],
        save_to_file: bool,
    ) -> Dict[str, Any]:
        if not self.siliconflow_client:
            return {"success": False, "error": "SiliconFlow Client not initialized"}

        # 如果配置为空则使用默认值
        width = config.width or 1024
        height = config.height or 1024
        steps = config.num_inference_steps or 30

        # 如需翻译简单提示（可选）
        # 目前直接透传

        result = await self.siliconflow_client.generate_image(
            prompt=prompt,
            negative_prompt=config.negative_prompt,
            width=width,
            height=height,
            seed=config.seed,
            num_inference_steps=steps,
        )

        if result["status"] == "success":
            # 如果save_to_file为True，下载图像
            if save_to_file:
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(result["url"]) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                                filename = f"sf_{now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
                                filepath = self._output_dir / filename
                                with open(filepath, "wb") as f:
                                    f.write(image_bytes)

                                return {
                                    "success": True,
                                    "model_used": "Kwai-Kolors/Kolors",
                                    "prompt": prompt,
                                    "image_path": str(filepath),
                                    "url": f"/output/image/{filename}",
                                    "provider": "siliconflow",
                                }
                except Exception as e:
                    logger.error(f"Failed to download SiliconFlow image: {e}")
                    # 回退到返回URL
                    return {
                        "success": True,
                        "model_used": "Kwai-Kolors/Kolors",
                        "prompt": prompt,
                        "url": result["url"],
                        "provider": "siliconflow",
                    }

            return {
                "success": True,
                "model_used": "Kwai-Kolors/Kolors",
                "prompt": prompt,
                "url": result["url"],
                "provider": "siliconflow",
            }
        else:
            return {"success": False, "error": result.get("error", "Unknown error")}
