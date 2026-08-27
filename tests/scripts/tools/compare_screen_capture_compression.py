"""
屏幕截图压缩策略对比测试

目的：测试不同压缩策略下，Qwen3-VL 能否看清屏幕细节
- 当前 2.5K 屏（逻辑分辨率 1707x1067，物理分辨率更高）
- 未来 4K 屏
- 平台（siliconflow）不做压缩，只有 256k 上下文限制

测试策略：
1. 原图 PNG（无损，最大细节，基准）
2. 原尺寸 JPEG quality=85（有损但保留尺寸）
3. 缩放到 1920 宽 JPEG q=85（中等压缩）
4. 缩放到 1280 宽 JPEG q=85（较大压缩）
5. 缩放到 1024 宽 JPEG q=80（激进压缩，接近 VL 内部处理尺寸）

每个版本都发给 Qwen3-VL，问同样的问题，对比：
- 文件大小（base64 体积，影响 token 消耗和上传耗时）
- VL 回答质量（能否看清文字、UI 细节、应用名称）
- VL 响应耗时

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\tools\\compare_screen_capture_compression.py
"""

import asyncio
import base64
import os
import sys
import time
from io import BytesIO

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PIL import Image

OUTPUT_DIR = os.path.join(
    _PROJECT_ROOT, "companion_data", "temp", "compression_test"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── 压缩策略定义 ────────────────────────────────────────
def strategy_original_png(img: Image.Image) -> tuple[bytes, str]:
    """原图 PNG 无损"""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "1_original_png"


def strategy_full_jpeg_q85(img: Image.Image) -> tuple[bytes, str]:
    """原尺寸 JPEG q=85"""
    buf = BytesIO()
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "2_fullsize_jpeg_q85"


def strategy_resize_1920_jpeg_q85(img: Image.Image) -> tuple[bytes, str]:
    """缩放到 1920 宽 JPEG q=85"""
    w, h = img.size
    if w > 1920:
        new_h = int(h * 1920 / w)
        img = img.resize((1920, new_h), resample=Image.LANCZOS)
    buf = BytesIO()
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "3_resize_1920_jpeg_q85"


def strategy_resize_1280_jpeg_q85(img: Image.Image) -> tuple[bytes, str]:
    """缩放到 1280 宽 JPEG q=85"""
    w, h = img.size
    if w > 1280:
        new_h = int(h * 1280 / w)
        img = img.resize((1280, new_h), resample=Image.LANCZOS)
    buf = BytesIO()
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "4_resize_1280_jpeg_q85"


def strategy_resize_1024_jpeg_q80(img: Image.Image) -> tuple[bytes, str]:
    """缩放到 1024 宽 JPEG q=80（激进压缩）"""
    w, h = img.size
    if w > 1024:
        new_h = int(h * 1024 / w)
        img = img.resize((1024, new_h), resample=Image.LANCZOS)
    buf = BytesIO()
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=80, optimize=True)
    return buf.getvalue(), "5_resize_1024_jpeg_q80"


STRATEGIES = [
    strategy_original_png,
    strategy_full_jpeg_q85,
    strategy_resize_1920_jpeg_q85,
    strategy_resize_1280_jpeg_q85,
    strategy_resize_1024_jpeg_q80,
]


