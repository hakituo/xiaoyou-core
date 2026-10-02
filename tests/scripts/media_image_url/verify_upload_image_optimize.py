"""验证上传图片优化：保留原格式 / 修 EXIF 方向 / 后缀与内容一致。

全部在临时目录里跑，不读也不写真实的 output/image/uploads。
运行：venv_core/Scripts/python.exe tests/scripts/media_image_url/verify_upload_image_optimize.py
"""

import asyncio
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PIL import Image  # noqa: E402

from core.image import image_utils  # noqa: E402


def _png(size=(2400, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


def _rotated_jpeg(size=(2000, 1000)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, (0, 128, 255))
    exif = img.getexif()
    exif[274] = 6  # Orientation = 6：需要顺时针转 90°
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-upload-image-") as temp:
        root = Path(temp)
        with patch.object(image_utils, "get_project_root", return_value=root):
            # 1. PNG 保持 PNG，透明通道不丢
            saved = Path(asyncio.run(image_utils.save_upload_image(_png(), "sticker.png")))
            with Image.open(saved) as img:
                assert saved.suffix == ".png", saved.suffix
                assert img.format == "PNG", f"PNG 被存成了 {img.format}"
                assert img.mode in ("RGBA", "LA"), f"透明通道丢了，模式={img.mode}"
                assert img.size == (1600, 800), img.size
            print(f"  [OK] PNG 原格式保留 + 透明未丢 + 长边缩到 1600: {saved.name} {img.size}")

            # 2. EXIF 方向被应用到像素
            rotated = Path(asyncio.run(image_utils.save_upload_image(_rotated_jpeg(), "shot.jpg")))
            with Image.open(rotated) as img:
                assert img.size == (800, 1600), f"像素没被转正，尺寸仍为 {img.size}"
                assert img.getexif().get(274) is None, "方向标记应已随转正清除"
            print(f"  [OK] 竖拍照片按 EXIF 转正: 2000x1000 -> {img.size}")

            # 3. BMP 换格式后后缀同步，且不留原始副本
            buf = io.BytesIO()
            Image.new("RGB", (2200, 1000), (10, 200, 10)).save(buf, "BMP")
            converted = Path(asyncio.run(image_utils.save_upload_image(buf.getvalue(), "pic.bmp")))
            assert converted.suffix == ".png", converted.suffix
            assert list((root / "output" / "image" / "uploads").glob("*.bmp")) == []
            print(f"  [OK] BMP 转 PNG 且后缀同步、无残留副本: {converted.name}")

            # 4. 非图片后缀原样保留
            raw = Path(asyncio.run(image_utils.save_upload_image(b"hello", "note.txt")))
            assert raw.read_bytes() == b"hello"
            print(f"  [OK] 非图片后缀原样保留: {raw.name}")

    print("PASS: 上传图片优化行为符合预期")


if __name__ == "__main__":
    main()
