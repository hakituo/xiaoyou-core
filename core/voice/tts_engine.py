#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS引擎模块
负责管理TTS引擎实例和分发合成任务
"""

import threading
from typing import Optional

from config.integrated_config import get_settings
from core.utils.config_accessor import get_config
from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock

# 引擎类延迟导入，避免启动时加载 torch/numpy/qwen_tts 等重型依赖
# from core.voice.engines import (
#     TTSEngine,
#     GPTSoVITSEngine,
#     CloudTTSEngine,
#     Qwen3TTSEngine,
#     F5TTSEngine,
# )

try:
    from core.resource_manager import get_resource_manager, ResourcePriority
except ImportError:
    get_resource_manager = None
    ResourcePriority = None

logger = get_logger("TTS_ENGINE")


class TTSManager:
    """
    TTS管理器
    负责管理TTS引擎实例和分发合成任务
    """

    _instance = None
    # P0-23: 使用 threading.Lock + double-check 保护 __new__ 单例初始化，
    # 防止多线程并发导致重复创建实例（_initialized_manager 状态不一致、引擎重复加载）
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                # double-check：拿到锁后再次确认，避免重复初始化
                if cls._instance is not None:
                    return cls._instance
                cls._instance = super(TTSManager, cls).__new__(cls)
                cls._instance._initialized_manager = False
        return cls._instance

    def __init__(self):
        """
        初始化TTS管理器
        """
        if self._initialized_manager:
            return

        self.settings = get_settings()
        self.engine = None  # type: Optional[object]  # TTSEngine 延迟导入
        self.initialized = False
        self._initialized_manager = True
        self.current_device: Optional[str] = None
        self._device_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self.last_error: Optional[str] = None
        logger.info("TTSManager created")

    @property
    def device(self) -> str:
        # 尝试从引擎获取实时状态，如果引擎没有状态则回退到管理器记录的状态
        if self.engine and hasattr(self.engine, "current_device"):
            return self.engine.current_device or self.current_device or "cpu"
        return self.current_device or "cpu"

    @device.setter
    def device(self, value: str):
        self.current_device = str(value or "").strip().lower() or None

    async def initialize(self):
        """
        初始化TTS管理器
        """
        if self.initialized:
            return

        logger.info("Initializing TTS Manager...")

        # 1. 优先使用新的配置结构
        tts_config = self.settings.voice.tts
        provider = tts_config.provider

        # 兼容旧配置
        legacy_engine = getattr(self.settings.voice, "tts_engine", "qwen3")
        if provider == "local" and legacy_engine in ["cloud", "siliconflow", "openai"]:
            provider = legacy_engine

        if provider in ["local", "default", "auto"]:
            try:
                from core.voice.engines import Qwen3TTSEngine

                model_hint = str(tts_config.model or "").strip()
                if model_hint.lower() in {"", "default", "qwen3"}:
                    model_hint = None
                self.engine = Qwen3TTSEngine(model_path=model_hint)
                await self.engine.initialize()
                logger.info("Selected Qwen3TTSEngine (default)")
                self.last_error = None
            except Exception as e:
                logger.error(f"Error initializing default Qwen3-TTS: {e}")
                self.engine = None
                self.last_error = f"Qwen3-TTS初始化失败: {str(e)}"
        elif provider in ["gpt_sovits"]:
            try:
                from core.voice.engines import GPTSoVITSEngine

                self.engine = GPTSoVITSEngine()
                await self.engine.initialize()
                logger.info("Selected GPTSoVITSEngine")
                self.last_error = None
            except Exception as e:
                logger.error(f"Error initializing GPTSoVITS: {e}")
                self.engine = None
                self.last_error = f"GPT-SoVITS初始化失败: {str(e)}"
        elif provider in ["qwen3", "local:qwen3"] or (
            provider == "local" and str(tts_config.model or "").lower() == "qwen3"
        ):
            try:
                from core.voice.engines import Qwen3TTSEngine

                model_hint = str(tts_config.model or "").strip()
                if model_hint.lower() in {"", "default", "gpt_sovits", "qwen3"}:
                    model_hint = None
                self.engine = Qwen3TTSEngine(model_path=model_hint)
                await self.engine.initialize()
                logger.info("Selected Qwen3TTSEngine")
                self.last_error = None
            except Exception as e:
                model_hint = str(tts_config.model or "").strip()
                logger.error(
                    "Error initializing local Qwen3-TTS: %s | model=%s",
                    e,
                    model_hint or "Qwen3-TTS-12Hz-0.6B-Base",
                )
                logger.error(
                    "Qwen3-TTS 仅允许本地加载。请确认当前后端 Python 环境已安装 qwen_tts，并确保模型目录存在且可读。"
                )
                self.engine = None
                self.last_error = f"Qwen3-TTS引擎加载失败，请检查 qwen_tts 是否已安装且模型路径存在。详细错误: {str(e)}"
        elif provider in ["f5", "f5-tts", "local:f5"] or (
            provider == "local" and str(tts_config.model or "").lower() == "f5"
        ):
            try:
                from core.voice.engines import F5TTSEngine

                self.engine = F5TTSEngine()
                await self.engine.initialize()
                logger.info("Selected F5TTSEngine")
                self.last_error = None
            except Exception as e:
                logger.error(f"Error initializing F5-TTS: {e}")
                self.engine = None
                self.last_error = f"F5-TTS引擎加载失败，请检查 f5-tts 是否已安装且模型已下载。详细错误: {str(e)}"
        elif provider in ["cloud", "siliconflow", "openai", "custom"]:
            try:
                from core.voice.engines import CloudTTSEngine

                # 确定默认值
                model = tts_config.model
                base_url = tts_config.base_url
                api_key = tts_config.api_key

                if provider == "siliconflow":
                    if not model or model == "default":
                        model = "fishaudio/fish-speech-1.5"
                    if not base_url:
                        base_url = "https://api.siliconflow.cn/v1/audio/speech"
                elif provider == "openai":
                    if not model or model == "default":
                        model = "tts-1"
                    if not base_url:
                        base_url = "https://api.openai.com/v1/audio/speech"

                self.engine = CloudTTSEngine(
                    api_key=api_key, base_url=base_url, model=model
                )
                await self.engine.initialize()
                logger.info(
                    f"Selected CloudTTSEngine (Provider: {provider}, Model: {model})"
                )
                self.last_error = None
            except Exception as e:
                logger.error(f"Error initializing Cloud TTS: {e}")
                self.engine = None
                self.last_error = f"云端TTS引擎初始化失败: {str(e)}"
        elif provider in ["volcano", "volcengine", "字节"]:
            try:
                from core.voice.engines import VolcanoTTSEngine

                model = tts_config.model
                api_key = tts_config.api_key
                base_url = tts_config.base_url

                # 读取火山引擎特有的额外配置（pydantic v2 extra="allow"）
                extra = getattr(tts_config, "model_extra", {}) or {}
                appid = getattr(tts_config, "appid", None) or extra.get("appid")
                voice_map = extra.get("voice_map", {})
                key_map = extra.get("key_map", {})

                self.engine = VolcanoTTSEngine(
                    api_key=api_key,
                    appid=appid,
                    model=model,
                    voice_map=voice_map,
                    key_map=key_map,
                )
                await self.engine.initialize()
                logger.info(
                    f"Selected VolcanoTTSEngine (model={model}, "
                    f"voices={list(voice_map.keys()) or [model]})"
                )
                self.last_error = None
            except Exception as e:
                logger.error(f"Error initializing Volcano TTS: {e}")
                self.engine = None
                self.last_error = f"火山引擎TTS初始化失败: {str(e)}"
        else:
            logger.warning(
                f"Unknown TTS provider: {provider}, falling back to Qwen3-TTS"
            )
            try:
                from core.voice.engines import Qwen3TTSEngine

                self.engine = Qwen3TTSEngine()
                await self.engine.initialize()
                logger.info("Fallback to Qwen3TTSEngine")
                self.last_error = None
            except Exception as fallback_err:
                logger.warning(f"Fallback to Qwen3-TTS failed: {fallback_err}")
                try:
                    from core.voice.engines import F5TTSEngine

                    self.engine = F5TTSEngine()
                    await self.engine.initialize()
                    logger.info("Fallback to F5TTSEngine")
                    self.last_error = None
                except Exception as e:
                    logger.error(f"All TTS fallbacks failed: {e}")
                    self.engine = None
                    self.last_error = f"所有TTS引擎回退均失败: {str(e)}"

        # P1-3: 所有 provider 都失败时不应标记为已初始化
        # self.engine 为 None 表示没有任何 TTS 引擎可用
        # 此时保留 self.initialized=False，允许后续重试，避免"失败仍标记为成功"
        if self.engine is None:
            logger.error(
                "TTS 初始化失败：所有 provider 均不可用，last_error=%s",
                self.last_error,
            )
            # 仍尝试注册到资源管理器（按需重试初始化）
            self._register_resource_manager_safely()
            return

        self.initialized = True
        logger.info("TTS engine initialized")

        # 注册到资源管理器
        self._register_resource_manager_safely()

    def _register_resource_manager_safely(self) -> None:
        """P1-3: 抽取资源管理器注册逻辑，避免初始化失败时重复代码。"""
        if not get_resource_manager or not ResourcePriority:
            return
        try:
            rm = get_resource_manager()
            try:
                rm.register_model(
                    model_id="tts_engine",
                    model_type="tts",
                    priority=ResourcePriority.MEDIUM,
                    load_func=self.initialize,
                    unload_func=self.shutdown,
                    instance=self,
                )
            except Exception:
                pass
            rm.register_resource_handler(
                "gpu_memory", ResourcePriority.MEDIUM, self.handle_resource_pressure
            )
            logger.info("Registered TTS with Resource Manager (Priority: MEDIUM)")
        except Exception as e:
            logger.warning(f"Failed to register with Resource Manager: {e}")

    async def handle_resource_pressure(self, action: str):
        """处理资源压力通知"""
        act = str(action or "").strip().lower()
        if act == "release":
            if not self.engine or self.current_device in ("cpu", None):
                return
            await self.move_to_cpu()
        elif act in {"recover", "restore"}:
            return

    async def move_to_cpu(self):
        """如果支持，将当前引擎卸载到CPU"""
        if self.engine and hasattr(self.engine, "move_to_cpu"):
            ok = await self.engine.move_to_cpu()
            if ok is False:
                return
            self.current_device = "cpu"
            logger.info("TTS engine moved to CPU")

    async def move_to_gpu(self):
        """如果支持，将当前引擎恢复到GPU"""
        if self.engine and hasattr(self.engine, "move_to_gpu"):
            ok = await self.engine.move_to_gpu()
            if ok is False:
                return
            self.current_device = "cuda"

    async def _ensure_optimal_device(self):
        if not self.engine:
            return
        async with self._device_lock:
            try:
                from core.resource_manager import get_resource_manager, ResourceType

                rm = get_resource_manager()
                if rm and rm.monitor.is_resource_pressure(ResourceType.GPU_MEMORY):
                    if (
                        hasattr(self.engine, "move_to_cpu")
                        and self.current_device != "cpu"
                    ):
                        ok = await self.engine.move_to_cpu()
                        if ok:
                            self.current_device = "cpu"
                    return
            except Exception:
                pass

            target = "cpu"
            has_cuda = False
            try:
                import torch

                has_cuda = bool(torch.cuda.is_available())
            except Exception:
                has_cuda = False

            if has_cuda and hasattr(self.engine, "move_to_gpu"):
                target = "cuda"

            # 如果当前已经在目标设备上，直接返回
            if self.current_device == target:
                return

            if target == "cuda" and hasattr(self.engine, "move_to_gpu"):
                try:
                    from core.resource_manager import get_resource_manager

                    rm = get_resource_manager()
                    free_mb = await rm.get_gpu_free_mb() if rm else None
                    if isinstance(free_mb, int):
                        try:
                            settings = get_settings()
                            min_free = int(
                                get_config(
                                    "model.tts_gpu_min_free_mb",
                                    default=1200,
                                    settings=settings,
                                )
                                or 1200
                            )
                        except Exception:
                            min_free = 1200

                        if free_mb < min_free:
                            logger.info(
                                "GPU 空闲显存不足(%sMB < %sMB)，保持 TTS 在 CPU",
                                free_mb,
                                min_free,
                            )
                            return
                except Exception:
                    pass

                ok = await self.engine.move_to_gpu()
                if ok:
                    self.current_device = "cuda"
            elif target == "cpu" and hasattr(self.engine, "move_to_cpu"):
                ok = await self.engine.move_to_cpu()
                if ok:
                    self.current_device = "cpu"

    async def get_engine(self):
        """
        获取TTS引擎实例
        """
        if not self.initialized or not self.engine:
            await self.initialize()
        return self.engine

    async def synthesize(self, text: str, **kwargs):
        """
        合成语音，带自动回退逻辑
        """
        import numpy as np

        engine = await self.get_engine()
        if not engine:
            logger.error(self.last_error or "No TTS engine available")
            return np.zeros(0, dtype=np.float32)

        await self._ensure_optimal_device()

        try:
            return await engine.synthesize(text, **kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            is_connection_error = (
                "cannot connect" in err_msg
                or "connection refused" in err_msg
                or "timeout" in err_msg
            )

            if is_connection_error:
                from core.voice.engines import Qwen3TTSEngine

                if not isinstance(engine, Qwen3TTSEngine):
                    fallback_name = "Qwen3-TTS"
                    fallback_cls = Qwen3TTSEngine
                    logger.warning(
                        f"TTS engine failed ({e}), attempting fallback to {fallback_name}..."
                    )
                    try:
                        fallback_engine = fallback_cls()
                        await fallback_engine.initialize()
                        self.engine = fallback_engine
                        logger.info(f"Successfully switched to fallback engine: {fallback_name}")
                        return await fallback_engine.synthesize(text, **kwargs)
                    except Exception as fallback_e:
                        logger.error(f"Fallback to {fallback_name} also failed: {fallback_e}")
                        self.engine = engine

            logger.error(f"TTS synthesis failed: {e}")
            return np.zeros(0, dtype=np.float32)

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        engine = await self.get_engine()
        if not engine:
            logger.error(self.last_error or "No TTS engine available")
            return None
        await self._ensure_optimal_device()

        try:
            if hasattr(engine, "synthesize_bytes"):
                return await engine.synthesize_bytes(text, **kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            is_connection_error = (
                "cannot connect" in err_msg
                or "connection refused" in err_msg
                or "timeout" in err_msg
            )

            if is_connection_error:
                from core.voice.engines import Qwen3TTSEngine

                if not isinstance(engine, Qwen3TTSEngine):
                    fallback_name = "Qwen3-TTS"
                    fallback_cls = Qwen3TTSEngine
                    logger.warning(
                        f"TTS synthesize_bytes failed ({e}), attempting fallback to {fallback_name}..."
                    )
                    try:
                        fallback_engine = fallback_cls()
                        await fallback_engine.initialize()
                        self.engine = fallback_engine
                        if hasattr(fallback_engine, "synthesize_bytes"):
                            return await fallback_engine.synthesize_bytes(text, **kwargs)
                    except Exception as fallback_e:
                        logger.error(f"Fallback to {fallback_name} bytes failed: {fallback_e}")
                        self.engine = engine

        return None

    async def shutdown(self):
        """
        关闭TTS引擎
        """
        if self.engine:
            await self.engine.shutdown()
        self.initialized = False
        logger.info("TTS engine shutdown")

    async def switch_engine(self, provider: str) -> str:
        """
        动态切换TTS引擎
        
        Args:
            provider: 引擎类型 "cloud"/"volcano" 或 "local"/"qwen3"
        
        Returns:
            切换结果描述
        """
        provider = str(provider or "").strip().lower()
        
        # 映射别名
        cloud_aliases = {"cloud", "volcano", "volcengine", "字节", "火山", "云端"}
        local_aliases = {"local", "qwen3", "本地"}
        
        if provider in cloud_aliases:
            target = "volcano"
        elif provider in local_aliases:
            target = "qwen3"
        else:
            return f"未知的TTS类型: {provider}，支持: cloud/volcano/云端 或 local/qwen3/本地"
        
        # 获取当前配置
        tts_config = self.settings.voice.tts
        current_provider = str(tts_config.provider or "").strip().lower()
        
        # 检查是否已经是目标引擎
        if (target == "volcano" and current_provider in cloud_aliases) or \
           (target == "qwen3" and current_provider in local_aliases):
            return f"当前已经是{'云端' if target == 'volcano' else '本地'}TTS"
        
        # 关闭当前引擎
        if self.engine:
            try:
                await self.engine.shutdown()
            except Exception:
                pass
            self.engine = None
        
        # 更新配置
        tts_config.provider = target
        self.initialized = False
        
        # 重新初始化
        try:
            await self.initialize()
            engine_name = "火山引擎" if target == "volcano" else "Qwen3本地"
            return f"已切换到{engine_name}TTS"
        except Exception as e:
            logger.error(f"切换TTS引擎失败: {e}")
            return f"切换失败: {str(e)}"


# 方便导入的工厂函数
_tts_manager_instance = None
# P0-23: 使用 threading.Lock + double-check 保护 get_tts_manager 单例，
# 防止多线程并发导致重复创建 TTSManager 实例（引擎重复加载、显存翻倍）
_tts_manager_lock = threading.Lock()


def get_tts_manager() -> TTSManager:
    global _tts_manager_instance
    if _tts_manager_instance is None:
        with _tts_manager_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _tts_manager_instance is not None:
                return _tts_manager_instance
            _tts_manager_instance = TTSManager()
    return _tts_manager_instance
