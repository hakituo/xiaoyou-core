#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ComfyUI 后端 Mixin
负责通过 ComfyUI 进行图像生成（Flux / SDXL，支持 Nunchaku 与 Lightning/Turbo/LCM 加速）。
从 image_manager.py 拆分而来，方法体保持原样。

设计说明：
    本模块为 Mixin 类，方法在 ImageManager 实例上调用，
    self 即为 ImageManager 实例，等价于把 manager 整体注入。
"""

import uuid
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("IMAGE_MANAGER")


class _ImageComfyBackendMixin:
    """ComfyUI 后端 Mixin"""

    async def _generate_with_comfy(
        self,
        prompt: str,
        config,
        model_id: Optional[str],
        save_to_file: bool,
    ) -> Dict[str, Any]:
        """
        Generate image using ComfyUI
        """
        if not self.comfy_client:
            return {"success": False, "error": "Comfy Client not initialized"}

        settings = get_settings()

        # 1. Process Prompt
        width = config.width or settings.model.image_gen_width
        height = config.height or settings.model.image_gen_height
        steps = config.num_inference_steps or settings.model.image_gen_steps
        seed = config.seed if config.seed is not None else -1

        # 2. Determine Model & Workflow
        # 如果model_id明确请求flux或nunchaku，或默认为flux
        # 如果model_id请求sdxl，或默认为sdxl（如illustrious）

        target_model = model_id or settings.model.default_image_model
        target_model_lower = target_model.lower()

        is_flux = "flux" in target_model_lower
        is_sdxl = (
            "xl" in target_model_lower
            or "sdxl" in target_model_lower
            or "illustrious" in target_model_lower
            or "pony" in target_model_lower
        )

        # 如不确定则默认SDXL，根据用户偏好
        if not is_flux and not is_sdxl:
            is_sdxl = True

        workflow = None
        use_nunchaku = False

        if is_flux:
            # 如果已配置，检查Nunchaku可用性
            if settings.model.comfy_auto_check_nunchaku:
                use_nunchaku = await self.comfy_client.check_nunchaku_availability()
                if use_nunchaku:
                    logger.info("[ComfyUI] Nunchaku acceleration enabled for Flux")
                else:
                    logger.info(
                        "[ComfyUI] Nunchaku acceleration not available, using standard Flux loader"
                    )

            workflow = self.comfy_client.build_flux_workflow(
                prompt=prompt,
                width=width,
                height=height,
                steps=steps,
                seed=seed,
                use_nunchaku=use_nunchaku,
            )
        else:
            # SDXL / 其他
            # 尝试将模型名映射为文件名，或直接传递
            # 目前，如果是"illustrious"，我们可能想映射到实际文件名（如果已知），
            # 但ComfyUI需要checkpoints文件夹中的实际文件名。
            # 假设用户提供正确的文件名或我们使用安全默认值。

            # 常见别名的简单映射
            model_filename = target_model
            if target_model == "illustrious":
                model_filename = "Illustrious-XL-v2.0.safetensors"  # 示例
            elif target_model == "pony":
                model_filename = "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"

            # 如果用户未指定扩展名，是否追加.safetensors？
            # ComfyUI通常处理宽松匹配，但完整名称更安全。
            if not model_filename.endswith(
                ".safetensors"
            ) and not model_filename.endswith(".ckpt"):
                # 只是启发式，如果用户确实指无扩展名的名称可能出错
                pass

            # --- 自动检测加速（Lightning/Turbo/LCM）---
            loras_to_use = []
            if config.lora_path:
                loras_to_use.append(config.lora_path)

            cfg_to_use = 7.0
            steps_to_use = steps
            sampler_to_use = "euler_ancestral"
            scheduler_to_use = "normal"
            acceleration_type = None

            if settings.model.comfy_auto_acceleration:
                try:
                    available_loras = await self.comfy_client.get_available_loras()
                    # 优先级 Lightning -> Turbo -> LCM
                    # 匹配"lightning"和"sdxl"（不区分大小写）

                    lightning_lora = next(
                        (
                            x
                            for x in available_loras
                            if "lightning" in x.lower() and "sdxl" in x.lower()
                        ),
                        None,
                    )
                    turbo_lora = next(
                        (
                            x
                            for x in available_loras
                            if "turbo" in x.lower() and "sdxl" in x.lower()
                        ),
                        None,
                    )
                    lcm_lora = next(
                        (
                            x
                            for x in available_loras
                            if "lcm" in x.lower() and "sdxl" in x.lower()
                        ),
                        None,
                    )

                    if lightning_lora:
                        if lightning_lora not in loras_to_use:
                            loras_to_use.append(lightning_lora)
                        acceleration_type = "lightning"
                        logger.info(
                            f"[ComfyUI] Auto-detected SDXL Lightning LoRA: {lightning_lora}. Enabling Lightning acceleration (8 steps)."
                        )
                        steps_to_use = 8
                        cfg_to_use = 1.5
                        sampler_to_use = "euler_ancestral"
                        scheduler_to_use = "sgm_uniform"
                    elif turbo_lora:
                        if turbo_lora not in loras_to_use:
                            loras_to_use.append(turbo_lora)
                        acceleration_type = "turbo"
                        logger.info(
                            f"[ComfyUI] Auto-detected SDXL Turbo LoRA: {turbo_lora}. Enabling Turbo acceleration (4 steps)."
                        )
                        steps_to_use = 4
                        cfg_to_use = 1.5
                        sampler_to_use = "euler_ancestral"
                        scheduler_to_use = "sgm_uniform"
                    elif lcm_lora:
                        if lcm_lora not in loras_to_use:
                            loras_to_use.append(lcm_lora)
                        acceleration_type = "lcm"
                        logger.info(
                            f"[ComfyUI] Auto-detected SDXL LCM LoRA: {lcm_lora}. Enabling LCM acceleration (6 steps)."
                        )
                        steps_to_use = 6
                        cfg_to_use = 1.5
                        sampler_to_use = "lcm"
                        scheduler_to_use = "sgm_uniform"
                except Exception as e:
                    logger.warning(f"Failed to auto-detect acceleration LoRAs: {e}")

            workflow = self.comfy_client.build_sdxl_workflow(
                prompt=prompt,
                negative_prompt=config.negative_prompt,
                width=width,
                height=height,
                steps=steps_to_use,
                seed=seed,
                model_name=model_filename,
                lora_names=loras_to_use if loras_to_use else None,
                cfg=cfg_to_use,
                sampler_name=sampler_to_use,
                scheduler=scheduler_to_use,
            )

        # 3. Execute
        try:
            logger.info(
                f"[Image Gen] Calling ComfyUI... Model: {target_model} (Flux={is_flux}, SDXL={is_sdxl}, Accel={acceleration_type})"
            )
            prompt_id = await self.comfy_client.queue_prompt(workflow)
            if not prompt_id:
                return {"success": False, "error": "Failed to queue prompt in ComfyUI"}

            # 等待执行
            images_data = await self.comfy_client.wait_for_execution(prompt_id)

            if not images_data:
                return {
                    "success": False,
                    "error": "ComfyUI generation returned no data",
                }

            # 5. Save/Return
            result = {
                "success": True,
                "model_used": "flux-nunchaku"
                if use_nunchaku
                else ("flux-standard" if is_flux else "sdxl"),
                "prompt": prompt,
            }

            if save_to_file:
                saved = []
                for idx, img_bytes in enumerate(images_data):
                    if not img_bytes:
                        continue

                    filename = f"comfy_{now_str('%Y%m%d_%H%M%S')}_{idx}_{uuid.uuid4().hex[:6]}.png"
                    filepath = self._output_dir / filename

                    try:
                        with open(filepath, "wb") as f:
                            f.write(img_bytes)

                        # 前端的相对路径
                        # 假设前端可通过某路由或静态服务访问output/image中的文件
                        # 本项目的标准模式似乎是返回绝对路径或相对路径
                        # 尽可能使用项目根目录的相对路径，或绝对路径

                        saved.append(
                            {
                                "image_path": str(filepath),
                                "url": f"/images/{filename}",  # 简单假设
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to save image {filename}: {e}")

                result["images"] = saved
                if saved:
                    result["image_path"] = saved[0]["image_path"]
                    result["url"] = saved[0]["url"]

            return result

        except Exception as e:
            logger.error(f"ComfyUI generation failed: {e}")
            return {"success": False, "error": str(e)}
