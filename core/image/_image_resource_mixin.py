#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像生成资源协调 Mixin
负责生图期间的资源管理：GPU 占用标记、Forge 模型卸载调度、LLM 回迁 GPU 等。
从 image_manager.py 拆分而来，方法体保持原样。

设计说明：
    本模块为 Mixin 类，方法在 ImageManager 实例上调用，
    self 即为 ImageManager 实例，等价于把 manager 整体注入。
"""

import asyncio

from config.integrated_config import get_settings
from core.utils.logger import get_logger

logger = get_logger("IMAGE_MANAGER")


class _ImageResourceMixin:
    """图像生成资源协调 Mixin"""

    async def _restore_llm_gpu(self) -> bool:
        ok = False
        try:
            from core.resource_manager import get_resource_manager
            rm = get_resource_manager()
            model = rm.models.get("llm_engine")
            inst = getattr(model, "instance", None) if model else None
            restore = getattr(inst, "restore_llm_to_gpu", None) if inst else None
            if callable(restore):
                ok = bool(await asyncio.wait_for(asyncio.shield(restore()), timeout=30.0))
        except Exception:
            ok = False

        if not ok:
            try:
                from core.services.scheduler.cpp_scheduler_engine import get_scheduler_engine
                eng = get_scheduler_engine()
                if eng and getattr(eng, "enabled", False):
                    ok = bool(await eng.restore_llm_to_gpu())
            except Exception:
                ok = False

        return ok

    async def _set_image_gen_active(self, active: bool):
        try:
            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()
            rm.mark_model_loaded("image_gen_module", bool(active))
            model = rm.models.get("image_gen_module")
            if model and active:
                model.device = "GPU"
        except Exception:
            pass

    async def _begin_image_gen(self, provider: str):
        if provider not in ["forge", "comfyui"]:
            return
        async with self._image_gen_active_lock:
            await self._cancel_pending_forge_unload()
            self._image_gen_active += 1
            if self._image_gen_active == 1:
                await self._set_image_gen_active(True)

    async def _end_image_gen(self, provider: str):
        if provider not in ["forge", "comfyui"]:
            return
        async with self._image_gen_active_lock:
            self._image_gen_active = max(0, self._image_gen_active - 1)
            if self._image_gen_active == 0:
                await self._set_image_gen_active(False)

                unload_task = None
                if provider == "forge":
                    unload_task = await self._schedule_forge_unload_if_needed()

                async def _post_image_cleanup_and_restore():
                    try:
                        if unload_task is not None:
                            try:
                                await unload_task
                            except Exception:
                                pass

                        try:
                            from core.resource_manager import get_resource_manager
                            rm = get_resource_manager()
                            await asyncio.wait_for(rm.optimize_resources(), timeout=6.0)
                        except Exception:
                            pass

                        ok = await self._restore_llm_gpu()

                        if not ok:
                            logger.warning("[Image Gen] LLM 回迁 GPU 失败，准备重试")
                            for delay_s in (1.5, 3.0, 6.0):
                                try:
                                    await asyncio.sleep(float(delay_s))
                                except Exception:
                                    pass

                                try:
                                    from core.resource_manager import get_resource_manager
                                    rm = get_resource_manager()
                                    await asyncio.wait_for(rm.optimize_resources(), timeout=6.0)
                                except Exception:
                                    pass

                                ok = await self._restore_llm_gpu()
                                if ok:
                                    logger.info(
                                        "[Image Gen] LLM 回迁 GPU 重试成功 (delay=%.1fs)",
                                        float(delay_s),
                                    )
                                    break
                    except Exception:
                        return

                try:
                    from core.utils.async_tasks import spawn_bg_task
                    spawn_bg_task(_post_image_cleanup_and_restore(), name="image_cleanup_restore")
                except Exception:
                    pass

    async def _cancel_pending_forge_unload(self):
        async with self._forge_unload_lock:
            if self._forge_unload_task and (not self._forge_unload_task.done()):
                self._forge_unload_task.cancel()
                try:
                    await self._forge_unload_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            self._forge_unload_task = None

    async def _schedule_forge_unload_if_needed(self):
        try:
            settings = get_settings()
            seconds = getattr(settings.model, "forge_keep_model_loaded_seconds", 0)
            seconds = int(seconds) if seconds is not None else 0
        except Exception:
            seconds = 0

        if seconds < 0 or (not self.forge_client):
            return None

        if seconds == 0:
            try:
                ok = await asyncio.to_thread(self.forge_client.unload_model)
                logger.info("[Forge] Unload checkpoint ok=%s", bool(ok))
            except Exception as e:
                logger.warning("[Forge] Unload checkpoint failed: %s", e)
            return None

        async with self._forge_unload_lock:
            if self._forge_unload_task and (not self._forge_unload_task.done()):
                return self._forge_unload_task

            async def _do_unload():
                try:
                    if seconds > 0:
                        await asyncio.sleep(float(seconds))
                    ok = await asyncio.to_thread(self.forge_client.unload_model)
                    logger.info("[Forge] Unload checkpoint ok=%s", bool(ok))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("[Forge] Unload checkpoint failed: %s", e)

            self._forge_unload_task = asyncio.create_task(_do_unload())
            return self._forge_unload_task
