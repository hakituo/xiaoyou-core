"""
验证表情包图片下发改造（Android 端表情包/图片破图修复）

背景：
    后端把表情包编码成 data URI 塞进 image_result 事件；Android 端用的是
    Coil 2.x，没有 data URI 对应的 Fetcher，AsyncImage 直接落到 error 占位图
    （右下角三角感叹号）。改造后：
    - 后端优先把表情包落成静态资源，只下发 URL（/output/image/memes/...）；
    - 前端（Web/Android）按相对路径拼接后端地址加载，可走 HTTP 缓存；
    - Android 端新增 data URI 解码，保证历史消息里的 base64 仍能显示。

本脚本验证：
    1. meme_path_to_url 返回 /output/image/memes/ 下的静态 URL 且文件真实可访问
    2. GIF 保留原后缀（动图不再被强制转 JPEG）
    3. 同一张图重复下发只落一份文件
    4. 静态 URL 转换失败时回退 data URI，且该 data URI 能被 Android 端的
       解码规则（DataUriImage）正确解出图片字节
    5. WebSocket 通道的两个辅助函数行为一致

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\media_image_url\\verify_meme_image_url.py
"""
import base64
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# 1x1 PNG / 1x1 GIF 占位图
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_GIF_BYTES = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)

# Android 端 DataUriImage 的等效规则：^data:([^,;]+)?(;base64)?,(.+)$ + MIME base64 解码
_DATA_URI_RE = re.compile(r"^data:([^,;]+)?(;base64)?,(.+)$", re.IGNORECASE | re.DOTALL)


def android_decode_data_uri(value: str):
    """复刻 clients/frontend/aveline-android .../utils/DataUriImage.kt 的解码逻辑。"""
    match = _DATA_URI_RE.match(value.strip())
    if not match or not match.group(2):
        return None
    payload = "".join(match.group(3).split())
    try:
        raw = base64.b64decode(payload)
    except Exception:
        return None
    return raw or None


def _static_file(url: str) -> Path:
    return ROOT / url.lstrip("/")


def check_static_url_and_file(tmp_dir: Path, published: list):
    from clients.bots.qq.media_tags import meme_path_to_url

    src = tmp_dir / "测试 表情.png"
    src.write_bytes(_PNG_BYTES)

    url = meme_path_to_url(src)
    assert url, "meme_path_to_url 应返回 URL"
    assert url.startswith("/output/image/memes/"), f"URL 前缀不对: {url}"
    dst = _static_file(url)
    assert dst.is_file(), f"静态文件不存在: {dst}"
    assert dst.read_bytes() == _PNG_BYTES, "静态文件内容与源图不一致"
    published.append(dst)
    print(f"  [OK] 静态 URL 生成并落盘: {url}")


def check_gif_ext_kept(tmp_dir: Path, published: list):
    from clients.bots.qq.media_tags import meme_path_to_url

    src = tmp_dir / "动图.gif"
    src.write_bytes(_GIF_BYTES)

    url = meme_path_to_url(src)
    assert url and url.endswith(".gif"), f"GIF 应保留 .gif 后缀，实际: {url}"
    assert _static_file(url).read_bytes() == _GIF_BYTES, "GIF 内容被改动"
    published.append(_static_file(url))
    print(f"  [OK] GIF 保留原格式（不再被转 JPEG）: {url}")


def check_idempotent(tmp_dir: Path, published: list):
    from clients.bots.qq.media_tags import meme_path_to_url

    src = tmp_dir / "复用.png"
    src.write_bytes(_PNG_BYTES)

    first = meme_path_to_url(src)
    dst = _static_file(first)
    published.append(dst)
    dst.write_bytes(b"sentinel")  # 若重复复制会被覆盖，用于检测幂等
    second = meme_path_to_url(src)

    assert first == second, f"同图两次 URL 不一致: {first} != {second}"
    assert dst.read_bytes() == b"sentinel", "同一张图被重复复制（应复用已有文件）"
    print(f"  [OK] 同一张图只落一份静态文件: {first}")


