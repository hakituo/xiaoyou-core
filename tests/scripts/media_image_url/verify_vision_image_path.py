"""
验证 Android 端发图链路依赖的后端行为。

Android 端发图流程：选图 → /api/v1/media/upload → 拿到相对路径
（/output/image/uploads/xxx.jpg）→ 把它直接交给 /api/v1/vision/describe
的 image_path 做识别 → 识别结果作为用户消息文本发给 chat。

本脚本验证：
    1. 上传接口返回的是 /output/image/uploads/ 下、前端可直接访问的路径
    2. 视觉接口能把这个"上传返回路径"解析成本地文件（否则 Android 端
       传过去只会得到"Invalid image data"）
    3. 路径不存在时视觉接口返回 error，而不是把路径串当成图片数据

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\media_image_url\\verify_vision_image_path.py
"""
import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# 1x1 PNG
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

_VISION_STUB_TEXT = "视觉识别占位结果"


class FakeService:
    """只提供视觉路径解析需要的工程根目录。"""

    def _get_project_root(self):
        return ROOT


def _run_vision(image_data: str) -> dict:
    """跑视觉接口，并把真正的模型调用替换成桩，只验证路径解析。"""
    import core.services.aveline.vision_service as vs

    async def _stub(_service, _image, _prompt):
        return _VISION_STUB_TEXT

    original = vs._execute_vision_task
    vs._execute_vision_task = _stub
    try:
        return asyncio.run(vs.analyze_screen(FakeService(), image_data, "描述这张图片"))
    finally:
        vs._execute_vision_task = original


def check_upload_returns_accessible_path():
    from core.image.image_utils import get_image_url, save_upload_image

    saved = asyncio.run(save_upload_image(_PNG_BYTES, "verify_vision_upload.png"))
    url = get_image_url(saved)
    assert url.startswith("/output/image/uploads/"), f"上传路径格式不符: {url}"
    assert (ROOT / url.lstrip("/")).is_file(), f"上传文件不可访问: {url}"
    print(f"  [OK] 上传返回可直接访问的路径: {url}")
    return ROOT / url.lstrip("/")


def check_vision_accepts_upload_path(upload_file: Path):
    result = _run_vision(str(upload_file).replace("\\", "/"))
    # 相对项目根的路径形式（后端下发给前端的 /output/... 也是这样被解析）
    rel_url = "/" + str(upload_file.relative_to(ROOT)).replace("\\", "/")
    result_rel = _run_vision(rel_url)

    assert result.get("status") == "success", f"绝对路径识别失败: {result}"
    assert result_rel.get("status") == "success", f"相对路径识别失败: {result_rel}"
    assert result_rel.get("description") == _VISION_STUB_TEXT, "识别结果未回传"
    print(f"  [OK] 视觉接口能解析上传路径: {rel_url}")


def check_missing_path_returns_error():
    result = _run_vision("/output/image/uploads/__not_exist__.png")
    assert result.get("status") == "error", f"不存在的文件应返回 error，实际: {result}"
    print("  [OK] 图片不存在时视觉接口返回 error（Android 端据此回退 [图片: url]）")


def main():
    print("验证 Android 发图链路的后端依赖：")
    upload_file = check_upload_returns_accessible_path()
    try:
        check_vision_accepts_upload_path(upload_file)
    finally:
        if upload_file.exists():
            upload_file.unlink()
    check_missing_path_returns_error()
    print("\n✅ 上传路径 + 视觉识别链路验证通过（Android 端可直接传 image_path）")


if __name__ == "__main__":
    main()
