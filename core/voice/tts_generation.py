# -*- coding: utf-8 -*-
"""TTS 生成核心（由 routers/v1/media.py 下沉而来）。

只负责「文本 + 参数 -> 音频 base64」，不含 HTTP 语义；
路由层与 benchmark 等调用方通过 media.py 的兼容导出使用，保持既有调用方式不变。"""

import asyncio
import base64
import hashlib
import io
import logging
import os
import time
import uuid
from typing import Any, Dict
from config.integrated_config import get_settings
from core.utils.time_utils import now_str

logger = logging.getLogger(__name__)

_tts_prompt_text_cache: Dict[str, str] = {}


def _project_root() -> str:
    from core.utils.common import get_project_root
    return str(get_project_root())


def _project_root_path():
    from core.utils.common import get_project_root
    return get_project_root()


def _voice_dir() -> str:
    d = os.path.join(_project_root(), "output", "voice")
    os.makedirs(d, exist_ok=True)
    return d


async def generate_tts_with_async(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """TTS 核心生成函数（保留此函数名以兼容 benchmark_llm 等外部引用）。"""
    t_start = time.perf_counter()
    base_dir = _project_root()
    ref_wav = params.get("speaker_wav") or params.get("reference_audio")

    if isinstance(ref_wav, str):
        token = ref_wav.strip()
        if token.lower() in {"default", "female"}:
            ref_wav = ""
        elif token.isdigit():
            idx = int(token) - 1
            ref_audio_dir = os.path.join(base_dir, "ref_audio", "female")
            try:
                candidates = []
                if os.path.exists(ref_audio_dir):
                    for f in os.listdir(ref_audio_dir):
                        if str(f).lower().endswith((".wav", ".mp3", ".ogg", ".flac", ".m4a")):
                            candidates.append(os.path.join(ref_audio_dir, f))
                candidates.sort(key=lambda p: os.path.basename(p).lower())
                if 0 <= idx < len(candidates):
                    ref_wav = candidates[idx]
                else:
                    ref_wav = ""
            except Exception:
                ref_wav = ""

    if not ref_wav:
        default_ref = os.path.join(base_dir, "ref_audio", "female", "ref_calm.wav")
        ref_wav = os.environ.get("XIAOYOU_TTS_DEFAULT_REF_WAV") or default_ref

    if ref_wav and not os.path.exists(ref_wav):
        potential = os.path.join(base_dir, "ref_audio", "female", os.path.basename(ref_wav))
        if os.path.exists(potential):
            ref_wav = potential

    if not ref_wav or not os.path.exists(ref_wav):
        logger.warning(f"参考音频不存在: {ref_wav}")
        default_ref = os.path.join(base_dir, "ref_audio", "female", "ref_calm.wav")
        if os.path.exists(default_ref):
            ref_wav = default_ref

    settings = get_settings()
    ref_wav_for_prompt = ref_wav

    async def _ensure_mono_ref_wav(path: str) -> str:
        if not path or not os.path.exists(path):
            return path
        if not str(path).lower().endswith(".wav"):
            return path
        try:
            import soundfile as sf
            info = await asyncio.to_thread(sf.info, path)
            if int(getattr(info, "channels", 1) or 1) <= 1:
                return path
        except Exception:
            return path
        try:
            abs_path = os.path.abspath(path)
            try:
                mtime = os.path.getmtime(abs_path)
            except Exception:
                mtime = 0.0
            cache_root = settings.model.cache_dir or "cache"
            cache_root_path = cache_root if os.path.isabs(cache_root) else str((_project_root_path() / cache_root).resolve())
            out_dir = os.path.join(cache_root_path, "tts_ref_mono")
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception:
                return path
            digest = hashlib.md5(f"{abs_path}|{mtime:.6f}".encode("utf-8")).hexdigest()
            out_path = os.path.join(out_dir, f"{digest}_mono.wav")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return out_path

            def _convert() -> None:
                import soundfile as sf
                data, sr = sf.read(abs_path, always_2d=True, dtype="float32")
                if data.size == 0:
                    raise RuntimeError("empty wav")
                mono = data.mean(axis=1)
                sf.write(out_path, mono, int(sr), format="WAV", subtype="PCM_16")

            await asyncio.to_thread(_convert)
            return out_path if os.path.exists(out_path) else path
        except Exception:
            return path

    tts_conf = settings.voice.tts
    auto_prompt_text = bool(
        getattr(tts_conf, "auto_prompt_text", False)
        or getattr(tts_conf, "auto_prompt_text_from_ref", False)
        or os.environ.get("XIAOYOU_TTS_AUTO_PROMPT_TEXT", "").strip().lower() in ("1", "true", "yes", "on")
    )

    prompt_text = params.get("prompt_text")
    if not prompt_text and ref_wav_for_prompt and os.path.exists(ref_wav_for_prompt):
        ref_wav_abs = os.path.abspath(ref_wav_for_prompt)
        try:
            ref_mtime = os.path.getmtime(ref_wav_abs)
        except Exception:
            ref_mtime = 0.0
        cache_key = f"{ref_wav_abs}|{ref_mtime:.6f}"
        cached_prompt = _tts_prompt_text_cache.get(cache_key)
        if cached_prompt:
            prompt_text = cached_prompt
        else:
            base_path = os.path.splitext(ref_wav_abs)[0]
            for ext in [".txt", ".lab"]:
                txt_path = base_path + ext
                if os.path.exists(txt_path):
                    try:
                        with open(txt_path, "r", encoding="utf-8") as f:
                            prompt_text = f.read().strip()
                        if prompt_text:
                            break
                    except Exception:
                        pass

            if not prompt_text:
                cache_root = settings.model.cache_dir or "cache"
                cache_root_path = cache_root if os.path.isabs(cache_root) else str((_project_root_path() / cache_root).resolve())
                prompt_cache_dir = os.path.join(cache_root_path, "tts_prompt_text")
                try:
                    os.makedirs(prompt_cache_dir, exist_ok=True)
                except Exception:
                    prompt_cache_dir = ""
                prompt_cache_file = ""
                if prompt_cache_dir:
                    digest = hashlib.md5(ref_wav_abs.encode("utf-8")).hexdigest()
                    prompt_cache_file = os.path.join(prompt_cache_dir, f"{digest}.txt")
                if prompt_cache_file and os.path.exists(prompt_cache_file):
                    try:
                        with open(prompt_cache_file, "r", encoding="utf-8") as f:
                            prompt_text = f.read().strip()
                    except Exception:
                        prompt_text = None

            if not prompt_text and auto_prompt_text:
                try:
                    logger.info(f"未找到参考音频提示文本，开始自动识别: {ref_wav_abs}")
                    from core.voice import get_stt_manager
                    stt_mgr = await get_stt_manager()
                    stt_engine = await stt_mgr.get_engine()

                    def _read_ref_audio() -> bytes:
                        with open(ref_wav_abs, "rb") as f:
                            return f.read()

                    audio_bytes = await asyncio.to_thread(_read_ref_audio)
                    res = await stt_engine.transcribe(audio_bytes)
                    if res and res.get("text"):
                        prompt_text = str(res.get("text") or "").strip()
                        if prompt_text and prompt_cache_file:
                            try:
                                def _write_prompt_cache() -> None:
                                    with open(prompt_cache_file, "w", encoding="utf-8") as f:
                                        f.write(prompt_text)
                                await asyncio.to_thread(_write_prompt_cache)
                            except Exception as e:
                                logger.warning(f"写入 prompt_text 缓存失败: {e}")
                except Exception as e:
                    logger.warning(f"自动识别提示文本失败: {e}")
            elif not prompt_text and not auto_prompt_text:
                logger.info("未提供 prompt_text，且未启用参考音频自动识别，跳过 STT 提示文本生成")

            if prompt_text:
                _tts_prompt_text_cache[cache_key] = prompt_text

    t_prompt_done = time.perf_counter()

    rm = None
    try:
        from core.voice import get_tts_manager
        mgr = await get_tts_manager()
        await mgr.get_engine()
        try:
            from core.resource_manager import get_resource_manager
            rm = get_resource_manager()
            if rm is not None:
                rm.mark_model_loaded("tts_engine", True)
        except Exception:
            rm = None

        weights_path = params.get("gpt_sovits_weights")
        if weights_path and weights_path.lower() != "default" and hasattr(mgr.engine, "set_gpt_weights"):
            try:
                is_audio = any(weights_path.lower().endswith(ext) for ext in [".wav", ".mp3", ".ogg", ".flac", ".m4a"])
                if is_audio:
                    logger.debug(f"Ignoring set_gpt_weights for audio file: {weights_path}")
                elif "." in weights_path or "/" in weights_path or "\\" in weights_path:
                    logger.info(f"Switching GPT-SoVITS weights to: {weights_path}")
                    await mgr.engine.set_gpt_weights(weights_path)
                else:
                    logger.debug(f"Skipping set_gpt_weights for non-path ID: {weights_path}")
            except Exception as w_err:
                logger.warning(f"Failed to switch GPT-SoVITS weights: {w_err}")

        def _map_lang(lang):
            lang_lower = str(lang or "zh").lower()
            if "en" in lang_lower:
                return "en"
            if "ja" in lang_lower:
                return "ja"
            return "zh"

        ref_wav_for_engine = await _ensure_mono_ref_wav(ref_wav)
        clone_params = {
            "text": text,
            "reference_audio": ref_wav_for_engine,
            "text_lang": _map_lang(params.get("text_lang")),
            "prompt_text": prompt_text,
            "prompt_lang": _map_lang(params.get("prompt_lang")),
            "speed": float(params.get("speed", 1.0)),
            "top_k": int(params.get("top_k", 15)),
            "top_p": float(params.get("top_p", 1.0)),
            "temperature": float(params.get("temperature", 1.0)),
            "pitch": float(params.get("pitch", 1.0)),
        }
        
        # 添加 voice 参数（角色名）
        voice = params.get("voice", "")
        if voice:
            clone_params["voice"] = voice
        logger.info(f"_generate_tts_with_async: voice={voice}, clone_params keys={list(clone_params.keys())}")

        t_synth_start = time.perf_counter()
        audio_bytes = None
        clone_kwargs = dict(clone_params)
        clone_kwargs.pop("text", None)
        try:
            audio_bytes = await asyncio.wait_for(mgr.synthesize_bytes(text, **clone_kwargs), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("TTS生成超时 (300s)")
            raise RuntimeError("TTS生成超时")
        except Exception:
            audio_bytes = None

        t_synth_done = time.perf_counter()
        is_wav = bool(audio_bytes and len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE")

        if is_wav:
            t_encode_start = time.perf_counter()
            wav_bytes = audio_bytes
            sr = 32000
            try:
                import wave
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    sr = int(wf.getframerate() or sr)
            except Exception:
                pass
            b64 = base64.b64encode(wav_bytes).decode("ascii")
            t_encode_done = time.perf_counter()
        elif audio_bytes:
            # MP3 或其他格式，直接返回（不转换为 WAV）
            t_encode_start = time.perf_counter()
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            sr = 32000  # 默认采样率
            t_encode_done = time.perf_counter()
            logger.info(f"返回 MP3 格式音频，大小: {len(audio_bytes)} bytes")
        else:
            # 没有音频数据，尝试第二次调用
            try:
                audio_data = await asyncio.wait_for(mgr.synthesize(**clone_params), timeout=300.0)
            except asyncio.TimeoutError:
                logger.error("TTS生成超时 (300s)")
                raise RuntimeError("TTS生成超时")
            if audio_data is None or len(audio_data) == 0:
                error_msg = getattr(mgr, "last_error", None) or "TTS生成结果为空"
                raise RuntimeError(error_msg)
            sr = 32000
            if hasattr(mgr, "engine") and mgr.engine and hasattr(mgr.engine, "sample_rate"):
                sr = mgr.engine.sample_rate
            elif hasattr(mgr, "sample_rate"):
                sr = mgr.sample_rate
            import numpy as np
            if np.max(np.abs(audio_data)) < 0.01:
                logger.warning("生成音频似乎是静音 (max amplitude < 0.01)")
            audio_data = np.clip(audio_data, -1.0, 1.0)
            pcm = (audio_data * 32767).astype(np.int16)
            if len(pcm) < sr * 0.1:
                logger.warning(f"生成音频过短: {len(pcm)} samples")
            t_encode_start = time.perf_counter()
            buf = io.BytesIO()
            import soundfile as sf
            sf.write(buf, pcm, sr, format="WAV", subtype="PCM_16")
            wav_bytes = buf.getvalue()
            b64 = base64.b64encode(wav_bytes).decode("ascii")
            t_encode_done = time.perf_counter()

        out_dir = _voice_dir()
        fname = f"tts_{now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.wav"
        fpath = os.path.join(out_dir, fname)
        rel_path = ""
        try:
            def _write_wav_file() -> None:
                with open(fpath, "wb") as f:
                    f.write(wav_bytes)
            await asyncio.to_thread(_write_wav_file)
            rel_path = f"output/voice/{fname}"
        except Exception as e:
            logger.warning(f"保存TTS文件失败: {e}")

        t_total_done = time.perf_counter()
        logger.info("TTS timings (s): prompt=%.3f, synth=%.3f, encode=%.3f, total=%.3f",
                    t_prompt_done - t_start, t_synth_done - t_synth_start,
                    t_encode_done - t_encode_start, t_total_done - t_start)
        # 根据音频格式设置正确的 MIME 类型
        mime_type = "audio/wav" if is_wav else "audio/mpeg"
        return {
            "audio_base64": f"data:{mime_type};base64,{b64}",
            "sample_rate": sr,
            "file_path": rel_path,
            "text": text,
            "source": "core_voice",
        }
    except Exception as e:
        logger.error(f"TTS生成过程中出错: {e}", exc_info=True)
        raise
    finally:
        try:
            if rm is not None:
                rm.mark_model_loaded("tts_engine", False)
        except Exception:
            pass


# ==================== STT ====================