def check_missing_file_returns_none(tmp_dir: Path):
    from clients.bots.qq.media_tags import meme_path_to_url

    assert meme_path_to_url(tmp_dir / "不存在.png") is None, "文件不存在时应返回 None"
    print("  [OK] 文件不存在时返回 None（调用方回退 data URI）")


def check_fallback_data_uri(tmp_dir: Path, published: list):
    """静态 URL 不可用时回退 data URI，且 Android 端能解出这张图。"""
    import clients.bots.qq.media_tags as mt
    from core.services.aveline import stream_orchestrator as so

    src = tmp_dir / "回退.png"
    src.write_bytes(_PNG_BYTES)

    original = mt.meme_path_to_url
    mt.meme_path_to_url = lambda path: None  # 模拟静态 URL 转换失败
    try:
        data_url = so._encode_image_to_data_url(src)
    finally:
        mt.meme_path_to_url = original

    assert data_url and data_url.startswith("data:image/jpeg;base64,"), "兜底应生成 data URI"
    decoded = android_decode_data_uri(data_url)
    assert decoded, "Android 端 DataUriImage 无法解码后端下发的 data URI"
    print(f"  [OK] 回退 data URI 可被 Android 端解码（{len(decoded)} 字节）")

    # 有静态 URL 时优先用 URL
    url = mt.meme_path_to_url(src)
    if url:
        published.append(_static_file(url))
        assert not url.startswith("data:"), "有静态资源时不应再下发 base64"
        print(f"  [OK] 正常路径优先下发静态 URL: {url}")
    else:
        print("  [跳过] 静态 URL 转换不可用，未校验优先顺序")


def check_url_shape_for_clients():
    """Web/Android 都靠 "以 / 开头的相对路径" 拼接后端地址，校验 URL 形状满足约定。"""
    from clients.bots.qq.media_tags import meme_path_to_url

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "a.png"
        src.write_bytes(_PNG_BYTES)
        url = meme_path_to_url(src)
        assert url.startswith("/"), f"相对路径需以 / 开头，实际: {url}"
        assert " " not in url and "\\\\" not in url, f"URL 含空格或反斜杠: {url}"
        # 清理本次产生的静态文件
        dst = _static_file(url)
        if dst.is_file():
            dst.unlink()
    print("  [OK] URL 形状满足前端拼接约定（/ 开头、无空格与反斜杠）")


def check_websocket_helpers(tmp_dir: Path, published: list):
    from core.interfaces.websocket.adapters import streaming as st

    src = tmp_dir / "ws.png"
    src.write_bytes(_PNG_BYTES)

    url = st._meme_path_to_url_safe(src)
    assert url and url.startswith("/output/image/memes/"), f"WS 通道静态 URL 异常: {url}"
    published.append(_static_file(url))

    fallback = st._encode_image_to_data_url(src)
    assert fallback and android_decode_data_uri(fallback), "WS 通道兜底 data URI 不可用"
    assert st._meme_path_to_url_safe(tmp_dir / "不存在.png") is None, "WS 通道不存在文件应返回 None"
    print(f"  [OK] WebSocket 通道辅助函数一致: url={url}")


def main():
    published: list[Path] = []
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        print("验证表情包图片下发改造：")
        check_static_url_and_file(tmp_dir, published)
        check_gif_ext_kept(tmp_dir, published)
        check_idempotent(tmp_dir, published)
        check_missing_file_returns_none(tmp_dir)
        check_fallback_data_uri(tmp_dir, published)
        check_url_shape_for_clients()
        check_websocket_helpers(tmp_dir, published)

    # 清理验证过程中落到 output/image/memes/ 的静态文件
    for f in published:
        if f.exists():
            f.unlink()

    print("\n✅ 表情包图片下发改造验证通过（静态 URL 优先 + data URI 兜底 + 前端可解码）")


if __name__ == "__main__":
    main()
