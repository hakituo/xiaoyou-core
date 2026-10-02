"""
启动配置缓存管理
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("config")
STARTUP_CACHE_VERSION = 1
STARTUP_CACHE_FILENAME = "startup_settings_cache.json"


def get_startup_cache_path(project_root: Path) -> Path:
    root = Path(project_root)
    cache_dir = root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / STARTUP_CACHE_FILENAME


def build_path_signature(path: Path) -> Dict[str, Any]:
    target = Path(path)
    signature: Dict[str, Any] = {"path": str(target)}
    try:
        stat = target.stat()
        signature["exists"] = True
        signature["is_dir"] = target.is_dir()
        signature["mtime_ns"] = stat.st_mtime_ns
        signature["size"] = stat.st_size
    except FileNotFoundError:
        signature["exists"] = False
    except Exception as e:
        signature["exists"] = False
        signature["error"] = str(e)
    return signature


def load_startup_cache(project_root: Path) -> Dict[str, Any]:
    cache_path = get_startup_cache_path(project_root)
    if not cache_path.exists():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        if int(payload.get("version", 0) or 0) != STARTUP_CACHE_VERSION:
            return {}
        return payload
    except Exception as e:
        logger.warning(f"Failed to load startup cache: {e}")
        return {}


def save_startup_cache(payload: Dict[str, Any], project_root: Path):
    cache_path = get_startup_cache_path(project_root)
    try:
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save startup cache: {e}")


def build_empty_startup_cache() -> Dict[str, Any]:
    return {"version": STARTUP_CACHE_VERSION}


def get_cache_entry(cache: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    entry = cache.get(key)
    if isinstance(entry, dict):
        return entry
    return None
