# -*- coding: utf-8 -*-
"""媒体域 - 文件上传端点。

图片 / 视频 / 音频 / 文档上传后落盘并返回可访问路径。"""

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, File, UploadFile
from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.time_utils import now_iso, now_str
from core.voice.tts_generation import _project_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["媒体与语音"])

@router.post("/upload", summary="上传文件（图片 / 视频 / 音频 / 文档）")
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
            elif content_type.startswith("video/"):
                # 视频单独存 output/video/uploads：/output 已被静态挂载，
                # Android 端 ExoPlayer 拿这个相对地址拼后端地址即可直接播放。
                out_dir = base_out / "video" / "uploads"
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
