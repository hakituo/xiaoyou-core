from core.utils.logger import get_logger
import asyncio

from pathlib import Path
from typing import Optional, Tuple

from core.utils.common import get_project_root
from PIL import Image
import aiofiles

logger = get_logger("IMAGE_UTILS")


async def optimize_image(
    input_path: str,
    output_path: Optional[str] = None,
    max_size: Tuple[int, int] = (2048, 2048),
    quality: int = 85,
) -> str:
    """
    优化图像：缩放并压缩
    """
    if output_path is None:
        output_path = input_path

    def _process():
        with Image.open(input_path) as img:
            # 转换为 RGB (处理 RGBA/P 模式)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # 保持比例缩放
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # 保存
            img.save(output_path, "JPEG", quality=quality, optimize=True)
            return output_path

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
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        try:
            await optimize_image(str(fpath))
        except Exception as e:
            logger.warning(f"图像优化失败: {e}")

    return str(fpath)
