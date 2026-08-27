#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-TTS 引擎模块（基于 faster-qwen3-tts，使用 CUDA Graph 加速）
"""

import asyncio
import os
import uuid
import numpy as np
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

try:
    import soundfile as sf
except ImportError:
    sf = None

from config.integrated_config import get_settings
from core.utils.config_accessor import get_config
from core.utils.logger import get_logger
from core.utils.common import get_project_root
from core.utils.async_locks import LazyAsyncLock
from core.voice.engines.base import TTSEngine
from core.voice.engines.mock_transformer import _ensure_sox_mock

try:
    from core.utils.resource_lock import get_resource_lock
except Exception:
    get_resource_lock = None
try:
    from core.resource_manager import get_resource_manager, ResourcePriority
except ImportError:
    get_resource_manager = None
    ResourcePriority = None

logger = get_logger("QWEN3_TTS_ENGINE")


class Qwen3TTSEngine(TTSEngine):
    def __init__(self, model_path: str = None):
        super().__init__()
        self.model_path = model_path
        self._model = None
        self.current_device = "cpu"
        self._load_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._is_generating = False  # 生成状态标志
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen3_tts")
        # 动态批处理相关
        self._batch_queue = []  # 等待批处理的请求队列
        self._batch_results = {}  # 请求ID到结果的映射
        self._batch_lock = LazyAsyncLock()
        self._batch_timer = None  # 批处理定时器
        self._batch_max_wait = 0.05  # 最大等待50ms收集请求
        self._batch_max_size = 4  # 最大批处理大小
        # P1-2: 维护 fire-and-forget 批处理任务引用，防止被 GC 导致 future 永久阻塞
        self._batch_tasks: set = set()

    def _spawn_batch_task(self, coro) -> None:
        """P1-2: 提交批处理任务并保存引用，完成后自动清理并记录异常。"""
        task = asyncio.create_task(coro)
        self._batch_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._batch_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Qwen3-TTS 批处理任务异常: %r", exc, exc_info=exc)

        task.add_done_callback(_on_done)

    def _resolve_model_path(self):
        settings = get_settings()
        root = str(get_project_root())
        base_models_dir = (
            get_config("model.model_dir", default="models", settings=settings) or "models"
        )
        ignore_values = {"", "default", "gpt_sovits", "qwen3"}
        candidate_paths = []

        model_path = str(self.model_path or "").strip()
        if model_path:
            if os.path.isabs(model_path):
                return model_path, os.path.exists(model_path)
            candidate_paths.append(os.path.join(root, model_path))
            candidate_paths.append(model_path)

        model_hint = str(getattr(settings.voice.tts, "model", "") or "").strip()
        if model_hint.lower() not in ignore_values:
            if os.path.isabs(model_hint):
                candidate_paths.append(model_hint)
            else:
                candidate_paths.append(os.path.join(root, model_hint))
                candidate_paths.append(os.path.join(root, base_models_dir, model_hint))
                candidate_paths.append(
                    os.path.join(root, base_models_dir, "tts", model_hint)
                )

        # 优先 0.6B，其次 1.7B
        candidate_paths.extend(
            [
                os.path.join(root, base_models_dir, "Qwen3-TTS-12Hz-0.6B-Base"),
                os.path.join(root, base_models_dir, "tts", "Qwen3-TTS-12Hz-0.6B-Base"),
                os.path.join(root, base_models_dir, "Qwen3-TTS-12Hz-1.7B-Base"),
                os.path.join(root, base_models_dir, "tts", "Qwen3-TTS-12Hz-1.7B-Base"),
                os.path.join(root, base_models_dir, "Qwen3-TTS-12Hz-1.7B"),
                os.path.join(root, base_models_dir, "tts", "Qwen3-TTS-12Hz-1.7B"),
                os.path.join(root, base_models_dir, "Qwen3-TTS"),
                os.path.join(root, base_models_dir, "tts", "Qwen3-TTS"),
            ]
        )

        for path in candidate_paths:
            if path and os.path.exists(path):
                return path, True

        fallback = (
            candidate_paths[0]
            if candidate_paths
            else os.path.join(root, base_models_dir, "Qwen3-TTS-12Hz-0.6B-Base")
        )
        return fallback, False

    async def initialize(self):
        if self.initialized:
            return
        _ensure_sox_mock()
        self.model_path, path_exists = self._resolve_model_path()
        if not path_exists:
            logger.warning(f"Qwen3-TTS model path not found: {self.model_path}")

        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"

        async with self._load_lock:

            def _load():
                try:
                    if not torch.cuda.is_available():
                        # FasterQwen3TTS 仅支持 CUDA，回退到原始 qwen_tts
                        raise ValueError("CUDA not available, falling back to qwen_tts")

                    from faster_qwen3_tts import FasterQwen3TTS

                    logger.info(f"Loading FasterQwen3-TTS from {self.model_path}")
                    self._model = FasterQwen3TTS.from_pretrained(
                        str(self.model_path),
                    )
                    self.current_device = "cuda"

                    # 检测GPU架构并记录日志
                    gpu_name = torch.cuda.get_device_name(0).lower()
                    cc_major, cc_minor = torch.cuda.get_device_capability(0)
                    compute_capability = cc_major * 10 + cc_minor
                    arch_name = "Unknown"

                    is_blackwell = compute_capability >= 100 or "rtx 50" in gpu_name
                    is_hopper = compute_capability >= 90 and compute_capability < 100
                    is_ada = compute_capability == 89 or "rtx 40" in gpu_name
                    is_ampere = compute_capability >= 80 and compute_capability < 89

                    if is_blackwell:
                        arch_name = "Blackwell"
                    elif is_hopper:
                        arch_name = "Hopper"
                    elif is_ada:
                        arch_name = "Ada Lovelace"
                    elif is_ampere:
                        arch_name = "Ampere"

                    logger.info(f"FasterQwen3-TTS已加载: {arch_name}架构, CUDA Graph加速")

                except Exception as e:
                    # FasterQwen3TTS 加载失败，回退到原始 qwen_tts
                    logger.warning(f"FasterQwen3-TTS不可用: {e}，回退到原始qwen_tts")
                    try:
                        from qwen_tts import Qwen3TTSModel

                        fallback_device = "cuda:0" if torch.cuda.is_available() else "cpu"
                        fallback_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
                        logger.info(f"使用原始Qwen3TTSModel加载: device={fallback_device}")
                        self._model = Qwen3TTSModel.from_pretrained(
                            str(self.model_path),
                            device_map=fallback_device,
                            dtype=fallback_dtype,
                            attn_implementation="sdpa",
                        )
                        self.current_device = "cuda" if torch.cuda.is_available() else "cpu"
                    except Exception as e2:
                        import gc
                        import torch as _torch_cleanup
                        logger.error(f"所有TTS模型加载均失败: faster={e}, original={e2}")
                        self._model = None
                        gc.collect()
                        if _torch_cleanup.cuda.is_available():
                            _torch_cleanup.cuda.empty_cache()
                            if hasattr(_torch_cleanup.cuda, "ipc_collect"):
                                _torch_cleanup.cuda.ipc_collect()
                        raise

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _load)

        if get_resource_manager:
            rm = get_resource_manager()
            rm.register_resource_handler(
                "gpu_memory", ResourcePriority.MEDIUM, self.handle_resource_pressure
            )
            logger.info("Registered Qwen3-TTS with ResourceManager (Priority: MEDIUM)")

        self.initialized = True

    async def handle_resource_pressure(self, action: str):
        if action == "release":
            if self.current_device == "cpu":
                return
            if self._is_generating:
                logger.warning(
                    "Ignored resource release request during Qwen3-TTS generation"
                )
                return
            logger.info("Received resource release request. Moving Qwen3-TTS to CPU...")
            await self.move_to_cpu()

    async def move_to_cpu(self):
        # FasterQwen3TTS 不支持动态 CPU/GPU 切换，需要重新加载
        import torch

        if self.current_device == "cpu":
            return True
        async with self._load_lock:

            def _reload():
                # 释放旧模型
                self._model = None
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                # CPU 模式下使用原始 qwen_tts（faster 版本仅支持 CUDA）
                logger.info("FasterQwen3-TTS不支持CPU模式，将使用原始qwen_tts")
                from qwen_tts import Qwen3TTSModel

                self._model = Qwen3TTSModel.from_pretrained(
                    str(self.model_path),
                    device_map="cpu",
                    dtype=torch.float32,
                    attn_implementation="sdpa",
                )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _reload)
            self.current_device = "cpu"
            return True

    async def move_to_gpu(self):
        import torch

        if not torch.cuda.is_available():
            return False
        if self.current_device == "cuda":
            return True
        async with self._load_lock:

            def _reload():
                from faster_qwen3_tts import FasterQwen3TTS

                # 释放旧模型
                self._model = None
                import gc
                gc.collect()
                torch.cuda.empty_cache()

                self._model = FasterQwen3TTS.from_pretrained(
                    str(self.model_path),
                )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _reload)
            self.current_device = "cuda"
            return True

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        # 仅在模型尚未加载到GPU时，在生成前添加VRAM检查
        if self._model is None or self.current_device != "cuda":
            try:
                from core.resource_manager import get_resource_manager
                from config.integrated_config import get_settings
                tts_vram_threshold = get_settings().voice.tts_vram_threshold_mb
                rm = get_resource_manager()
                if rm:
                    gpu_usage = None
                    if hasattr(rm, "get_gpu_free_mb"):
                        free_mem = await rm.get_gpu_free_mb()
                        if free_mem is not None and free_mem < tts_vram_threshold:
                            error_msg = f"Qwen3-TTS生成被跳过：显存不足 (空闲: {free_mem}MB < {tts_vram_threshold}MB)。请关闭其他占用显存的任务或更换轻量模型。"
                            logger.warning(error_msg)
                            raise RuntimeError(error_msg)
                    elif hasattr(rm.monitor, "get_gpu_memory_usage_async"):
                        gpu_usage = await rm.monitor.get_gpu_memory_usage_async()
                        if gpu_usage:
                            used, total = gpu_usage
                            free_mem = total - used
                            if free_mem < tts_vram_threshold:
                                error_msg = f"Qwen3-TTS生成被跳过：显存不足 (空闲: {free_mem}MB < {tts_vram_threshold}MB)。请关闭其他占用显存的任务或更换轻量模型。"
                                logger.warning(error_msg)
                                raise RuntimeError(error_msg)
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"Failed to check VRAM for Qwen3-TTS: {e}")

        if not self._model:
            await self.initialize()

        # 使用动态批处理：将请求加入队列，等待批量处理
        request_id = str(uuid.uuid4())
        # P1-1: 使用 get_running_loop() 替代 get_event_loop()（在 async 函数内）
        future = asyncio.get_running_loop().create_future()

        async with self._batch_lock:
            self._batch_queue.append({
                "id": request_id,
                "text": text,
                "kwargs": kwargs,
                "future": future,
            })
            queue_len = len(self._batch_queue)

            # 如果队列已满，立即触发批处理
            if queue_len >= self._batch_max_size:
                if self._batch_timer:
                    self._batch_timer.cancel()
                    self._batch_timer = None
                self._spawn_batch_task(self._process_batch())
            elif queue_len == 1:
                # 第一个请求，启动定时器
                # P1-1: 使用 get_running_loop() 替代 get_event_loop()
                self._batch_timer = asyncio.get_running_loop().call_later(
                    self._batch_max_wait,
                    lambda: self._spawn_batch_task(self._process_batch())
                )

        # 等待批处理完成
        try:
            result = await future
            return result
        except Exception as e:
            logger.error(f"批处理请求失败: {e}")
            raise

    async def _process_batch(self):
        """处理批处理队列中的所有请求"""
        async with self._batch_lock:
            if not self._batch_queue:
                return

            # 取出所有待处理请求
            batch = self._batch_queue[:self._batch_max_size]
            self._batch_queue = self._batch_queue[self._batch_max_size:]
            self._batch_timer = None

        if len(batch) == 1:
            # 单条请求，直接处理
            await self._process_single(batch[0])
        else:
            # 多条请求，逐条处理（faster-qwen3-tts 不支持批量推理）
            logger.info(f"Qwen3-TTS批量处理: {len(batch)}条请求")
            for item in batch:
                await self._process_single(item)

    async def _process_single(self, item: dict):
        """处理单条请求"""
        try:
            result = await self._do_synthesize(
                item["text"], **item["kwargs"]
            )
            item["future"].set_result(result)
        except Exception as e:
            item["future"].set_exception(e)

    async def _do_synthesize(self, text: str, **kwargs) -> Optional[bytes]:
        """实际执行单条合成"""
        self._is_generating = True
        try:
            settings = get_settings()
            default_ref_audio = settings.voice.reference_audio
            base_path = str(get_project_root())
            if not default_ref_audio:
                default_ref_audio = os.path.join(
                    base_path, "ref_audio", "female", "ref_calm.wav"
                )
            elif not os.path.isabs(default_ref_audio):
                default_ref_audio = os.path.join(base_path, default_ref_audio)

            ref_audio = (
                kwargs.get("ref_audio_path")
                or kwargs.get("reference_audio")
                or default_ref_audio
            )
            language = kwargs.get("language") or kwargs.get("text_lang") or "Chinese"
            ref_text = kwargs.get("ref_text")
            xvec_only = bool(kwargs.get("x_vector_only_mode"))

            # 如果未提供ref_text但存在.txt文件，则自动加载
            if not ref_text and not xvec_only and ref_audio:
                txt_path = os.path.splitext(str(ref_audio))[0] + ".txt"
                if os.path.exists(txt_path):
                    try:
                        with open(txt_path, "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                        logger.info(
                            f"Auto-loaded ref_text for Qwen3-TTS: {ref_text[:20]}..."
                        )
                    except Exception:
                        pass

            # 如果仍无ref_text，回退到x_vector_only以避免幻觉
            if not ref_text and not xvec_only:
                logger.warning(
                    "No ref_text provided for Qwen3-TTS and no accompanying .txt found. Switching to x_vector_only mode."
                )
                xvec_only = True

            # 语言代码映射
            lang_map = {
                "zh": "chinese", "en": "english", "ja": "japanese",
                "yue": "cantonese", "ko": "korean", "fr": "french",
                "de": "german", "it": "italian", "es": "spanish",
                "pt": "portuguese", "ru": "russian",
                "mix": "auto", "all_zh": "chinese", "all_ja": "japanese",
            }

            text_lang_param = language.lower()
            if "mixed" in text_lang_param or "auto" in text_lang_param:
                text_lang_param = "auto"
            else:
                text_lang_param = lang_map.get(text_lang_param, text_lang_param)

            import soundfile as sf
            import io

            def _infer():
                gen_kwargs = {
                    "max_new_tokens": kwargs.get("max_new_tokens", 4096),
                    "repetition_penalty": kwargs.get("repetition_penalty", 1.1),
                    "temperature": kwargs.get("temperature", 0.7),
                    "top_p": kwargs.get("top_p", 0.8),
                }

                # FasterQwen3TTS 用 xvec_only，原始 Qwen3TTSModel 用 x_vector_only_mode
                is_faster = hasattr(self._model, 'predictor_graph')
                xvec_param = "xvec_only" if is_faster else "x_vector_only_mode"

                wavs, sr = self._model.generate_voice_clone(
                    text=text,
                    language=text_lang_param,
                    ref_audio=str(ref_audio),
                    ref_text=(None if xvec_only else ref_text),
                    **{xvec_param: xvec_only},
                    **gen_kwargs,
                )
                buf = io.BytesIO()
                sf.write(buf, wavs[0], sr, format="WAV")
                return buf.getvalue()

            loop = asyncio.get_running_loop()
            if get_resource_lock:
                async with get_resource_lock().acquire("TTS", reject_if_full=True):
                    return await loop.run_in_executor(self._executor, _infer)
            return await loop.run_in_executor(self._executor, _infer)
        finally:
            self._is_generating = False

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        if sf is None:
            return np.zeros(0, dtype=np.float32)
        audio_bytes = await self.synthesize_bytes(text, **kwargs)
        if not audio_bytes:
            return np.zeros(0, dtype=np.float32)
        import io

        data, _sr = sf.read(io.BytesIO(audio_bytes))
        return data.astype(np.float32)

    async def shutdown(self):
        self._model = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        await super().shutdown()
