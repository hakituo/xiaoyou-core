# -*- coding: utf-8 -*-
"""媒体（media）域。

提供 TTS（语音合成）、STT（语音识别）、语音列表、参考音频列表、文件上传。
"""

import asyncio
import base64
import hashlib
import io
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, File, Query, UploadFile

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from config.integrated_config import get_settings
from core.utils.time_utils import now_iso, now_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["媒体与语音"])

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


async def _generate_tts_with_async(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
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

@router.post("/stt", summary="语音转文字")
async def stt_endpoint(
    file: UploadFile = File(...),
    model_size: str = Query("base", pattern="^(tiny|base|small|medium|large|large-v2|large-v3)$"),
):
    request_id = str(uuid.uuid4())
    try:
        logger.info(f"收到STT请求, 请求ID: {request_id}, 模型大小: {model_size}")
        audio_data = await file.read()

        async def _try_convert_to_wav_bytes(raw: bytes) -> bytes:
            filename = str(getattr(file, "filename", "") or "")
            content_type = str(getattr(file, "content_type", "") or "").lower()
            ext = Path(filename).suffix.lower().lstrip(".")
            if ext in ("wav", "wave"):
                return raw
            if content_type in ("audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"):
                return raw
            if not raw:
                return raw
            try:
                from pydub import AudioSegment
            except Exception as e:
                raise RuntimeError("服务器缺少音频转码依赖，无法处理 webm/ogg 等格式，请升级前端改为上传 wav") from e
            import tempfile

            def _convert() -> bytes:
                suffix = f".{ext}" if ext else ".bin"
                tmp_path = ""
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                        tmp_path = f.name
                        f.write(raw)
                    fmt = ext or None
                    audio = AudioSegment.from_file(tmp_path, format=fmt)
                    buf = io.BytesIO()
                    audio.export(buf, format="wav")
                    return buf.getvalue()
                finally:
                    if tmp_path:
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

            try:
                return await asyncio.to_thread(_convert)
            except Exception as e:
                msg = str(e)
                if "ffmpeg" in msg.lower():
                    raise RuntimeError("服务器未正确安装 ffmpeg，无法处理 webm/ogg 音频；请升级前端改为上传 wav，或在服务器安装 ffmpeg 并加入 PATH") from e
                raise RuntimeError(f"音频格式不受支持或转码失败: {msg}") from e

        try:
            audio_data = await _try_convert_to_wav_bytes(audio_data)
        except Exception as e:
            return error_response(ErrorCode.STT_AUDIO_FORMAT_UNSUPPORTED, message=str(e), request_id=request_id)

        from core.voice import get_stt_manager
        stt_manager = await get_stt_manager()
        engine = await stt_manager.get_engine()
        result = await engine.transcribe(audio_data)
        return {
            "status": "success",
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
            "language": result.get("language", ""),
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"STT处理失败: {str(e)}", exc_info=True)
        return error_response(ErrorCode.STT_FAILED, message=str(e), request_id=request_id)


# ==================== 语音列表与参考音频 ====================

@router.get("/voice/reference-audio", summary="获取参考音频列表")
async def list_reference_audio():
    try:
        ref_audio_dir = os.path.join(_project_root(), "ref_audio", "female")
        if not os.path.exists(ref_audio_dir):
            return {"status": "success", "files": []}
        files = []
        for f in os.listdir(ref_audio_dir):
            if f.lower().endswith((".wav", ".mp3", ".ogg", ".flac")):
                files.append({"name": f, "path": os.path.join("ref_audio", "female", f).replace("\\", "/")})
        return {"status": "success", "files": files}
    except Exception as e:
        logger.error(f"获取参考音频列表失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/voices", summary="获取可用语音列表")
async def list_voices():
    request_id = str(uuid.uuid4())
    try:
        from core.voice import get_speakers
        spks = await get_speakers()
        voices = [{"id": str(s), "name": str(s)} for s in spks]
        return {
            "status": "success",
            "data": {"voices": voices},
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"获取声音列表失败: {str(e)}", exc_info=True)
        return error_response(ErrorCode.VOICES_ERROR, message="无法获取声音列表", request_id=request_id)


# ==================== TTS ====================

@router.post("/tts", summary="文字转语音")
async def tts(payload: Dict[str, Any] = Body(...)):
    request_id = str(uuid.uuid4())
    task = None
    try:
        if not isinstance(payload, dict):
            return error_response(ErrorCode.INVALID_PAYLOAD, message="请求体必须是JSON对象", request_id=request_id)
        text = str(payload.get("text", "")).strip()
        if not text:
            return error_response(ErrorCode.EMPTY_TEXT, message="文本不能为空", request_id=request_id)
        if len(text) > 20000:
            text = text[:20000]

        from core.modules.voice.utils.text_processor import TextProcessor
        tp = TextProcessor(max_segment_length=1000)
        cleaned1, markers = tp.extract_markers(text)
        cleaned1 = tp.remove_bracketed(cleaned1)
        cleaned1 = tp.normalize_text(cleaned1)
        cleaned1 = re.sub(r"#([^#]{1,64})#", " ", cleaned1)
        cleaned1 = re.sub(r"\s{2,}", " ", cleaned1).strip()
        try:
            cleaned1 = re.sub(r"([。！？!?])\1+", r"\1", cleaned1)
            cleaned1 = re.sub(r"(\S{6,})\1+", r"\1", cleaned1)
        except Exception:
            pass
        try:
            nm = str(payload.get("assistant_name") or "Aveline")
            cleaned1 = re.sub(r"^\s*(用户)\s*:\s*", "", cleaned1)
            cleaned1 = re.sub(r"^\s*" + re.escape(nm) + r"\s*:\s*", "", cleaned1)
        except Exception:
            pass

        params = payload.copy()
        params.pop("text", None)
        if "speed" in params:
            try:
                params["speed"] = float(params["speed"])
            except Exception:
                params["speed"] = 1.0
        if "pitch" in params:
            try:
                params["pitch"] = float(params["pitch"])
            except Exception:
                params["pitch"] = 1.0

        def _norm_lang(x: str) -> str:
            x = str(x or "").strip()
            return {"中文": "zh", "英文": "en", "日文": "ja", "中英混合": "mix",
                    "zh": "zh", "en": "en", "ja": "ja", "mix": "mix"}.get(x, "zh")

        if "text_language" in params and "text_lang" not in params:
            params["text_lang"] = _norm_lang(params.pop("text_language"))
        elif "text_lang" in params:
            params["text_lang"] = _norm_lang(params["text_lang"])
        if "prompt_language" in params and "prompt_lang" not in params:
            params["prompt_lang"] = _norm_lang(params.pop("prompt_language"))
        elif "prompt_lang" in params:
            params["prompt_lang"] = _norm_lang(params["prompt_lang"])
        if "speed" not in params and "speed" in markers:
            params["speed"] = float(markers.get("speed", 1.0))
        if "pitch" not in params and "pitch" in markers:
            params["pitch"] = float(markers.get("pitch", 1.0))
        if "style" not in params and "style" in markers:
            params["style"] = markers.get("style")
        for k in ("xfade_ms", "pause_second", "noise_gate_threshold", "hp_cut", "lp_cut", "fade_ms"):
            if k in payload:
                params[k] = payload[k]
        if "xfade_ms" not in params:
            params["xfade_ms"] = 20
        if "pause_second" not in params:
            params["pause_second"] = 0.25
        if "noise_gate_threshold" not in params:
            params["noise_gate_threshold"] = 0.006
        if "hp_cut" not in params:
            params["hp_cut"] = 100.0
        if "lp_cut" not in params:
            params["lp_cut"] = 6000.0
        if "fade_ms" not in params:
            params["fade_ms"] = 20
        if "downsample_sr" in params and not params["downsample_sr"]:
            params.pop("downsample_sr", None)

        text = cleaned1
        
        # 提取 voice 参数（角色名，用于音色选择）
        voice = str(payload.get("voice", "")).strip() or "Aveline"
        params["voice"] = voice
        logger.info(f"TTS request: voice={voice}, text[:50]={text[:50]}")
        
        from core.core_engine.config_manager import ConfigManager
        timeout_seconds = ConfigManager().get("limits.tts_timeout", 120)

        task = asyncio.create_task(_generate_tts_with_async(text=text, params=params))
        result = await asyncio.wait_for(task, timeout=timeout_seconds)
        return {
            "status": "success",
            "data": result,
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except asyncio.TimeoutError:
        try:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception:
            pass
        return error_response(ErrorCode.TTS_TIMEOUT, message="语音合成超时", request_id=request_id)
    except Exception as e:
        logger.error(f"TTS生成失败: {str(e)}", exc_info=True)
        return error_response(ErrorCode.TTS_FAILED, message=str(e) or "语音合成失败", request_id=request_id)


# ==================== 文件上传 ====================

@router.post("/upload", summary="上传文件（图片 / 音频 / 文档）")
async def upload_file(file: UploadFile = File(...)):
    request_id = str(uuid.uuid4())
    try:
        content_type = str(getattr(file, "content_type", "") or "").lower()
        original_name = os.path.basename(str(getattr(file, "filename", "") or "file"))
        content = await file.read()

        if content_type.startswith("image/"):
            from core.image.image_utils import save_upload_image, get_image_url
            fpath = await save_upload_image(content, original_name)
            rel = get_image_url(fpath)
        else:
            ext = os.path.splitext(original_name)[1]
            base_out = Path(_project_root()) / "output"
            if content_type.startswith("audio/"):
                out_dir = base_out / "voice" / "uploads"
            else:
                out_dir = base_out / "uploads"
            os.makedirs(str(out_dir), exist_ok=True)
            short_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", os.path.splitext(original_name)[0])[:40].strip("_")
            name_part = short_name or "file"
            fname = f"upload_{now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{name_part}{ext}"
            fpath = os.path.join(str(out_dir), fname)

            def _write() -> None:
                with open(fpath, "wb") as f:
                    f.write(content)
            await asyncio.to_thread(_write)

            rel_path = Path(fpath)
            project_root = Path(_project_root())
            try:
                rel = str(rel_path.relative_to(project_root)).replace("\\", "/")
            except Exception:
                rel = str(rel_path).replace("\\", "/")

        return {
            "status": "success",
            "data": {
                "file_path": rel,
                # Android 端 FileUploadManager 解析 file_url / url 字段，
                # 补充该字段避免上传后图片 URL 为空导致无法显示。
                "file_url": rel,
            },
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}", exc_info=True)
        return error_response(ErrorCode.UPLOAD_FAILED, message="文件上传失败", request_id=request_id)
