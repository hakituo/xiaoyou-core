"""更换手机壁纸工具

从指定图库随机选一张图片 (或用指定路径), 缩放后转 base64 下发到手机端设置壁纸。
"""

import base64
import io
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from core.tools.device.base import DeviceToolBase
from core.utils.logger import get_logger

logger = get_logger("device_set_wallpaper")

# 图库根目录映射 (不硬编码 sensitive 名称, 用通用 source 标识)
_IMAGE_ROOTS: Dict[str, str] = {
    "image": r"D:\Air_Plane\image",
    "image1": r"D:\Air_Plane\image1",
}

# 支持的图片扩展名
_SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 缩放参数: 长边不超过此值, 避免图片过大撑爆 WebSocket 帧
_MAX_LONG_EDGE = 1080
_JPEG_QUALITY = 85


class SetWallpaperInput(BaseModel):
    source: str = Field(
        default="image",
        description=(
            "图片来源: 'image' 或 'image1' 两个图库。默认 'image'。"
        ),
    )
    image_path: Optional[str] = Field(
        default=None,
        description=(
            "可选, 指定具体图片的绝对路径。不填则从 source 图库随机选一张。"
        ),
    )


def _list_images(root: str) -> list[str]:
    """列出目录下所有支持的图片文件"""
    p = Path(root)
    if not p.exists() or not p.is_dir():
        return []
    return [
        str(f.resolve())
        for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS
    ]


def _encode_image(path: str) -> Optional[Dict[str, str]]:
    """打开图片, 缩放到长边 1080p, 转 JPEG base64

    Returns:
        {"image_base64": "...", "format": "jpeg", "width": w, "height": h}
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow 未安装, 无法缩放图片")
        return None

    try:
        img = Image.open(path)
        # 转 RGB (JPEG 不支持 RGBA/P 模式)
        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        # 缩放 (保持比例, 长边不超过 _MAX_LONG_EDGE)
        if max(w, h) > _MAX_LONG_EDGE:
            scale = _MAX_LONG_EDGE / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)
            w, h = img.size

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
        data = buf.getvalue()
        b64 = base64.b64encode(data).decode("ascii")

        return {
            "image_base64": b64,
            "format": "jpeg",
            "width": w,
            "height": h,
        }
    except Exception as e:
        logger.error("编码图片失败 %s: %s", path, e, exc_info=True)
        return None


class SetWallpaperTool(DeviceToolBase):
    """更换手机壁纸"""

    name = "set_wallpaper"
    description = (
        "从图库随机选一张图片 (或用指定图片) 设置为手机壁纸。"
        "图片会在后端缩放到 1080p 后下发。仅 Master 可用。"
    )
    short_description = "更换手机壁纸 (仅 Master)"
    args_schema = SetWallpaperInput

    async def _run(
        self,
        source: str = "image",
        image_path: Optional[str] = None,
    ) -> str:
        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        # 决定图片路径
        if image_path and image_path.strip():
            chosen = image_path.strip()
            if not os.path.isfile(chosen):
                return f"指定的图片不存在: {chosen}"
        else:
            root = _IMAGE_ROOTS.get(source)
            if not root:
                return f"未知的图库 source: {source} (可选: {', '.join(_IMAGE_ROOTS.keys())})"
            images = _list_images(root)
            if not images:
                return f"图库 '{source}' 为空或不存在"
            chosen = random.choice(images)

        logger.info("换壁纸: 选中 %s", chosen)

        # 缩放 + 编码
        encoded = _encode_image(chosen)
        if encoded is None:
            return "图片处理失败, 请检查后端日志"

        args = {
            "image_base64": encoded["image_base64"],
            "format": encoded["format"],
        }

        # 下发到手机端
        result = await self._execute("set_wallpaper", args, timeout=20.0)

        status_ok = "已" in result or "成功" in result
        if status_ok:
            return (
                f"已将图片设为手机壁纸。原图: {os.path.basename(chosen)} "
                f"(缩放至 {encoded['width']}x{encoded['height']})"
            )
        return result
