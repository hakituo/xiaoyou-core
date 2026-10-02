"""上传图片优化：保留原格式、修 EXIF 方向、后缀与内容一致。

回归背景：
- 旧实现一律存 JPEG 却沿用原后缀，上传 PNG 会得到「.png 文件名 + JPEG 字节」，
  透明通道被静默丢掉、静态服务按后缀发出错误的 Content-Type。
- 旧实现缩放时既不带 EXIF 也不旋转像素，手机竖拍照片（orientation 6/8）会显示成躺倒的。
"""

import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image

from core.image import image_utils


def _png_bytes(size=(2400, 1200), mode="RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_orientation(size=(2000, 1000), orientation=6) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, (0, 128, 255))
    exif = img.getexif()
    exif[274] = orientation  # 274 = Orientation
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    """把落盘目录指到临时目录，避免污染真实 output/image/uploads。"""
    monkeypatch.setattr(image_utils, "get_project_root", lambda: tmp_path)
    return tmp_path


def test_png_keeps_png_and_alpha(upload_root):
    saved = Path(asyncio.run(image_utils.save_upload_image(_png_bytes(), "sticker.png")))
    assert saved.suffix == ".png"
    with Image.open(saved) as img:
        assert img.format == "PNG", "PNG 不能被存成 JPEG"
        assert img.mode in ("RGBA", "LA"), "透明通道不能被丢掉"
        assert img.size == (1600, 800), "长边应缩到 1600 且保持比例"


def test_exif_orientation_is_applied_to_pixels(upload_root):
    saved = Path(asyncio.run(image_utils.save_upload_image(_jpeg_with_orientation(), "shot.jpg")))
    with Image.open(saved) as img:
        # orientation=6 表示需要旋转 90°：宽高应当互换，说明像素真的被转正了
        assert img.size == (800, 1600)
        assert img.getexif().get(274) is None, "转正后不应再残留方向标记"


def test_bmp_is_converted_to_png_with_matching_suffix(upload_root):
    buf = io.BytesIO()
    Image.new("RGB", (2200, 1000), (10, 200, 10)).save(buf, "BMP")
    saved = Path(asyncio.run(image_utils.save_upload_image(buf.getvalue(), "pic.bmp")))
    assert saved.suffix == ".png", "换格式后后缀必须同步换掉"
    with Image.open(saved) as img:
        assert img.format == "PNG"
    leftovers = list((upload_root / "output" / "image" / "uploads").glob("*.bmp"))
    assert leftovers == [], "换格式后不应留下名实不符的原始副本"


def test_small_image_is_not_upscaled(upload_root):
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (1, 2, 3)).save(buf, "PNG")
    saved = Path(asyncio.run(image_utils.save_upload_image(buf.getvalue(), "small.png")))
    with Image.open(saved) as img:
        assert img.size == (300, 200), "thumbnail 只缩不放"


def test_unsupported_suffix_is_kept_as_is(upload_root):
    saved = Path(asyncio.run(image_utils.save_upload_image(b"hello", "note.txt")))
    assert saved.suffix == ".txt"
    assert saved.read_bytes() == b"hello"


def test_optimize_image_returns_path_with_correct_suffix(tmp_path):
    """直接调用 optimize_image 时，返回值必须指向真实存在的文件。"""
    src = tmp_path / "a.png"
    Image.new("RGBA", (500, 400), (0, 0, 255, 200)).save(src, "PNG")
    result = Path(asyncio.run(image_utils.optimize_image(str(src))))
    assert result.is_file()
    with Image.open(result) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"
