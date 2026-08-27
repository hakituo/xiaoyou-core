#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Image Manager（薄壳门面）
负责管理通过 Stable Diffusion WebUI Forge / ComfyUI / SiliconFlow 的图像生成。

拆分说明：
    本文件原为 1000+ 行的单体模块，已按职责拆分为多个 Mixin：
      - _image_config.py               : ImageGenerationConfig 配置类
      - _image_resource_mixin.py       : 资源协调 / GPU 切换 / Forge 卸载调度
      - _image_forge_backend_mixin.py  : Forge 后端（进程管理 + 图像生成）
      - _image_comfy_backend_mixin.py  : ComfyUI 后端
      - _image_cloud_backend_mixin.py  : SiliconFlow 云端后端
      - _image_models_mixin.py         : 模型查询与兼容性存根

    ImageManager 通过多继承 Mixin 组合所有能力，对外 API 完全兼容。
    本文件仅保留核心生命周期方法（__init__ / initialize / shutdown）
    与对外主入口（generate_image / generate_images）以及全局单例函数。

外部导入路径保持不变：
    from core.image.image_manager import ImageGenerationConfig, ImageManager
    from core.image.image_manager import get_image_manager, shutdown_image_manager_instance
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock
from core.modules.forge_client import ForgeClient
from core.modules.comfy_client import ComfyClient
from core.image.siliconflow_image_client import SiliconFlowImageClient
from core.image._image_config import ImageGenerationConfig
from core.image._image_resource_mixin import _ImageResourceMixin
from core.image._image_forge_backend_mixin import _ImageForgeBackendMixin
from core.image._image_comfy_backend_mixin import _ImageComfyBackendMixin
from core.image._image_cloud_backend_mixin import _ImageCloudBackendMixin
from core.image._image_models_mixin import _ImageModelsMixin

logger = get_logger("IMAGE_MANAGER")


