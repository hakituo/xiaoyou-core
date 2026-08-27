#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火山引擎（字节跳动）TTS 引擎
支持多角色/多音色克隆配置

认证方式：
- 新版 API Key：直接通过 x-api-key header
- 旧版 AppID + Token：通过 appid + token 字段

使用方式：
    engine = VolcanoTTSEngine(
        api_key="your_api_key",
        appid="your_appid",          # 旧版需要
        model="S_default_voice",     # 默认音色
        voice_map={"Ling": "S_LvHb6zN62", "Aveline": "S_HbG6m9272"},
        key_map={
            "Aveline": {"api_key": "another_key"}
        }
    )
    # 通过 voice 参数选择角色
    audio = await engine.synthesize("你好", voice="Ling")
"""

import asyncio
import io
import os
import uuid
from typing import Dict, Optional, Tuple

import aiohttp
import numpy as np

from core.utils.logger import get_logger
from core.voice.engines.base import TTSEngine

logger = get_logger("VOLCANO_TTS")

_VOICE_ALIAS_MAP = {
    "aveline": "Aveline",
    "七濑澪": "Aveline",
    "七濑 澪": "Aveline",
    "七濑": "Aveline",
    "澪": "Aveline",
    "小澪": "Aveline",
    "澪姐": "Aveline",
    "Ling": "Ling",
    "ling": "Ling",
    "玲玲": "Ling",
    "小玲": "Ling",
    "玲姐": "Ling",
    "妹妹": "Ling",
    "罗欢": "罗欢",
    "luohuan": "罗欢",
}


class VolcanoTTSEngine(TTSEngine):
    """
    火山引擎 TTS 引擎
    支持通过 voice 参数切换不同角色的克隆音色。
    """

    BASE_URL = "https://openspeech.bytedance.com/api/v1/tts"

    def __init__(
        self,
        api_key: Optional[str] = None,
        appid: Optional[str] = None,
        model: Optional[str] = None,
        voice_map: Optional[Dict[str, str]] = None,
        key_map: Optional[Dict[str, Dict[str, str]]] = None,
    ):
        super().__init__()
        self.default_api_key = api_key or os.getenv("VOLC_API_KEY")
        self.default_appid = appid or os.getenv("VOLC_APPID")
        self.default_voice = model or "zh_female_qingxin"
        self.voice_map = voice_map or {}
        self.key_map = key_map or {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock: Optional[asyncio.Lock] = None
        self._session_loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Session 管理
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session and not self._session.closed and self._session_loop is loop:
            return self._session

        if self._session_lock is None or self._session_loop is not loop:
            self._session_lock = asyncio.Lock()

        async with self._session_lock:
            if (
                self._session
                and not self._session.closed
                and self._session_loop is loop
            ):
                return self._session

            if (
                self._session
                and not self._session.closed
                and self._session_loop is not loop
            ):
                try:
                    await self._session.close()
                except Exception:
                    pass

            connector = aiohttp.TCPConnector(
                limit=32,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=timeout
            )
            self._session_loop = loop
            return self._session

    # ------------------------------------------------------------------
    # Voice / Key 解析
    # ------------------------------------------------------------------

    def _resolve_voice(
        self, voice_name: Optional[str] = None
    ) -> Tuple[str, Optional[str], str]:
        """
        根据 voice 名称解析出 (api_key, appid, voice_id)。
        """
        voice_name = self._normalize_voice_name(voice_name or self.default_voice)

        # 1. 查找音色映射
        voice_id = self.voice_map.get(voice_name, voice_name)

        # 2. 查找认证信息映射
        key_cfg = self.key_map.get(voice_name, {})
        logger.info(f"  _resolve_voice: voice_name={voice_name}, key_cfg={key_cfg}")
        api_key = key_cfg.get("api_key") or self.default_api_key
        appid = key_cfg.get("appid") or self.default_appid

        # 3. 兜底：如果 voice_name 没有独立的 key_map，使用默认
        if not api_key:
            api_key = self.default_api_key
        if not appid and voice_name not in self.key_map:
            appid = self.default_appid

        return api_key, appid, voice_id

    @staticmethod
    def _normalize_voice_name(voice_name: Optional[str]) -> str:
        """把角色别名归一化到配置里的权威音色键。"""
        text = str(voice_name or "").strip()
        if not text:
            return text
        return _VOICE_ALIAS_MAP.get(text, _VOICE_ALIAS_MAP.get(text.lower(), text))

    # ------------------------------------------------------------------
    # TTSEngine 接口
    # ------------------------------------------------------------------

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        logger.info(
            f"Volcano TTS Engine initialized (default_voice={self.default_voice}, "
            f"voices={list(self.voice_map.keys())})"
        )

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        audio_bytes = await self.synthesize_bytes(text, **kwargs)
        if not audio_bytes:
            return np.array([], dtype=np.float32)
        return self._decode_mp3(audio_bytes)

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        voice_name = kwargs.get("voice", self.default_voice)
        speed = kwargs.get("speed", 1.0)
        api_key, appid, voice_id = self._resolve_voice(voice_name)

        # 出于安全考虑，不再在日志中输出 api_key 任何片段
        logger.info(
            "Volcano TTS synthesize: voice_name=%s, voice_id=%s, api_key_len=%d, has_appid=%s",
            voice_name, voice_id, len(api_key or ""), bool(appid),
        )
        logger.info(f"  voice_map={self.voice_map}")
        logger.info(f"  key_map keys={list(self.key_map.keys())}")

        if not api_key:
            logger.warning("Volcano TTS: api_key 为空，无法合成")
            return None

        reqid = str(uuid.uuid4())
        payload = {
            "app": {"cluster": "volcano_icl"},
            "user": {"uid": "user_1"},
            "audio": {
                "voice_type": voice_id,
                "encoding": "mp3",
                "speed_ratio": float(speed),
            },
            "request": {
                "reqid": reqid,
                "text": text,
                "operation": "query",
            },
        }

        # appid 是必须的
        payload["app"]["appid"] = appid
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }

        try:
            session = await self._get_session()
            async with session.post(
                self.BASE_URL, json=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        f"Volcano TTS 请求失败: {resp.status} | {body[:200]}"
                    )
                    return None

                content_type = resp.headers.get("Content-Type", "")
                # 返回的是 JSON，音频在 data 字段（base64）
                if "json" in content_type:
                    result = await resp.json()
                    code = result.get("code")
                    if code != 3000:
                        logger.warning(
                            f"Volcano TTS API 错误: code={code}, msg={result.get('message')}"
                        )
                        return None
                    import base64
                    b64_data = result.get("data")
                    if b64_data:
                        return base64.b64decode(b64_data)
                    logger.warning("Volcano TTS: data 字段为空")
                    return None
                else:
                    # 直接返回二进制（理论上火山引擎 v1 不会走这条，但兼容）
                    return await resp.read()

        except Exception as e:
            logger.error(f"Volcano TTS 合成异常: {e}")
            return None

    async def shutdown(self):
        try:
            if self._session and not self._session.closed:
                await self._session.close()
        except Exception:
            pass
        self._session = None
        self._session_loop = None
        await super().shutdown()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_mp3(mp3_bytes: bytes) -> np.ndarray:
        """
        尝试将 MP3 bytes 解码为 numpy float32 数组。
        优先使用 soundfile，若失败则尝试 ffmpeg。
        """
        if not mp3_bytes:
            return np.array([], dtype=np.float32)

        # 1. 尝试 soundfile（需要 libsndfile 支持 MP3）
        try:
            import soundfile as sf
            data, sr = sf.read(io.BytesIO(mp3_bytes))
            return data.astype(np.float32)
        except Exception:
            pass

        # 2. 尝试 ffmpeg
        # P0-19: 添加 timeout 防止 ffmpeg pipe 阻塞导致 TTS 合成流程卡死
        try:
            import subprocess
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-i", "pipe:0",
                    "-f", "f32le",
                    "-acodec", "pcm_f32le",
                    "-ar", "24000",
                    "-ac", "1",
                    "pipe:1",
                ],
                input=mp3_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if proc.returncode == 0 and proc.stdout:
                audio = np.frombuffer(proc.stdout, dtype=np.float32)
                return audio
        except subprocess.TimeoutExpired:
            logger.warning("Volcano TTS: ffmpeg 解码超时（30s），返回空数组")
        except Exception:
            pass

        logger.warning("Volcano TTS: MP3 解码失败，返回空数组")
        return np.array([], dtype=np.float32)
