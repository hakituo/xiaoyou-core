# -*- coding: utf-8 -*-
"""TTS 合成结果磁盘缓存。

同一段文本 + 同一个音色 + 同一组影响输出的参数，没必要每次都真的调用云端 TTS。
本模块按这些输入算出一个 key，把 `_generate_tts_with_async` 的返回结果缓存成 JSON：

- 命中即直接返回，省一次云端调用（省额度、降延迟）；
- TTL 7 天：超过 7 天视为过期，写入新结果时顺带清理；
- 目录容量上限：超过上限时按最旧优先淘汰，避免无限膨胀；
- 缓存 key 只包含影响音频内容的输入，不含 request_id 这类每次不同的字段。

设计取舍：云端大模型语音合成同一句话每次结果会有细微随机差异，缓存会把首次结果固定住。
对"同一句话反复播放"的场景这是想要的行为（一致 + 省额度）；如需每次都重新合成，
把 `TTS_CACHE_ENABLED` 置否即可。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 缓存有效期：7 天
TTS_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# 缓存目录大小上限：512MB，超出按最旧优先淘汰
TTS_CACHE_MAX_BYTES = 512 * 1024 * 1024

# 影响音频内容的参数（顺序无关，取 hash 用）。text / voice 单独处理。
_KEY_PARAM_FIELDS = (
    "text_lang",
    "prompt_lang",
    "speed",
    "pitch",
    "style",
    "xfade_ms",
    "pause_second",
    "noise_gate_threshold",
    "hp_cut",
    "lp_cut",
    "fade_ms",
    "downsample_sr",
    "reference_audio",
)


def is_cache_enabled() -> bool:
    """缓存开关：默认开启；置 TTS_CACHE_DISABLED=1 可临时关闭（排查问题时用）。"""
    return os.environ.get("TTS_CACHE_DISABLED", "").strip().lower() not in ("1", "true", "yes", "on")


def _cache_dir() -> str:
    """缓存目录：output/cache/tts（output 已在 .gitignore 内）。"""
    from core.utils.common import get_project_root

    d = os.path.join(str(get_project_root()), "output", "cache", "tts")
    os.makedirs(d, exist_ok=True)
    return d


def build_cache_key(text: str, voice: str, params: Optional[Dict[str, Any]] = None) -> str:
    """按「音色 + 文本 + 影响输出的参数」生成稳定 key。

    参数里混有 None / 数字 / 字符串时统一转成字符串再参与 hash，保证同一请求稳定命中。
    text 和 voice 放最后并加分隔符，避免不同字段拼接后撞出同一个 hash。
    """
    params = params or {}
    parts = []
    for field in _KEY_PARAM_FIELDS:
        value = params.get(field)
        if value is None:
            continue
        parts.append(f"{field}={value}")
    payload = "|".join(parts) + f"\x00voice={voice}\x00text={text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_path(key: str) -> str:
    return os.path.join(_cache_dir(), f"{key}.json")


def load_cached_result(key: str) -> Optional[Dict[str, Any]]:
    """读取缓存结果；不存在、已过期或损坏时返回 None。

    过期文件顺手删掉，避免每次都要再判一次。
    """
    if not is_cache_enabled():
        return None
    path = _cache_path(key)
    try:
        if not os.path.exists(path):
            return None
        age = time.time() - os.path.getmtime(path)
        if age > TTS_CACHE_TTL_SECONDS:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        result = payload.get("result")
        if not isinstance(result, dict) or not result.get("audio_base64"):
            return None
        logger.info("TTS 缓存命中: key=%s, age=%.1fh", key, age / 3600.0)
        return result
    except Exception as e:
        # 缓存读取失败绝不能影响正常合成：记录后按未命中处理
        logger.warning("TTS 缓存读取失败(忽略): %s", e)
        return None


def save_cached_result(key: str, result: Dict[str, Any]) -> None:
    """写入缓存结果；只缓存含音频的结果，失败仅告警。"""
    if not is_cache_enabled():
        return
    if not isinstance(result, dict) or not result.get("audio_base64"):
        return
    path = _cache_path(key)
    try:
        # 写入前先做一轮过期/容量清理，减少目录无界增长
        clear_expired()
        trim_cache_if_needed(len(json.dumps(result)))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cached_at": time.time(), "result": result}, f, ensure_ascii=False)
        logger.info("TTS 结果已缓存: key=%s", key)
    except Exception as e:
        logger.warning("TTS 缓存写入失败(忽略): %s", e)


def clear_expired() -> int:
    """删除超过 TTL 的缓存文件，返回删除数量。"""
    removed = 0
    try:
        now = time.time()
        for name in os.listdir(_cache_dir()):
            if not name.endswith(".json"):
                continue
            path = os.path.join(_cache_dir(), name)
            try:
                if now - os.path.getmtime(path) > TTS_CACHE_TTL_SECONDS:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    except Exception as e:
        logger.warning("TTS 缓存过期清理失败(忽略): %s", e)
    return removed


def trim_cache_if_needed(incoming_bytes: int = 0) -> int:
    """目录总大小超过上限时，按最旧优先淘汰，返回删除数量。"""
    removed = 0
    try:
        cache_dir = _cache_dir()
        entries = [
            os.path.join(cache_dir, name)
            for name in os.listdir(cache_dir)
            if name.endswith(".json")
        ]
        total = sum(os.path.getsize(p) for p in entries if os.path.exists(p)) + max(incoming_bytes, 0)
        if total <= TTS_CACHE_MAX_BYTES:
            return 0
        entries.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        for path in entries:
            if total <= TTS_CACHE_MAX_BYTES:
                break
            try:
                size = os.path.getsize(path)
                os.remove(path)
                total -= size
                removed += 1
            except OSError:
                continue
    except Exception as e:
        logger.warning("TTS 缓存淘汰失败(忽略): %s", e)
    return removed


def clear_all() -> int:
    """清空全部缓存（调试/手动维护用），返回删除数量。"""
    removed = 0
    try:
        for name in os.listdir(_cache_dir()):
            if not name.endswith(".json"):
                continue
            try:
                os.remove(os.path.join(_cache_dir(), name))
                removed += 1
            except OSError:
                continue
    except Exception as e:
        logger.warning("TTS 缓存清空失败(忽略): %s", e)
    return removed


def cache_stats() -> Dict[str, Any]:
    """缓存现状（条数 / 总大小 / 最早写入时间），供维护脚本与排查用。"""
    stats: Dict[str, Any] = {"count": 0, "bytes": 0, "expired": 0, "oldest_age_hours": 0.0}
    try:
        now = time.time()
        ages = []
        total = 0
        count = 0
        expired = 0
        for name in os.listdir(_cache_dir()):
            if not name.endswith(".json"):
                continue
            path = os.path.join(_cache_dir(), name)
            try:
                size = os.path.getsize(path)
                age = now - os.path.getmtime(path)
            except OSError:
                continue
            count += 1
            total += size
            ages.append(age)
            if age > TTS_CACHE_TTL_SECONDS:
                expired += 1
        stats.update(
            {
                "count": count,
                "bytes": total,
                "expired": expired,
                "oldest_age_hours": round(max(ages) / 3600.0, 2) if ages else 0.0,
            }
        )
    except Exception as e:
        logger.warning("TTS 缓存统计失败(忽略): %s", e)
    return stats