class ImageManager(
    _ImageResourceMixin,
    _ImageForgeBackendMixin,
    _ImageComfyBackendMixin,
    _ImageCloudBackendMixin,
    _ImageModelsMixin,
):
    """
    图像管理器类（薄壳门面）
    将图像生成委托给ForgeClient或SiliconFlowImageClient。

    具体实现分散在各个 Mixin 中：
      - 资源协调：_ImageResourceMixin
      - Forge 后端：_ImageForgeBackendMixin
      - ComfyUI 后端：_ImageComfyBackendMixin
      - 云端后端：_ImageCloudBackendMixin
      - 模型查询：_ImageModelsMixin
    """

    def __init__(self):
        self._is_initialized = False
        # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._lock = LazyAsyncLock()
        self._image_gen_active = 0
        self._image_gen_active_lock = LazyAsyncLock()
        self._forge_api_warmup_started = False
        self._forge_start_lock = LazyAsyncLock()
        self._forge_last_start_ts = 0.0
        self._forge_unload_task = None
        self._forge_unload_lock = LazyAsyncLock()
        self._forge_process = None
        self._forge_process_pid = None
        self._forge_process_started = False
        # P1-3: 记录初始化失败原因，供健康检查/重试逻辑使用
        self.last_error: str = ""

        settings = get_settings()
        self._output_dir = Path(settings.model.image_output_dir)
        if not self._output_dir.is_absolute():
            self._output_dir = Path.cwd() / self._output_dir

        self._ensure_output_dir()

        # 客户端
        self.forge_client = None
        self.siliconflow_client = None
        self.comfy_client = None

        # 默认提供者
        # 优先使用设置，回退到环境变量
        self.default_provider = getattr(settings.model, "image_provider", "forge")
        if not self.default_provider:
            self.default_provider = os.getenv("XIAOYOU_IMAGE_PROVIDER", "forge").lower()

        logger.info(
            f"Image Manager initialized. Default Provider: {self.default_provider}"
        )

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
            # 初始化ForgeClient
            try:
                self.forge_client = ForgeClient(base_url="http://127.0.0.1:7860")
            except Exception as e:
                logger.warning(
                    f"Forge Client init failed (Optional if using Cloud): {e}"
                )

            # 初始化SiliconFlowClient
            try:
                self.siliconflow_client = SiliconFlowImageClient()
            except Exception as e:
                logger.warning(f"SiliconFlow Client init failed: {e}")

            # 初始化ComfyClient
            try:
                settings = get_settings()
                self.comfy_client = ComfyClient(
                    host=settings.model.comfy_host, port=settings.model.comfy_port
                )
            except Exception as e:
                logger.warning(f"Comfy Client init failed: {e}")

            # P1-3: 至少一个 client 必须可用，否则不应标记为已初始化
            # 避免所有 client 都失败时仍标记 _is_initialized=True 导致后续调用 NoneType 崩溃
            available_clients = [
                ("forge", self.forge_client),
                ("siliconflow", self.siliconflow_client),
                ("comfy", self.comfy_client),
            ]
            if not any(c is not None for _, c in available_clients):
                self._is_initialized = False
                self.last_error = "所有图像后端 client 初始化均失败"
                logger.error(
                    "Image Manager 初始化失败：所有后端 client 均不可用（forge/siliconflow/comfy）"
                )
                return False

            self._is_initialized = True
            logger.info(
                "Image Manager initialized (Warmup skipped to save memory, "
                "部分后端可能降级)"
            )
            return True
        except Exception as e:
            logger.error(f"Image Manager initialization failed: {e}")
            return False

    async def shutdown(self):
        if not self._is_initialized:
            await self._terminate_forge_process()
            return

        try:
            await self._cancel_pending_forge_unload()
        except Exception:
            pass

        try:
            await self._set_image_gen_active(False)
        except Exception:
            pass

        try:
            await self._terminate_forge_process()
        except Exception:
            pass

        self.forge_client = None
        self.siliconflow_client = None
        self.comfy_client = None
        self._is_initialized = False

    async def generate_image(
        self,
        prompt: str,
        config: Optional[ImageGenerationConfig] = None,
        model_id: Optional[str] = None,
        save_to_file: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate image using Forge or SiliconFlow
        """
        prompt_preview = ""
        try:
            prompt_preview = str(prompt)[:30]
        except Exception:
            prompt_preview = ""
        logger.info(f"[Image Gen] Prompt: {prompt_preview}...")

        if not self._is_initialized:
            await self.initialize()

        if config is None:
            config = ImageGenerationConfig()

        # 确定提供者
        provider = config.provider or self.default_provider

        await self._begin_image_gen(provider)
        try:
            if provider == "siliconflow":
                return await self._generate_with_siliconflow(
                    prompt, config, model_id, save_to_file
                )
            elif provider == "comfyui":
                return await self._generate_with_comfy(
                    prompt, config, model_id, save_to_file
                )

            result = await self._generate_with_forge(
                prompt, config, model_id, save_to_file
            )

            return result
        finally:
            await self._end_image_gen(provider)

    async def generate_images(
        self,
        prompts: list[str],
        config: Optional[ImageGenerationConfig] = None,
        model_id: Optional[str] = None,
        save_to_file: bool = True,
    ) -> Dict[str, Any]:
        if not prompts:
            return {"success": False, "error": "Prompt list is empty"}

        results = []
        for p in prompts:
            r = await self.generate_image(
                prompt=str(p),
                config=config,
                model_id=model_id,
                save_to_file=save_to_file,
            )
            if not r.get("success"):
                return r
            if r.get("images"):
                results.extend(r.get("images"))
            else:
                results.append(
                    {
                        "image_path": r.get("image_path"),
                        "url": r.get("url"),
                    }
                )

        return {"success": True, "images": results}


_image_manager_instance = None
# P0-22: 使用 asyncio.Lock + double-check 保护 async 单例初始化，
# 防止协程并发导致重复创建 ImageManager 实例（资源泄漏、显存翻倍）
_image_manager_lock = asyncio.Lock()


async def get_image_manager():
    """
    获取全局 ImageManager 实例（async 单例）

    线程安全：使用 double-check locking 防止协程并发初始化导致：
    1. 多个 ImageManager 实例被创建（资源泄漏）
    2. 显存/连接池翻倍
    3. ResourceManager 重复注册
    """
    global _image_manager_instance
    if _image_manager_instance is None:
        async with _image_manager_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _image_manager_instance is not None:
                return _image_manager_instance
            _image_manager_instance = ImageManager()
            await _image_manager_instance.initialize()
    return _image_manager_instance


async def shutdown_image_manager_instance():
    global _image_manager_instance
    async with _image_manager_lock:
        if _image_manager_instance is not None:
            try:
                await _image_manager_instance.shutdown()
            except Exception:
                pass
        _image_manager_instance = None
