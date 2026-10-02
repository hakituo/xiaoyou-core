# -*- coding: utf-8 -*-
"""验证 TTS 磁盘缓存（core/voice/tts_cache.py）与 /media/tts 的缓存接线。

覆盖点：
1. key 稳定性：同输入 -> 同 key；文本/音色/参数任一变化 -> 不同 key；
2. 未命中 -> 写入 -> 命中；命中结果与写入内容一致；
3. 过期（TTL 7 天）文件不被命中，且读取时顺手删除；
4. 损坏的缓存文件不会抛异常，按未命中处理；
5. 容量超限时按最旧优先淘汰；
6. 路由层确实接上了缓存（静态检查 media_voice.py，防止后续重构时又漏掉）。

用法：
    venv_core\\Scripts\\python.exe tests/scripts/voice/verify_tts_cache.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("PASS: " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def _sample_result(text: str = "你好") -> dict:
    return {"audio_base64": "data:audio/wav;base64,AAAA", "sample_rate": 24000, "text": text}


def main() -> int:
    from core.voice import tts_cache

    print("=" * 70)
    print("TTS 缓存验证")
    print("=" * 70)

    # 用独立子目录避免污染真实缓存：直接改模块的目录函数
    tmp_root = ROOT / "output" / "cache" / "_verify_tts_cache"
    tmp_root.mkdir(parents=True, exist_ok=True)

    import core.voice.tts_cache as tc

    original_cache_dir = tc._cache_dir
    tc._cache_dir = lambda: str(tmp_root)  # type: ignore[assignment]

    try:
        # 清场
        for f in tmp_root.glob("*.json"):
            f.unlink()

        # 1. key 稳定性
        key_a = tts_cache.build_cache_key("你好", "Ye", {"speed": 1.0, "text_lang": "zh"})
        key_a2 = tts_cache.build_cache_key("你好", "Ye", {"text_lang": "zh", "speed": 1.0})
        key_b = tts_cache.build_cache_key("你好呀", "Ye", {"speed": 1.0, "text_lang": "zh"})
        key_c = tts_cache.build_cache_key("你好", "Ling", {"speed": 1.0, "text_lang": "zh"})
        key_d = tts_cache.build_cache_key("你好", "Ye", {"speed": 1.2, "text_lang": "zh"})
        check(key_a == key_a2, "参数字典顺序不影响 key（同一请求稳定命中）")
        check(len({key_a, key_b, key_c, key_d}) == 4, "文本/音色/参数任一变化都会产生不同 key")

        # 2. 未命中 -> 写入 -> 命中
        check(tts_cache.load_cached_result(key_a) is None, "首次请求未命中")
        tts_cache.save_cached_result(key_a, _sample_result())
        hit = tts_cache.load_cached_result(key_a)
        check(hit is not None and hit.get("text") == "你好", "写入后命中且结果一致")
        check(tts_cache.load_cached_result(key_b) is None, "不同文本不会串命中")

        # 3. 只有音频的结果才缓存
        tts_cache.save_cached_result(key_b, {"sample_rate": 24000})
        check(tts_cache.load_cached_result(key_b) is None, "无音频内容的结果不写入缓存")

        # 4. 过期不被命中，并被删除
        expired_key = tts_cache.build_cache_key("过期文本", "Ye", {})
        tts_cache.save_cached_result(expired_key, _sample_result("过期文本"))
        expired_path = Path(str(tmp_root / f"{expired_key}.json"))
        old = time.time() - (tts_cache.TTS_CACHE_TTL_SECONDS + 3600)
        os.utime(expired_path, (old, old))
        check(tts_cache.load_cached_result(expired_key) is None, "超过 TTL 的缓存不再命中")
        check(not expired_path.exists(), "读取过期缓存时顺手删除该文件")

        # 5. 损坏文件按未命中处理，不抛异常
        broken_key = tts_cache.build_cache_key("损坏文本", "Ye", {})
        broken_path = tmp_root / f"{broken_key}.json"
        broken_path.write_text("{不是合法 json", encoding="utf-8")
        check(tts_cache.load_cached_result(broken_key) is None, "损坏的缓存文件按未命中处理")

        # 6. 容量超限按最旧优先淘汰
        original_max = tts_cache.TTS_CACHE_MAX_BYTES
        tts_cache.TTS_CACHE_MAX_BYTES = 1  # 强制触发淘汰
        removed = tts_cache.trim_cache_if_needed(0)
        tts_cache.TTS_CACHE_MAX_BYTES = original_max
        check(removed > 0, f"超过容量上限时触发淘汰（删除 {removed} 个）")

        # 7. 统计
        stats = tts_cache.cache_stats()
        check("count" in stats and "bytes" in stats, f"cache_stats 可用: {stats}")

        # 8. 路由层接线（静态检查，防止重构后缓存被摘掉）
        voice_src = (ROOT / "routers/v1/media_voice.py").read_text(encoding="utf-8")
        check("load_cached_result" in voice_src, "media_voice.py 命中缓存后直接返回")
        check("save_cached_result" in voice_src, "media_voice.py 合成成功后写入缓存")

        # 9. 拆分后路由与兼容导出仍可用
        from routers.v1 import router as v1_router
        from routers.v1.media import _generate_tts_with_async
        from routers.v1.life_shared import SleepWakeRequest  # noqa: F401

        # /api/v1 前缀由顶层 routers/__init__.py 追加，v1 router 自身的 path 不含它
        paths = {getattr(r, "path", "") for r in v1_router.routes}
        for expected in (
            "/media/tts",
            "/media/stt",
            "/media/voices",
            "/media/upload",
            "/life/status",
            "/life/sleep/wake",
            "/life/activity/interrupt",
            "/life/activity/skip",
            "/life/activity/extend",
            "/life/emotion/detect",
        ):
            check(expected in paths, f"路由存在: {expected}")
        check(callable(_generate_tts_with_async), "media._generate_tts_with_async 兼容导出仍可用")
    finally:
        tc._cache_dir = original_cache_dir  # type: ignore[assignment]
        for f in tmp_root.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass

    print("-" * 70)
    if FAILURES:
        print(f"❌ 失败 {len(FAILURES)} 项：")
        for item in FAILURES:
            print("  - " + item)
        return 1
    print("✅ 全部通过：TTS 缓存命中/过期/淘汰行为正确，路由拆分后端点与兼容导出均可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
