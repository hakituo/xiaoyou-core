# -*- coding: utf-8 -*-
"""媒体（media）域聚合路由。

本文件不再直接实现端点，而是作为业务子域的聚合入口：
- media_voice: 语音（/media/stt, /media/voices, /media/voice/reference-audio, /media/tts）
- media_upload: 文件上传（/media/upload）

同时兼容导出 TTS 生成核心：历史上 benchmark_llm 等直接引用
``routers.v1.media._generate_tts_with_async``，这里保留同名别名。
"""

from fastapi import APIRouter

from core.voice.tts_generation import (
    generate_tts_with_async as _generate_tts_with_async,
)

from .media_upload import router as media_upload_router
from .media_voice import router as media_voice_router

router = APIRouter(tags=["媒体与语音"])

# 子路由自带 /media 前缀，本聚合层绝不能再声明 prefix，否则会叠加成 /media/media/*
router.include_router(media_voice_router)
router.include_router(media_upload_router)

__all__ = ["router", "_generate_tts_with_async"]
