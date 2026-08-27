#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 Android 端图片 URL 解析修复是否到位。

检查点：
1. ImageUrlResolver 工具类存在且实现了 resolve 方法。
2. MessageBubble 使用 ImageUrlResolver.resolve 解析图片地址。
3. AvelineApplication 在 onCreate 中配置 Coil 全局 ImageLoader。
4. 后端 /api/v1/upload 接口返回 data.file_url 字段。

该脚本为静态代码检查，不依赖 Gradle/Android Studio 编译。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main() -> int:
    root = _default_project_root()
    checks: list[tuple[str, bool]] = []

    # 1. ImageUrlResolver
    resolver_file = (
        root
        / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/utils/ImageUrlResolver.kt"
    )
    resolver_src = read_text(resolver_file)
    checks.append(
        (
            "ImageUrlResolver.kt 存在并实现 resolve 方法",
            "object ImageUrlResolver" in resolver_src
            and "fun resolve(backendUrl: String, imageUrl: String): String" in resolver_src,
        )
    )

    # 2. MessageBubble 使用 ImageUrlResolver
    bubble_file = (
        root
        / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/presentation/components/MessageBubble.kt"
    )
    bubble_src = read_text(bubble_file)
    checks.append(
        (
            "MessageBubble 导入并调用 ImageUrlResolver.resolve",
            "import com.aveline.ai.mobile.utils.ImageUrlResolver" in bubble_src
            and "ImageUrlResolver.resolve(" in bubble_src,
        )
    )

    # 3. AvelineApplication 配置 Coil ImageLoader
    app_file = (
        root
        / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/AvelineApplication.kt"
    )
    app_src = read_text(app_file)
    checks.append(
        (
            "AvelineApplication 在 onCreate 中调用 Coil.setImageLoader",
            "Coil.setImageLoader(coilImageLoader.createImageLoader(okHttpClient))" in app_src,
        )
    )

    # 4. 后端上传接口返回 file_url
    media_file = root / "routers/v1/media.py"
    media_src = read_text(media_file)
    checks.append(
        (
            "后端 /api/v1/upload 返回 data.file_url",
            '"file_url": rel' in media_src,
        )
    )

    # 5. 单元测试存在
    test_file = (
        root
        / "clients/frontend/aveline-android/android/app/src/test/java/com/aveline/ai/mobile/utils/ImageUrlResolverTest.kt"
    )
    checks.append(
        (
            "ImageUrlResolverTest 单元测试存在",
            test_file.exists() and "ImageUrlResolver.resolve" in read_text(test_file),
        )
    )

    failed = [desc for desc, ok in checks if not ok]
    for desc, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {desc}")

    if failed:
        print(f"\n失败项: {len(failed)}")
        return 1

    print("\n所有检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
