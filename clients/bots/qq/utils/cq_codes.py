"""QQ CQ 码构建与 URL/路径工具。"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _to_forward_slashes(path: str) -> str:
    """把 Windows 反斜杠路径转成正斜杠（NapCat 要求）。"""
    return str(path or "").replace("\\", "/")


def _build_cq_image(file_path: str) -> str:
    """构建图片 CQ 码。"""
    return f"[CQ:image,file={_to_forward_slashes(file_path)}]"


def _build_cq_record(file_path: str) -> str:
    """构建语音 CQ 码。"""
    return f"[CQ:record,file={_to_forward_slashes(file_path)}]"


def _build_cq_video(file_path: str) -> str:
    """构建视频 CQ 码（NapCat 支持的 [CQ:video] 格式）。"""
    return f"[CQ:video,file={_to_forward_slashes(file_path)}]"


def _append_query_param(url: str, key: str, value: str) -> str:
    """给 URL 追加查询参数（已存在则不覆盖）。"""
    url = str(url or "").strip()
    key = str(key or "").strip()
    value = str(value or "").strip()
    if not url or not key or not value:
        return url
    try:
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        if q.get(key):
            return url
        q[key] = value
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))
    except Exception:
        return url


def _normalize_qq_face_position(text: str) -> str:
    """规范化 QQ 表情标签位置，确保表情标签在消息末尾。"""
    text = str(text or "")
    face_pattern = r'\s*\[([^\]]*?(?:微笑|难过|生气|疑问|惊讶|害羞|困|委屈)[^\]]*?)\]\s*'
    faces = re.findall(face_pattern, text)
    if not faces:
        return text
    text = re.sub(face_pattern, '', text).strip()
    for face in faces:
        text = text.rstrip() + f' [{face}]'
    return text.strip()
