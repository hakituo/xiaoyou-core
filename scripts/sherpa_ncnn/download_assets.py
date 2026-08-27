"""下载 sherpa-ncnn Android 集成所需的 .so 库和模型文件。

用途:
- 下载 sherpa-ncnn 官方 Android APK (v2.1.15, arm64-v8a, 中英双语)
- 从 APK 提取 libsherpa-ncnn-jni.so + libncnn.so 到 jniLibs/arm64-v8a/
- 从 GitHub releases 下载 streaming Zipformer small 中英双语模型 tar.bz2 并解压到 assets/

用法:
    venv_core\\Scripts\\python.exe scripts\\sherpa_ncnn\\download_assets.py
    venv_core\\Scripts\\python.exe scripts\\sherpa_ncnn\\download_assets.py --skip-so    # 只下模型
    venv_core\\Scripts\\python.exe scripts\\sherpa_ncnn\\download_assets.py --skip-model # 只下 .so

前置条件:
- 网络可访问 github.com (APK 约 138MB, 模型 tar.bz2 约 70MB)

输出位置:
- .so: clients/frontend/aveline-android/android/app/src/main/jniLibs/arm64-v8a/
- 模型: clients/frontend/aveline-android/android/app/src/main/assets/sherpa_ncnn_models/
       下面的 sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16/96/ 子目录
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

# ============================================================
# 配置
# ============================================================

SHERPA_NCNN_VERSION = "v2.1.15"
# arm64-v8a + 中英双语 APK (兼顾中文识别 + 英文识别, S24 Ultra 是 arm64)
APK_URL = (
    f"https://github.com/k2-fsa/sherpa-ncnn/releases/download/{SHERPA_NCNN_VERSION}/"
    f"sherpa-ncnn-2.1.15-cpu-arm64-v8a-bilingual-en-zh.apk"
)

# 模型: streaming Zipformer small 中英双语 (2023-02-16)
# 从 GitHub releases models tag 下载 tar.bz2 (HF 仓库在国内常 401/308, 改用 GitHub)
# 解压后目录结构: sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16/96/
MODEL_TARBALL_NAME = "sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16.tar.bz2"
MODEL_TARBALL_URL = (
    "https://github.com/k2-fsa/sherpa-ncnn/releases/download/models/"
    + MODEL_TARBALL_NAME
)
MODEL_DIR_NAME = "sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16"

# 项目根目录 (自动定位: scripts/sherpa_ncnn/ 向上两层)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# .so 输出目录
JNILIBS_DIR = (
    PROJECT_ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "main"
    / "jniLibs"
    / "arm64-v8a"
)

# 模型输出根目录 (assets 下, 模型会放在此目录的 MODEL_DIR_NAME/96/ 子目录)
# 与 SherpaNcnnAsrEngine.kt 中给 modelConfig.path 加的 "sherpa_ncnn_models/" 前缀匹配
ASSETS_MODEL_DIR = (
    PROJECT_ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "main"
    / "assets"
    / "sherpa_ncnn_models"
)

# 临时下载目录
TEMP_DIR = PROJECT_ROOT / "companion_data" / "temp" / "sherpa_ncnn"

# 需要从 APK 提取的 .so 文件
SO_FILES = [
    "libsherpa-ncnn-jni.so",
    "libncnn.so",
]

# 模型文件列表 (验证用, 解压后应该在 MODEL_DIR_NAME/96/ 下)
MODEL_FILE_PATTERNS = [
    "encoder_jit_trace-pnnx.ncnn.param",
    "encoder_jit_trace-pnnx.ncnn.bin",
    "decoder_jit_trace-pnnx.ncnn.param",
    "decoder_jit_trace-pnnx.ncnn.bin",
    "joiner_jit_trace-pnnx.ncnn.param",
    "joiner_jit_trace-pnnx.ncnn.bin",
    "tokens.txt",
]


# ============================================================
# 工具函数
# ============================================================

def download_file(url: str, dest: Path) -> bool:
    """下载文件, 用 requests 自动跟随重定向"""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [SKIP] 已存在: {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [下载] {url}")
    print(f"        → {dest}")

    try:
        import requests

        # stream=True 流式下载避免大文件占内存; allow_redirects 自动跟随重定向
        with requests.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=(15, 300),  # (连接超时, 读取超时)
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        ) as resp:
            if resp.status_code != 200:
                print(f"\n  [ERROR] HTTP {resp.status_code}")
                return False

            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 / total
                        print(
                            f"\r  [进度] {downloaded / 1024 / 1024:.1f} / "
                            f"{total / 1024 / 1024:.1f} MB ({pct:.1f}%)",
                            end="",
                            flush=True,
                        )
            print()
        return True
    except Exception as e:
        print(f"\n  [ERROR] 下载失败: {e}")
        if dest.exists():
            dest.unlink()
        return False


def check_model_files_complete(model_dir: Path) -> bool:
    """检查模型目录是否包含所有必需文件且非空"""
    if not model_dir.exists():
        return False
    for pattern in MODEL_FILE_PATTERNS:
        f = model_dir / pattern
        if not f.exists() or f.stat().st_size == 0:
            return False
    return True


# ============================================================
# 步骤 1: 下载并提取 .so 文件
# ============================================================

def download_and_extract_so() -> bool:
    """下载 sherpa-ncnn Android APK 并提取 .so 文件"""
    print("\n=== 步骤 1: 下载 .so 文件 ===")
    print(f"APK URL: {APK_URL}")
    print(f"目标目录: {JNILIBS_DIR}")

    # 检查 .so 是否已存在
    existing = [f for f in SO_FILES if (JNILIBS_DIR / f).exists()]
    if len(existing) == len(SO_FILES):
        print("[SKIP] 所有 .so 文件已存在, 跳过下载")
        return True

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    apk_path = TEMP_DIR / f"sherpa-ncnn-{SHERPA_NCNN_VERSION}-arm64-v8a.apk"

    # 下载 APK (138MB, 可能慢)
    if not apk_path.exists():
        print(f"\n[下载 APK] (约 138MB, 可能需要几分钟...)")
        if not download_file(APK_URL, apk_path):
            print("[ERROR] APK 下载失败")
            return False
    else:
        print(f"[SKIP] APK 已存在: {apk_path.name}")

    # 解压提取 .so
    print(f"\n[解压] 从 APK 提取 .so 文件")
    JNILIBS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            # 列出 lib/arm64-v8a/ 下的所有 .so
            so_entries = [
                n for n in zf.namelist()
                if n.startswith("lib/arm64-v8a/") and n.endswith(".so")
            ]
            print(f"  发现 {len(so_entries)} 个 .so 文件:")
            for entry in so_entries:
                print(f"    - {entry}")

            for so_file in SO_FILES:
                entry = f"lib/arm64-v8a/{so_file}"
                if entry not in so_entries:
                    print(f"  [WARN] APK 中未找到 {entry}")
                    continue

                target = JNILIBS_DIR / so_file
                with zf.open(entry) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                print(f"  [OK] 提取: {so_file} ({target.stat().st_size / 1024 / 1024:.1f} MB)")

    except Exception as e:
        print(f"[ERROR] 解压失败: {e}")
        return False

    # 验证
    missing = [f for f in SO_FILES if not (JNILIBS_DIR / f).exists()]
    if missing:
        print(f"[ERROR] 仍有缺失的 .so: {missing}")
        return False

    print("[OK] .so 文件提取完成")
    return True


# ============================================================
# 步骤 2: 下载并解压模型文件
# ============================================================

def download_model_files() -> bool:
    """从 GitHub releases 下载 streaming Zipformer small 中英双语模型 tar.bz2 并解压"""
    print("\n=== 步骤 2: 下载模型文件 ===")
    print(f"模型 tar.bz2 URL: {MODEL_TARBALL_URL}")
    print(f"目标根目录: {ASSETS_MODEL_DIR}")

    # 模型文件最终存放路径: ASSETS_MODEL_DIR/MODEL_DIR_NAME/96/
    # 与 SherpaNcnn.kt getModelConfig(type=6) 的 modelDir 匹配
    # (引擎会给 modelConfig path 加 "sherpa_ncnn_models/" 前缀)
    model_target_dir = ASSETS_MODEL_DIR / MODEL_DIR_NAME / "96"

    # 检查是否已下载完整
    if check_model_files_complete(model_target_dir):
        print("[SKIP] 模型文件已完整, 跳过下载")
        return True

    ASSETS_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    tar_path = TEMP_DIR / MODEL_TARBALL_NAME

    # 下载 tar.bz2
    if not tar_path.exists() or tar_path.stat().st_size == 0:
        print(f"\n[下载 tar.bz2] (约 70MB)")
        if not download_file(MODEL_TARBALL_URL, tar_path):
            print("[ERROR] tar.bz2 下载失败")
            return False
    else:
        print(f"[SKIP] tar.bz2 已存在: {tar_path.name} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # 解压
    print(f"\n[解压] {MODEL_TARBALL_NAME}")
    extract_dir = TEMP_DIR / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    try:
        with tarfile.open(tar_path, "r:bz2") as tar:
            tar.extractall(extract_dir)
            print(f"  [OK] 解压完成")
    except Exception as e:
        print(f"[ERROR] 解压失败: {e}")
        return False

    # 找到模型源目录 (extracted/MODEL_DIR_NAME/96/)
    model_source_dir = extract_dir / MODEL_DIR_NAME / "96"
    if not model_source_dir.exists():
        # 可能解压后多了一层目录, 搜索一下
        found = False
        for candidate in extract_dir.rglob("96"):
            if candidate.is_dir() and (candidate / "tokens.txt").exists():
                model_source_dir = candidate
                found = True
                break
        if not found:
            print(f"[ERROR] 解压后未找到 {MODEL_DIR_NAME}/96/ 目录")
            print(f"  解压目录内容:")
            for item in extract_dir.rglob("*"):
                if item.is_file():
                    print(f"    {item.relative_to(extract_dir)}")
            return False

    print(f"  [OK] 找到模型源目录: {model_source_dir.relative_to(extract_dir)}")

    # 复制模型文件到目标目录
    rel_target = model_target_dir.relative_to(PROJECT_ROOT)
    print(f"\n[复制] 模型文件到 {rel_target}")
    model_target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for pattern in MODEL_FILE_PATTERNS:
        src = model_source_dir / pattern
        if not src.exists():
            print(f"  [WARN] 源文件不存在: {pattern}")
            continue
        dest = model_target_dir / pattern
        shutil.copy2(src, dest)
        size = dest.stat().st_size / 1024 / 1024
        print(f"  [OK] {pattern} ({size:.1f} MB)")
        copied += 1

    # 验证完整性
    if not check_model_files_complete(model_target_dir):
        print("[ERROR] 模型文件不完整")
        missing = [
            p for p in MODEL_FILE_PATTERNS
            if not (model_target_dir / p).exists()
        ]
        print(f"  缺失: {missing}")
        return False

    # 清理解压临时目录 (保留 tar.bz2 供下次跳过)
    shutil.rmtree(extract_dir, ignore_errors=True)

    print(f"\n[OK] 模型下载完成 ({copied}/{len(MODEL_FILE_PATTERNS)} 个文件)")

    # 列出最终文件
    print(f"\n[最终文件清单] {model_target_dir}:")
    for f in sorted(model_target_dir.iterdir()):
        size = f.stat().st_size / 1024 / 1024
        print(f"  - {f.name} ({size:.1f} MB)")

    return True


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载 sherpa-ncnn Android 集成所需的 .so 库和模型文件"
    )
    parser.add_argument(
        "--skip-so", action="store_true", help="跳过 .so 下载 (仅下模型)"
    )
    parser.add_argument(
        "--skip-model", action="store_true", help="跳过模型下载 (仅下 .so)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("sherpa-ncnn Android 资源下载脚本")
    print(f"版本: {SHERPA_NCNN_VERSION}")
    print(f"项目根目录: {PROJECT_ROOT}")
    print("=" * 60)

    success = True

    if not args.skip_so:
        if not download_and_extract_so():
            success = False
            print("\n[ERROR] .so 下载失败, 终止")
            return 1

    if not args.skip_model:
        if not download_model_files():
            success = False
            print("\n[WARN] 模型下载失败, 但 .so 可能已就绪")

    print("\n" + "=" * 60)
    if success:
        print("[完成] 所有资源已就绪")
        print("\n下一步:")
        print(f"  1. .so 位置: {JNILIBS_DIR.relative_to(PROJECT_ROOT)}")
        print(f"  2. 模型位置: {(ASSETS_MODEL_DIR / MODEL_DIR_NAME / '96').relative_to(PROJECT_ROOT)}")
        print("  3. 编译 Android 项目验证集成")
    else:
        print("[部分完成] 请检查上方警告")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
