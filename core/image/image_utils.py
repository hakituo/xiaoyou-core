from core.utils.logger import get_logger
import asyncio

from pathlib import Path
from typing import Optional, Tuple

from core.utils.common import get_project_root
from PIL import Image, ImageOps
import aiofiles

logger = get_logger("IMAGE_UTILS")

# 长边上限与 JPEG 质量。
# 取 1600 的理由：本地视觉链路（core/modules/vision/module.py）会把长边压到 1024 再推理，
# 所以超过 1024 对识别没有收益；同时手机全屏看图约 1440px，1600 留一档冗余即可。
# 参考主流聊天应用：微信聊天 ~1080px/q60-70，朋友圈 ~1280px/q75-85，Telegram ~1280px/q75-85。
DEFAULT_MAX_SIZE: Tuple[int, int] = (1600, 1600)
DEFAULT_JPEG_QUALITY = 85

# 后缀 -> 存盘格式。BMP 一律转 PNG（无损且体积小得多），所以优化后可能换后缀。
_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "PNG",
}
_SUFFIX_BY_FORMAT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}

# 会走优化流程的后缀；其余后缀原样保留，不做任何处理。
OPTIMIZABLE_SUFFIXES = tuple(_FORMAT_BY_SUFFIX)


def _flatten_to_rgb(img: "Image.Image") -> "Image.Image":
    """把带透明通道的图压到白底 RGB。

    只有 JPEG 这类不支持透明的目标格式才需要；PNG 走这里会把透明压没，
    所以调用方必须先确认目标格式是 JPEG。
    """
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


async def optimize_image(
    input_path: str,
    output_path: Optional[str] = None,
    max_size: Tuple[int, int] = DEFAULT_MAX_SIZE,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> str:
    """按原格式缩放并压缩图像，返回**实际落盘路径**（可能换后缀）。

    与旧实现的三点区别：
    1. 保留原格式：PNG 仍存 PNG 并保留透明通道，不再一律转 JPEG。
       旧实现把 JPEG 字节写进 .png 文件名，后缀和内容对不上，
       透明通道被静默丢掉、静态服务还会按后缀发出错误的 Content-Type。
    2. 先按 EXIF Orientation 把像素转正再落盘。缩略图不会自动旋转，而存盘又会丢掉 EXIF，
       手机竖拍照片（orientation 6/8）会因此显示成躺倒的。
    3. 后缀与格式严格对应：BMP 转 PNG 后文件名同步换成 .png，不再出现名实不符。

    无法识别的后缀直接返回原路径、不做处理。
    """
    source = Path(input_path)
    target_format = _FORMAT_BY_SUFFIX.get(source.suffix.lower())
    if target_format is None:
        logger.info(f"跳过图像优化（不支持的后缀）: {source.name}")
        return str(input_path)

    final_path = Path(output_path) if output_path else source
    expected_suffix = _SUFFIX_BY_FORMAT[target_format]
    if final_path.suffix.lower() != expected_suffix:
        final_path = final_path.with_suffix(expected_suffix)

    def _process() -> str:
        with Image.open(source) as img:
            # 先转正像素，再缩放；顺序反了会把方向标记一起丢掉。
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None:
                img = transposed

            # 保持比例缩放（thumbnail 只缩不放）
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            save_kwargs = {"optimize": True}
            if target_format == "JPEG":
                img = _flatten_to_rgb(img)
                save_kwargs["quality"] = quality
            elif target_format == "WEBP":
                save_kwargs["quality"] = quality
            elif target_format == "PNG" and img.mode == "CMYK":
                # PNG 不支持 CMYK；RGBA/P 原样保留，透明通道不能丢。
                img = img.convert("RGB")

            img.save(final_path, target_format, **save_kwargs)
            return str(final_path)

    return await asyncio.to_thread(_process)


def get_image_url(file_path: str) -> str:
    """
    将本地文件路径转换为 URL 路径
    """
    path_obj = Path(file_path)
    project_root = get_project_root()

    try:
        # 如果是相对于项目根目录的路径
        if not path_obj.is_absolute():
            rel_path = str(path_obj).replace("\\", "/")
        else:
            rel_path = str(path_obj.relative_to(project_root)).replace("\\", "/")

        # 如果路径包含 output/ 或 static/，则它是可以直接访问的
        if rel_path.startswith("output/"):
            return "/" + rel_path
        if rel_path.startswith("static/"):
            return "/" + rel_path

        return rel_path
    except Exception:
        return str(file_path).replace("\\", "/")


async def save_upload_image(content: bytes, filename: str) -> str:
    """
    保存并优化上传的图像

    返回最终落盘的路径：优化可能改变格式（如 BMP -> PNG），此时以新路径为准，
    并删掉先落盘的原始副本，避免磁盘上留下名实不符的垃圾文件。
    """
    project_root = get_project_root()

    # 确定保存目录
    out_dir = project_root / "output" / "image" / "uploads"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    import uuid
    import re
    from core.utils.time_utils import now_str

    ext = Path(filename).suffix.lower() or ".jpg"
    short_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(filename).stem)[:40].strip("_")
    fname = f"upload_{now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{short_name}{ext}"
    fpath = out_dir / fname

    # 先写入原始文件
    async with aiofiles.open(fpath, mode="wb") as f:
        await f.write(content)

    # 如果是图像，进行优化
    if ext in OPTIMIZABLE_SUFFIXES:
        try:
            optimized_path = await optimize_image(str(fpath))
            if optimized_path and Path(optimized_path) != fpath:
                # 换格式了（如 BMP -> PNG）：删掉先落盘的原始副本
                try:
                    Path(fpath).unlink()
                except OSError as cleanup_error:
                    logger.warning(f"清理优化前的原始文件失败: {cleanup_error}")
                fpath = Path(optimized_path)
        except Exception as e:
            logger.warning(f"图像优化失败: {e}")

    return str(fpath)