async def call_vl(image_bytes: bytes, fmt: str, question: str) -> tuple[str, float]:
    """调用 Qwen3-VL 分析图片，返回 (回答文本, 耗时秒)"""
    from core.llm.siliconflow_client import SiliconFlowClient
    from config.integrated_config import get_settings

    settings = get_settings()
    api_key = settings.model.vision.api_key
    vision_model = settings.model.vision.model or "Qwen/Qwen3-VL-235B-A22B-Thinking"

    if not api_key:
        return "[ERROR] 未配置 SILICONFLOW API Key", 0.0

    client = SiliconFlowClient(api_key=api_key, vision_model=vision_model)

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]

    t0 = time.time()
    try:
        result = await client._vision_inference(
            messages, max_tokens=1024, temperature=0.3
        )
        elapsed = time.time() - t0
        if result.get("status") == "success":
            return result.get("text", "").strip(), elapsed
        return f"[ERROR] {result.get('error', '未知错误')}", elapsed
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def main():
    print("=" * 70)
    print("屏幕截图压缩策略对比测试")
    print("=" * 70)

    # 1. 截图
    print("\n[1] 截取当前屏幕...")
    from PIL import ImageGrab

    screenshot = ImageGrab.grab()
    print(
        f"    原始尺寸: {screenshot.size[0]}x{screenshot.size[1]} "
        f"({screenshot.size[0]}x{screenshot.size[1]})"
    )

    # 2. 问题（统一提问，便于对比）
    question = (
        "请详细描述这张电脑屏幕截图的内容。要求：\n"
        "1. 用户在用什么应用/软件？（列出所有可见的应用窗口名称）\n"
        "2. 屏幕上有哪些可见的文字？请尽量逐字读出来（包括标题栏、菜单、按钮文字、"
        "网页标题、文件名等）。\n"
        "3. 如果是代码编辑器，能看到是什么编程语言、什么项目吗？\n"
        "4. 如果是网页/视频，能看到标题或内容吗？\n"
        "5. 整体布局是什么样的？\n"
        "请尽可能详细，不要遗漏任何文字信息。"
    )

    # 3. 对每个策略：压缩 + 调用 VL
    print(f"\n[2] 共 {len(STRATEGIES)} 个压缩策略，逐一测试...\n")
    results = []

    for strategy in STRATEGIES:
        # 压缩
        t_compress_start = time.time()
        img_copy = screenshot.copy()
        img_bytes, label = strategy(img_copy)
        compress_time = time.time() - t_compress_start

        # 保存到磁盘（便于人工查看）
        ext = "png" if "png" in label else "jpg"
        save_path = os.path.join(OUTPUT_DIR, f"{label}.{ext}")
        with open(save_path, "wb") as f:
            f.write(img_bytes)

        size_kb = len(img_bytes) / 1024
        b64_kb = (len(img_bytes) * 4 / 3) / 1024  # base64 膨胀约 4/3

        print(f"─── {label} ───")
        print(f"  文件大小: {size_kb:.1f} KB（base64 约 {b64_kb:.1f} KB）")
        print(f"  压缩耗时: {compress_time*1000:.0f} ms")
        print(f"  保存到: {save_path}")
        print(f"  调用 Qwen3-VL 分析中...")

        # 调用 VL
        fmt = "PNG" if "png" in label else "JPEG"
        answer, elapsed = await call_vl(img_bytes, fmt, question)

        print(f"  VL 响应耗时: {elapsed:.1f} s")
        print(f"  VL 回答:")
        # 缩进显示回答
        for line in answer.split("\n"):
            print(f"    {line}")
        print()

        results.append(
            {
                "label": label,
                "size_kb": size_kb,
                "b64_kb": b64_kb,
                "compress_ms": compress_time * 1000,
                "vl_seconds": elapsed,
                "answer": answer,
                "save_path": save_path,
            }
        )

        # 策略间隔，避免触发限流
        await asyncio.sleep(1.5)

    # 4. 汇总对比
    print("=" * 70)
    print("[汇总对比]")
    print("=" * 70)
    print(
        f"{'策略':<28} {'文件KB':>8} {'b64KB':>8} "
        f"{'压缩ms':>8} {'VL秒':>8}"
    )
    print("-" * 70)
    for r in results:
        print(
            f"{r['label']:<28} {r['size_kb']:>8.1f} {r['b64_kb']:>8.1f} "
            f"{r['compress_ms']:>8.0f} {r['vl_seconds']:>8.1f}"
        )

    print("\n[关键观察建议]")
    print("1. 对比「文件KB」和「VL 回答详细程度」的权衡")
    print("2. 重点看 VL 在哪个压缩级别开始丢失文字细节（应用名/标题/按钮文字）")
    print("3. 4K 屏（3840x2160）的原图体积会是 2.5K 的约 2.4 倍，压缩收益更大")
    print(f"\n所有压缩版本已保存到: {OUTPUT_DIR}")
    print("可手动打开对比画质。")


if __name__ == "__main__":
    asyncio.run(main())
