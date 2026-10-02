"""聊天图片输入辅助。

Android 图片消息使用 ``[图片: /output/image/uploads/xxx]`` 作为轻量附件标记。
本模块负责：
1. 从用户消息中拆出附件路径与真实 caption；
2. 只允许读取后端上传目录内的图片；
3. 把图片编码成 OpenAI 兼容的 data URI，交给统一视觉路由。

这里不判断模型是否支持视觉。模型能力判断统一由
``core.llm.model_capabilities`` / ``vision_router`` 负责，避免两套名单漂移。
"""

from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("ChatImageInput")

_IMAGE_MESSAGE_RE = re.compile(
    r"^\[图片:\s*(?P<path>[^\]\r\n]+)\]\s*(?P<caption>.*)$",
    re.DOTALL,
)
_DEFAULT_IMAGE_TEXT = "（用户发送了一张图片）"
_MAX_IMAGE_BYTES = 16 * 1024 * 1024
_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _normalize_uploaded_image_ref(image_ref: str) -> Optional[str]:
    """把相对地址/完整后端 URL 归一化成上传目录路径。"""
    token = str(image_ref or "").strip().strip('"').strip("'")
    if not token:
        return None

    parsed = urlparse(token)
    if parsed.scheme in {"http", "https"}:
        token = parsed.path
    elif parsed.scheme:
        return None

    normalized = "/" + token.lstrip("/")
    if not normalized.startswith("/output/image/uploads/"):
        return None
    return normalized


def split_chat_image_message(message: Any) -> Tuple[Any, Optional[str]]:
    """拆出 Android 图片附件标记，返回（真实用户文本，图片路径）。"""
    if not isinstance(message, str):
        return message, None

    match = _IMAGE_MESSAGE_RE.match(message.strip())
    if not match:
        return message, None

    image_ref = _normalize_uploaded_image_ref(match.group("path"))
    if image_ref is None:
        return message, None

    caption = str(match.group("caption") or "").strip()
    return caption or _DEFAULT_IMAGE_TEXT, image_ref


def _resolve_uploaded_image_path(image_ref: str) -> Optional[Path]:
    """只解析 ``output/image/uploads`` 目录内的文件，阻止路径穿越。"""
    normalized = _normalize_uploaded_image_ref(image_ref)
    if normalized is None:
        return None

    project_root = Path(get_project_root()).resolve()
    uploads_root = (project_root / "output" / "image" / "uploads").resolve()
    candidate = (project_root / normalized.lstrip("/")).resolve()

    try:
        candidate.relative_to(uploads_root)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in _MIME_BY_SUFFIX:
        return None
    return candidate


async def load_uploaded_image_data_url(image_ref: str) -> Optional[str]:
    """读取已上传图片并编码为标准 ``data:image/...;base64`` URL。"""
    image_path = _resolve_uploaded_image_path(image_ref)
    if image_path is None:
        logger.warning("聊天图片附件路径无效或文件不存在: %s", image_ref)
        return None

    try:
        file_size = image_path.stat().st_size
    except OSError as exc:
        logger.warning("读取聊天图片附件大小失败: %s", exc)
        return None

    if file_size <= 0 or file_size > _MAX_IMAGE_BYTES:
        logger.warning("聊天图片附件大小异常: path=%s size=%d", image_path, file_size)
        return None

    try:
        image_bytes = await asyncio.to_thread(image_path.read_bytes)
    except OSError as exc:
        logger.warning("读取聊天图片附件失败: %s", exc)
        return None

    mime = _MIME_BY_SUFFIX.get(image_path.suffix.lower())
    if not mime:
        return None
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"
