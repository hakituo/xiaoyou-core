# -*- coding: utf-8 -*-
"""媒体域 - 语音端点。

STT 语音识别、参考音频列表、可用音色列表、TTS 语音合成；
TTS 生成逻辑已下沉 core.voice.tts_generation，本文件只做参数清洗与 HTTP 封装。"""

import asyncio
import io
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, Body, File, Query, UploadFile
from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.time_utils import now_iso
from core.voice.tts_generation import (
    _project_root,
    generate_tts_with_async,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["媒体与语音"])

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
    """返回可用音色名列表（客户端音色选择用）。

    权威来源是 app.yaml 的 voice.tts.voice_map：它的 key 就是"用户注册的音色名"
    （妹妹 / Ling / Ye / Aveline / VoiceArtist ...），可直接作为 /api/v1/media/tts 的 voice 参数。

    注意不能直接用 get_speakers()：那返回的是引擎通用 speaker
    （default / female / male / child），不是用户注册的音色，客户端选了也合成不出对应声音。

    同一音色 ID 的多个别名（如 Aveline 与 Aveline 指向同一 ID）按 ID 去重，只保留首个名字。
    """
    request_id = str(uuid.uuid4())
    try:
        from config.voice_config import load_voice_map

        voice_map = load_voice_map()
        seen_voice_ids: set = set()
        voices = []
        for name, voice_id in voice_map.items():
            vid = str(voice_id or "").strip()
            if not vid or vid in seen_voice_ids:
                continue
            seen_voice_ids.add(vid)
            voices.append({"id": str(name), "name": str(name)})

        if not voices:
            # 没配置 voice_map 时回落到引擎通用 speaker，至少不是空列表
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

        # 缓存：同一音色 + 同一文本 + 同一组参数直接复用，不再调用云端 TTS。
        # key 只含影响音频内容的输入，与 request_id 无关；TTL 7 天，超出目录上限按最旧淘汰。
        from core.voice.tts_cache import build_cache_key, load_cached_result, save_cached_result

        cache_key = build_cache_key(text, voice, params)
        cached = load_cached_result(cache_key)
        if cached is not None:
            return {
                "status": "success",
                "data": cached,
                "request_id": request_id,
                "timestamp": now_iso(),
                "cached": True,
            }

        from core.core_engine.config_manager import ConfigManager
        timeout_seconds = ConfigManager().get("limits.tts_timeout", 120)

        task = asyncio.create_task(generate_tts_with_async(text=text, params=params))
        result = await asyncio.wait_for(task, timeout=timeout_seconds)
        save_cached_result(cache_key, result)
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

