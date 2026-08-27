#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT-SoVITS 引擎模块
"""

import asyncio
import os
import sys
import time
import aiohttp
import numpy as np
from typing import Optional

try:
    import soundfile as sf
except ImportError:
    sf = None

from config.integrated_config import get_settings
from core.voice.cloud_tts_helpers import get_cloud_tts_session
from core.utils.logger import get_logger
from core.utils.common import get_project_root
from core.voice.engines.base import TTSEngine

try:
    from core.utils.resource_lock import get_resource_lock
except Exception:
    get_resource_lock = None
try:
    from core.resource_manager import get_resource_manager, ResourcePriority
except ImportError:
    get_resource_manager = None
    ResourcePriority = None

logger = get_logger("GPT_SOVITS_ENGINE")


class GPTSoVITSEngine(TTSEngine):
    """
    GPT-SoVITS 引擎实现
    """

    def __init__(self, api_url="http://127.0.0.1:9880/tts", default_lang="zh"):
        super().__init__()
        self.api_url = api_url
        self.default_lang = default_lang
        self.sample_rate = 32000  # GPT-SoVITS 默认通常是 32000
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_loop = None
        self._session_lock = None
        self._control_unavailable_until = 0.0
        self.current_device = "cpu"
        self._is_generating = False  # 生成状态标志
        self._last_unavailable_log_ts = 0.0
        self._unavailable_log_interval = 15.0

    def _is_connection_error_text(self, text: str) -> bool:
        s = str(text or "").lower()
        return (
            "cannot connect" in s
            or "connection refused" in s
            or "connection error" in s
            or "timed out" in s
            or "timeout" in s
            or "actively refused" in s
            or "连接" in str(text or "")
            or "超时" in str(text or "")
        )

    def _log_unavailable(self, action: str, err: object) -> None:
        now = time.monotonic()
        if (
            now - float(self._last_unavailable_log_ts or 0.0)
        ) >= self._unavailable_log_interval:
            self._last_unavailable_log_ts = now
            logger.warning("GPT-SoVITS 服务不可用，%s: %s", action, err)
        else:
            logger.debug("GPT-SoVITS 服务不可用，%s: %s", action, err)

    async def _get_session(self) -> aiohttp.ClientSession:
        return await get_cloud_tts_session(self)

    async def initialize(self):
        await super().initialize()
        # 检查已配置的模型并设置
        settings = get_settings()
        if settings.voice.gpt_model_path:
            await self.set_gpt_weights(settings.voice.gpt_model_path)
        if settings.voice.sovits_model_path:
            await self.set_sovits_weights(settings.voice.sovits_model_path)

        # 注册到资源管理器
        if get_resource_manager:
            rm = get_resource_manager()
            rm.register_resource_handler(
                "gpu_memory", ResourcePriority.MEDIUM, self.handle_resource_pressure
            )
            logger.info("Registered GPT-SoVITS with ResourceManager (Priority: MEDIUM)")

    async def handle_resource_pressure(self, action: str):
        """处理资源压力通知"""
        if action == "release":
            if self.current_device in ("cpu", None):
                return
            if self._is_generating:
                logger.warning(
                    "Ignored resource release request during GPT-SoVITS generation"
                )
                return
            await self.move_to_cpu()

    def _build_control_url(self, endpoint: str) -> str:
        base = str(self.api_url or "").strip()
        if not base:
            base = "http://127.0.0.1:9880/tts"

        base = base.rstrip("/")
        if base.endswith("/tts"):
            base = base[: -len("/tts")]

        endpoint = (endpoint or "").strip()
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return base + endpoint

    def _resolve_local_path(self, p: str) -> str:
        p = str(p or "").strip()
        if not p:
            return p
        p = os.path.expanduser(p)
        if os.path.isabs(p):
            return os.path.normpath(p)
        return os.path.normpath(os.path.abspath(os.path.join(os.getcwd(), p)))

    async def _try_set_weights(
        self, *, endpoint: str, weights_path: str, kind: str
    ) -> bool:
        now = time.monotonic()
        if now < float(self._control_unavailable_until or 0.0):
            return False

        url = self._build_control_url(endpoint)
        candidate_params = [
            {"weights_path": weights_path},
            {"weight_path": weights_path},
            {"gpt_path": weights_path},
            {"sovits_path": weights_path},
            {"path": weights_path},
        ]

        timeout = aiohttp.ClientTimeout(
            total=3.0, connect=1.0, sock_connect=1.0, sock_read=2.0
        )
        last_error_text = ""
        session = await self._get_session()

        for params in candidate_params:
            try:
                async with session.get(url, params=params, timeout=timeout) as response:
                    text = await response.text()
                    if response.status == 200:
                        logger.info(
                            f"Successfully set {kind} weights to {weights_path}"
                        )
                        return True
                    last_error_text = f"{response.status}: {text}"
                    if response.status in (400, 404, 405, 422):
                        continue
            except Exception as e:
                last_error_text = str(e)
                err_lower = last_error_text.lower()
                if (
                    "cannot connect" in err_lower
                    or "connection refused" in err_lower
                    or "timeout" in err_lower
                    or "连接" in last_error_text
                    or "超时" in last_error_text
                ):
                    self._control_unavailable_until = time.monotonic() + 15.0
                    break
                continue

        if time.monotonic() < float(self._control_unavailable_until or 0.0):
            if self._is_connection_error_text(last_error_text):
                self._log_unavailable(f"设置{kind}权重", last_error_text)
            else:
                logger.error(f"Failed to set {kind} weights: {last_error_text}")
            return False

        for params in candidate_params:
            try:
                async with session.post(url, json=params, timeout=timeout) as response:
                    text = await response.text()
                    if response.status == 200:
                        logger.info(
                            f"Successfully set {kind} weights to {weights_path}"
                        )
                        return True
                    last_error_text = f"{response.status}: {text}"
                    if response.status in (400, 404, 405, 422):
                        continue
            except Exception as e:
                last_error_text = str(e)
                err_lower = last_error_text.lower()
                if (
                    "cannot connect" in err_lower
                    or "connection refused" in err_lower
                    or "timeout" in err_lower
                    or "连接" in last_error_text
                    or "超时" in last_error_text
                ):
                    self._control_unavailable_until = time.monotonic() + 15.0
                    break
                continue

        logger.error(f"Failed to set {kind} weights: {last_error_text}")
        return False

    async def set_gpt_weights(self, weights_path: str):
        # 增加防御性检查：如果是 "default" 或空，直接忽略
        if not weights_path or weights_path.lower() == "default":
            logger.debug(f"Ignoring set_gpt_weights for value: {weights_path}")
            return

        try:
            resolved = self._resolve_local_path(weights_path)
            if os.path.exists(resolved):
                await self._try_set_weights(
                    endpoint="/set_gpt_weights", weights_path=resolved, kind="GPT"
                )
            else:
                await self._try_set_weights(
                    endpoint="/set_gpt_weights", weights_path=weights_path, kind="GPT"
                )
        except Exception as e:
            logger.error(f"Error setting GPT weights: {e}")

    async def move_to_cpu(self):
        """将模型移至CPU以节省VRAM"""
        if time.monotonic() < float(self._control_unavailable_until or 0.0):
            return False

        try:
            url = self.api_url.replace("/tts", "/set_device")
            params = {"device": "cpu", "is_half": "false"}
            timeout = aiohttp.ClientTimeout(total=10.0, connect=1.0, sock_read=9.0)
            session = await self._get_session()
            async with session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    logger.info("Successfully moved GPT-SoVITS to CPU")
                    self.current_device = "cpu"
                    return True
                else:
                    logger.error(
                        f"Failed to move GPT-SoVITS to CPU: {await response.text()}"
                    )
                    return False
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                self._control_unavailable_until = time.monotonic() + 15.0
                self._log_unavailable("切换到 CPU", repr(e))
                return False
            if "Cannot connect" in str(e) or "connection refused" in str(e).lower():
                self._control_unavailable_until = time.monotonic() + 15.0
                self._log_unavailable("切换到 CPU", e)
                return False
            else:
                logger.error(f"Error moving GPT-SoVITS to CPU: {repr(e)}")
                return False

    async def move_to_gpu(self):
        """将模型恢复到GPU"""
        if time.monotonic() < float(self._control_unavailable_until or 0.0):
            return False

        try:
            # 只有当确实需要切换时才调用 API
            if self.current_device == "cuda":
                return True

            url = self.api_url.replace("/tts", "/set_device")
            # GPT-SoVITS API 通常支持半精度加载以节省显存
            params = {"device": "cuda", "is_half": "true"}
            timeout = aiohttp.ClientTimeout(total=15.0, connect=2.0, sock_read=13.0)
            session = await self._get_session()

            logger.info("Attempting to move GPT-SoVITS to GPU...")
            async with session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    logger.info("Successfully moved GPT-SoVITS to GPU")
                    self.current_device = "cuda"
                    return True
                else:
                    error_msg = await response.text()
                    logger.error(f"Failed to move GPT-SoVITS to GPU: {error_msg}")
                    return False
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                self._control_unavailable_until = time.monotonic() + 15.0
                self._log_unavailable("切换到 GPU", repr(e))
                return False
            if "Cannot connect" in str(e) or "connection refused" in str(e).lower():
                self._control_unavailable_until = time.monotonic() + 15.0
                self._log_unavailable("切换到 GPU", e)
                return False
            else:
                logger.error(f"Error moving GPT-SoVITS to GPU: {e}")
                return False

    async def set_sovits_weights(self, weights_path: str):
        if not weights_path or weights_path.lower() == "default":
            logger.debug(f"Ignoring set_sovits_weights for value: {weights_path}")
            return

        try:
            resolved = self._resolve_local_path(weights_path)
            if os.path.exists(resolved):
                await self._try_set_weights(
                    endpoint="/set_sovits_weights", weights_path=resolved, kind="SoVITS"
                )
            else:
                await self._try_set_weights(
                    endpoint="/set_sovits_weights",
                    weights_path=weights_path,
                    kind="SoVITS",
                )
        except Exception as e:
            logger.error(f"Error setting SoVITS weights: {e}")

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        """
        调用 GPT-SoVITS API 合成语音
        """
        self._is_generating = True
        try:
            return await self._synthesize_impl(text, **kwargs)
        finally:
            self._is_generating = False

    async def _synthesize_impl(self, text: str, **kwargs) -> np.ndarray:
        """
        调用 GPT-SoVITS API 合成语音
        """
        lang = kwargs.get("lang")
        if not lang:
            lang = kwargs.get("text_lang") or kwargs.get("text_language")
        if not lang:
            lang = self.default_lang
        lang = str(lang)

        # 动态获取默认参考音频路径
        settings = get_settings()
        default_ref_audio = settings.voice.reference_audio

        # 确定基础路径
        if getattr(sys, "frozen", False):
            # 作为编译的EXE运行
            base_path = os.path.dirname(sys.executable)
            # 在one-dir模式下，资源可能在_internal或根目录，取决于spec
            # 但通常我们将外部资源放在EXE旁边的根目录以便编辑
            # 或者如果包含在datas中，它们在sys._MEIPASS中

            # 首先检查是否为外部文件（用户可编辑）
            external_path = (
                os.path.join(base_path, default_ref_audio)
                if default_ref_audio
                else None
            )

            # 然后检查内部（打包的）
            internal_path = (
                os.path.join(sys._MEIPASS, default_ref_audio)
                if hasattr(sys, "_MEIPASS") and default_ref_audio
                else None
            )

            if external_path and os.path.exists(external_path):
                default_ref_audio = external_path
            elif internal_path and os.path.exists(internal_path):
                default_ref_audio = internal_path
            else:
                default_ref_audio = os.path.join(
                    base_path, "ref_audio", "female", "ref_calm.wav"
                )
        else:
            # 从源码运行
            base_path = str(get_project_root())
            if not default_ref_audio:
                default_ref_audio = os.path.join(
                    base_path, "ref_audio", "female", "ref_calm.wav"
                )
            elif not os.path.isabs(default_ref_audio):
                default_ref_audio = os.path.join(base_path, default_ref_audio)

        # 确定最终使用的参考音频路径
        ref_audio_path = (
            kwargs.get("ref_audio_path")
            or kwargs.get("reference_audio")
            or default_ref_audio
        )

        # 确保 ref_audio_path 是绝对路径
        if ref_audio_path and not os.path.isabs(ref_audio_path):
            if getattr(sys, "frozen", False):
                ref_audio_path = os.path.join(
                    os.path.dirname(sys.executable), ref_audio_path
                )
            else:
                ref_audio_path = os.path.abspath(
                    os.path.join(str(get_project_root()), ref_audio_path)
                )

        # 再次检查文件是否存在
        if ref_audio_path and not os.path.exists(ref_audio_path):
            logger.warning(
                f"Reference audio path does not exist locally: {ref_audio_path}"
            )

        prompt_text = kwargs.get("prompt_text") or "这是中文纯语音测试，不包含英文内容"
        prompt_lang = kwargs.get("prompt_lang") or "zh"

        params = {
            "text": text,
            "text_lang": lang,
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "top_k": kwargs.get("top_k", 5),
            "top_p": kwargs.get("top_p", 1.0),
            "temperature": kwargs.get("temperature", 1.0),
            "speed": kwargs.get("speed", 1.0),
        }

        # 可选参数
        if "batch_size" in kwargs and kwargs.get("batch_size") is not None:
            params["batch_size"] = kwargs["batch_size"]
        if "speed_factor" in kwargs and kwargs.get("speed_factor") is not None:
            params["speed_factor"] = kwargs["speed_factor"]
        if "pitch" in kwargs and kwargs.get("pitch") is not None:
            params["pitch"] = kwargs["pitch"]

        params = {k: v for k, v in params.items() if v is not None}

        audio_content = await self.synthesize_bytes(text, **kwargs)
        if not audio_content:
            raise RuntimeError("GPT-SoVITS returned empty audio data")

        if not sf:
            raise RuntimeError("soundfile library not installed")

        import io

        try:
            data, _samplerate = sf.read(io.BytesIO(audio_content))
            return data.astype(np.float32)
        except Exception as e:
            raise RuntimeError(f"Audio decoding failed: {e}") from e

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        lang = kwargs.get("lang")
        if not lang:
            lang = kwargs.get("text_lang") or kwargs.get("text_language")
        if not lang:
            lang = self.default_lang
        lang = str(lang)

        settings = get_settings()
        default_ref_audio = settings.voice.reference_audio

        if getattr(sys, "frozen", False):
            base_path = os.path.dirname(sys.executable)
            external_path = (
                os.path.join(base_path, default_ref_audio)
                if default_ref_audio
                else None
            )
            internal_path = (
                os.path.join(sys._MEIPASS, default_ref_audio)
                if hasattr(sys, "_MEIPASS") and default_ref_audio
                else None
            )

            if external_path and os.path.exists(external_path):
                default_ref_audio = external_path
            elif internal_path and os.path.exists(internal_path):
                default_ref_audio = internal_path
            else:
                default_ref_audio = os.path.join(
                    base_path, "ref_audio", "female", "ref_calm.wav"
                )
        else:
            base_path = str(get_project_root())
            if not default_ref_audio:
                default_ref_audio = os.path.join(
                    base_path, "ref_audio", "female", "ref_calm.wav"
                )
            elif not os.path.isabs(default_ref_audio):
                default_ref_audio = os.path.join(base_path, default_ref_audio)

        ref_audio_path = (
            kwargs.get("ref_audio_path")
            or kwargs.get("reference_audio")
            or default_ref_audio
        )

        if ref_audio_path and not os.path.isabs(ref_audio_path):
            if getattr(sys, "frozen", False):
                ref_audio_path = os.path.join(
                    os.path.dirname(sys.executable), ref_audio_path
                )
            else:
                ref_audio_path = os.path.abspath(
                    os.path.join(str(get_project_root()), ref_audio_path)
                )

        prompt_text = kwargs.get("prompt_text") or "这是中文纯语音测试，不包含英文内容"
        prompt_lang = kwargs.get("prompt_lang") or "zh"

        params = {
            "text": text,
            "text_lang": lang,
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "top_k": kwargs.get("top_k", 5),
            "top_p": kwargs.get("top_p", 1.0),
            "temperature": kwargs.get("temperature", 1.0),
            "speed": kwargs.get("speed", 1.0),
        }

        if "batch_size" in kwargs and kwargs.get("batch_size") is not None:
            params["batch_size"] = kwargs["batch_size"]
        if "speed_factor" in kwargs and kwargs.get("speed_factor") is not None:
            params["speed_factor"] = kwargs["speed_factor"]
        if "pitch" in kwargs and kwargs.get("pitch") is not None:
            params["pitch"] = kwargs["pitch"]

        params = {k: v for k, v in params.items() if v is not None}

        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=300, connect=3.0, sock_connect=3.0)
        try:
            if get_resource_lock:
                async with get_resource_lock().acquire("TTS", reject_if_full=True):
                    async with session.get(
                        self.api_url, params=params, timeout=timeout
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise RuntimeError(
                                f"GPT-SoVITS API Error: {response.status} - {error_text}"
                            )
                        audio_content = await response.read()
            else:
                async with session.get(
                    self.api_url, params=params, timeout=timeout
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(
                            f"GPT-SoVITS API Error: {response.status} - {error_text}"
                        )
                    audio_content = await response.read()
        except Exception as e:
            if self._is_connection_error_text(e):
                self._control_unavailable_until = time.monotonic() + 15.0
                self._log_unavailable("语音合成请求", e)
                raise RuntimeError("GPT-SoVITS 服务未启动或不可用")
            raise

        if not audio_content:
            return None
        return audio_content

    async def shutdown(self):
        try:
            if self._session and not self._session.closed:
                await self._session.close()
        except Exception:
            pass
        self._session = None
        self._session_loop = None
        await super().shutdown()
