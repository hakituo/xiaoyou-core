#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Forge 后端 Mixin
负责 Forge (Stable Diffusion WebUI Forge) 的进程管理、就绪检查与图像生成。
从 image_manager.py 拆分而来，方法体保持原样。

设计说明：
    本模块为 Mixin 类，方法在 ImageManager 实例上调用，
    self 即为 ImageManager 实例，等价于把 manager 整体注入。
"""

import asyncio
import base64
import functools
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.time_utils import now_str
from core.image.forge_runtime import (
    ensure_forge_ready,
    is_forge_ready,
    start_forge_process,
    terminate_forge_process,
    warmup_forge_api,
)
from core.image.prompt_processor import process_image_prompt

logger = get_logger("IMAGE_MANAGER")


class _ImageForgeBackendMixin:
    """Forge 后端 Mixin：进程管理 + 图像生成"""

    async def _is_forge_ready(self) -> bool:
        return await is_forge_ready(self)

    async def _start_forge_process(self) -> bool:
        return await start_forge_process(self, get_settings, logger)

    async def _terminate_forge_process(self):
        await terminate_forge_process(self)

    async def _ensure_forge_ready(self, timeout_seconds: float) -> bool:
        return await ensure_forge_ready(self, timeout_seconds, get_settings, logger)

    async def _warmup_forge_api(self):
        await warmup_forge_api(self, logger)

    async def _generate_with_forge(
        self,
        prompt: str,
        config,
        model_id: Optional[str],
        save_to_file: bool,
    ) -> Dict[str, Any]:
        """
        Original Forge Generation Logic
        """
        if not self.forge_client:
            return {"success": False, "error": "Forge Client not initialized"}

        stage_t0 = asyncio.get_running_loop().time()

        # 1. Process Prompt (Optimization & Translation if needed)
        try:
            t0 = asyncio.get_running_loop().time()
            processed = await process_image_prompt(
                prompt,
                width=config.width,
                height=config.height,
                num_inference_steps=config.num_inference_steps,
                guidance_scale=config.guidance_scale,
                seed=config.seed,
                custom_negative=config.negative_prompt,
            )
            logger.info(
                "[Image Gen] Prompt processed in %.2fs",
                asyncio.get_running_loop().time() - t0,
            )
            final_prompt = processed.get("prompt", prompt)
            final_negative_prompt = processed.get(
                "negative_prompt", config.negative_prompt or ""
            )

            # 如果参数已优化/验证，使用处理后的参数
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
        settings = get_settings()
        default_model = settings.model.default_image_model or "illustrious"
        model_type = default_model

        # 首先检查明确的model_id
        if model_id:
            model_id_lower = str(model_id).lower()
            if ".safetensors" in model_id_lower:
                model_type = model_id
            elif "illustrious" in model_id_lower or "illu" in model_id_lower:
                model_type = "illustrious"
            elif "noob" in model_id_lower:
                model_type = "noobai"
            elif "pony" in model_id_lower:
                model_type = "pony"
            elif "sdxl" in model_id_lower:
                model_type = "sdxl"
            elif "sd1.5" in model_id_lower or "chillout" in model_id_lower:
                model_type = "sd1.5"

        # 检查config.additional_params中的样式预设
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

        additional_loras = config.additional_params.get("loras")
        if additional_loras is None:
            additional_loras = []

        num_images = config.additional_params.get("num_images")
        batch_size = config.additional_params.get("batch_size")
        timeout = config.additional_params.get("timeout")

        try:
            num_images = int(num_images) if num_images is not None else 1
        except Exception:
            num_images = 1
        if num_images < 1:
            num_images = 1

        try:
            batch_size = int(batch_size) if batch_size is not None else None
        except Exception:
            batch_size = None

        try:
            timeout = float(timeout) if timeout is not None else 300.0
        except Exception:
            timeout = 300.0

        rm = None
        try:
            from core.resource_manager import (
                get_global_resource_manager,
                ResourceType,
                ResourceState,
            )

            rm = await get_global_resource_manager()
            logger.info("[Image Gen] Preparing resources for Forge")
            t0 = asyncio.get_running_loop().time()

            await asyncio.wait_for(
                rm.prepare_for_heavy_task("image_gen"),
                timeout=min(45.0, float(timeout)),
            )

            waited = 0.0
            while waited < 12.0:
                state = rm.monitor.get_resource_state(ResourceType.GPU_MEMORY)
                if state not in (ResourceState.CRITICAL, ResourceState.EMERGENCY):
                    break
                await asyncio.sleep(0.6)
                waited += 0.6

            state = rm.monitor.get_resource_state(ResourceType.GPU_MEMORY)
            if state in (ResourceState.CRITICAL, ResourceState.EMERGENCY):
                try:
                    free_mb = getattr(rm, "_get_gpu_free_mb", lambda: None)()
                except Exception:
                    free_mb = None
                logger.warning(
                    "[Image Gen] GPU 显存压力仍然过高，拒绝触发 Forge。state=%s free_mb=%s",
                    getattr(state, "name", str(state)),
                    free_mb,
                )
                return {
                    "success": False,
                    "error": "显存仍然紧张，已拒绝触发生图：请等待 LLM/视觉让位完成，或先降低分辨率与步数",
                    "raw_error": "gpu_memory_pressure",
                }

            logger.info(
                "[Image Gen] Resource preparation finished in %.2fs",
                asyncio.get_running_loop().time() - t0,
            )
        except asyncio.TimeoutError:
            logger.warning("[Image Gen] Resource preparation timed out")
            return {
                "success": False,
                "error": "资源让位超时：显存可能仍被占用，已取消生图请求（请检查 Forge 控制台与显存占用）",
                "raw_error": "resource_prepare_timeout",
            }
        except Exception as e:
            logger.error("Failed to prepare resources: %s", e)
            return {
                "success": False,
                "error": f"资源准备失败：{e}",
                "raw_error": "resource_prepare_failed",
            }

        extra_kwargs = {}
        passthrough_keys = [
            "sampler_name",
            "scheduler",
            "enable_hr",
            "hr_scale",
            "hr_upscaler",
            "hr_second_pass_steps",
            "denoising_strength",
            "override_settings",
            "override_settings_restore_afterwards",
            "script_name",
            "script_args",
            "alwayson_scripts",
        ]
        for k in passthrough_keys:
            if (
                k in config.additional_params
                and config.additional_params.get(k) is not None
            ):
                extra_kwargs[k] = config.additional_params.get(k)

        # P1-1: 使用 asyncio.get_running_loop() 替代 get_event_loop()（在 async 函数内）
        loop = asyncio.get_running_loop()
        try:
            from core.services.scheduler.task.task_scheduler_adapter import (
                get_task_scheduler,
            )

            scheduler = get_task_scheduler()

            forge_startup_timeout = getattr(
                settings.model, "forge_startup_timeout_seconds", 180.0
            )
            if not await self._ensure_forge_ready(forge_startup_timeout):
                return {
                    "success": False,
                    "error": "Forge 未启动或尚未就绪：已尝试自动拉起，但等待超时。请检查 Forge 终端输出后重试。",
                    "raw_error": "forge_not_ready",
                }

            call_kwargs = dict(
                prompt=final_prompt,
                model_type=model_type,
                lora_name=lora_name,
                lora_weight=config.lora_weight,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                negative_prompt=final_negative_prompt,
                seed=seed,
                num_images=num_images,
                batch_size=batch_size,
                loras=additional_loras,
                request_timeout=timeout,
                **extra_kwargs,
            )

            logger.info(
                "[Image Gen] Calling Forge. model=%s size=%sx%s steps=%s timeout=%.1fs",
                model_type,
                width,
                height,
                steps,
                float(timeout or 0),
            )
            t0 = asyncio.get_running_loop().time()

            if scheduler:
                images_bytes = await scheduler.run_gpu_task(
                    self.forge_client.generate_images,
                    timeout=timeout,
                    **call_kwargs,
                )
            else:
                images_bytes = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        functools.partial(
                            self.forge_client.generate_images, **call_kwargs
                        ),
                    ),
                    timeout=float(timeout),
                )

            logger.info("[Image Gen] Forge returned. ok=%s", bool(images_bytes))
            logger.info(
                "[Image Gen] Forge call finished in %.2fs",
                asyncio.get_running_loop().time() - t0,
            )

            if not images_bytes:
                return {"success": False, "error": "Forge generation returned no data"}

            # 5. Save/Return
            result = {"success": True, "model_used": model_type, "prompt": final_prompt}

            if not isinstance(images_bytes, list):
                images_bytes = [images_bytes]

            if save_to_file:
                saved = []
                for idx, img in enumerate(images_bytes):
                    if not img:
                        continue
                    filename = f"{now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{idx + 1}.png"
                    filepath = self._output_dir / filename
                    with open(filepath, "wb") as f:
                        f.write(img)
                    saved.append(
                        {
                            "image_path": str(filepath),
                            "url": f"/output/image/{filename}",
                        }
                    )

                if not saved:
                    return {
                        "success": False,
                        "error": "Forge generation returned empty images",
                    }

                result["images"] = saved
                result["image_path"] = saved[0]["image_path"]
                result["url"] = saved[0]["url"]
                logger.info(f"Saved {len(saved)} images")
                logger.info(
                    "[Image Gen] Total pipeline time %.2fs",
                    asyncio.get_running_loop().time() - stage_t0,
                )
                return result

            encoded = []
            for img in images_bytes:
                if not img:
                    continue
                encoded.append(base64.b64encode(img).decode("utf-8"))
            if not encoded:
                return {
                    "success": False,
                    "error": "Forge generation returned empty images",
                }
            result["images"] = [{"image_data": s} for s in encoded]
            result["image_data"] = encoded[0]
            logger.info(
                "[Image Gen] Total pipeline time %.2fs",
                asyncio.get_running_loop().time() - stage_t0,
            )
            return result

        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                logger.error("[Image Gen] Forge call timed out")
                try:
                    from core.utils.async_tasks import spawn_bg_task
                    spawn_bg_task(
                        asyncio.to_thread(self.forge_client.unload_model),
                        name="forge_unload_oom",
                    )
                except Exception:
                    pass

                try:
                    if rm is not None:
                        from core.utils.async_tasks import spawn_bg_task
                        spawn_bg_task(rm.optimize_resources(), name="forge_timeout_optimize")
                except Exception:
                    pass
                return {
                    "success": False,
                    "error": "图像生成超时：Forge 长时间无响应，请检查 Forge 控制台/显存占用，或降低分辨率与步数",
                    "raw_error": "timeout",
                }

            err_str = str(e)

            if "no kernel image is available" in err_str:
                user_err = "显卡驱动或 CUDA 版本过旧，不支持当前硬件（RTX 50系列需更新 Forge 环境）"
            elif "WinError 233" in err_str or "管道的另一端上无任何进程" in err_str:
                user_err = "Forge 后端内部进程异常（WinError 233）。请重启 Forge 后端后重试，或先降低分辨率与步数。"
            elif "Forge connection error" in err_str:
                user_err = "无法连接到 Forge 后端，请检查 7860 端口是否已启动"
            else:
                user_err = f"图像生成失败: {err_str}"

            try:
                lowered = err_str.lower()
                if "out of memory" in lowered or "cuda" in lowered or "显存" in err_str:
                    from core.resource_manager import get_global_resource_manager

                    rm = await get_global_resource_manager()
                    from core.utils.async_tasks import spawn_bg_task
                    spawn_bg_task(rm.optimize_resources(), name="forge_oom_optimize")
            except Exception:
                pass

            logger.error(f"Image generation error: {err_str}")
            return {"success": False, "error": user_err, "raw_error": err_str}
