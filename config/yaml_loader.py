"""
YAML 配置加载与映射。

支持 app.yaml 作为主入口，通过 imports 机制按领域拆分子配置文件。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from config.cache_manager import build_path_signature

logger = logging.getLogger("config")
ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$(\w+)")


def extract_env_var_names(text: str) -> list[str]:
    env_names = []
    seen = set()
    for match in ENV_VAR_PATTERN.finditer(text or ""):
        env_name = match.group(1) or match.group(2)
        if env_name and env_name not in seen:
            seen.add(env_name)
            env_names.append(env_name)
    return env_names


def get_env_snapshot(env_names: list[str]) -> Dict[str, str]:
    return {name: os.getenv(name, "") for name in env_names}


def resolve_env_vars(config: Any) -> Any:
    """递归替换配置中的环境变量占位符"""
    if isinstance(config, dict):
        return {k: resolve_env_vars(v) for k, v in config.items()}
    if isinstance(config, list):
        return [resolve_env_vars(item) for item in config]
    if isinstance(config, str):

        def replace_var(match):
            env_var = match.group(1) or match.group(2)
            return os.getenv(env_var, match.group(0))

        return ENV_VAR_PATTERN.sub(replace_var, config)
    return config


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并字典，后者覆盖前者。"""
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_import_paths(raw_imports: Any, base_dir: Path) -> list[Path]:
    """将 imports 配置转换为相对当前 YAML 文件的绝对路径列表。"""
    if raw_imports is None:
        return []

    if isinstance(raw_imports, str):
        items = [raw_imports]
    elif isinstance(raw_imports, list):
        items = [item for item in raw_imports if isinstance(item, str)]
    else:
        raise ValueError("YAML imports 必须是字符串或字符串列表")

    resolved_paths: list[Path] = []
    for item in items:
        candidate = (base_dir / item).resolve()
        resolved_paths.append(candidate)
    return resolved_paths


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """去重并保持顺序。"""
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _load_yaml_document_with_imports(
    yaml_path: Path,
    *,
    visited: Optional[set[str]] = None,
) -> tuple[Dict[str, Any], str, list[Path]]:
    """递归加载 YAML 文档，并展开 imports。"""
    normalized_path = yaml_path.resolve()
    visited = visited or set()
    path_key = str(normalized_path)

    if path_key in visited:
        raise ValueError(f"检测到循环 YAML imports: {normalized_path}")
    if not normalized_path.exists():
        raise FileNotFoundError(f"YAML 配置文件不存在: {normalized_path}")

    visited.add(path_key)
    yaml_text = normalized_path.read_text(encoding="utf-8")
    raw_config = yaml.safe_load(yaml_text) or {}
    if not isinstance(raw_config, dict):
        raise ValueError(f"YAML 顶层必须是映射: {normalized_path}")

    import_paths = _normalize_import_paths(raw_config.pop("imports", None), normalized_path.parent)

    merged_config: Dict[str, Any] = {}
    collected_texts: list[str] = []
    collected_paths: list[Path] = []

    for import_path in import_paths:
        imported_config, imported_text, imported_paths = _load_yaml_document_with_imports(
            import_path,
            visited=visited,
        )
        merged_config = _deep_merge_dicts(merged_config, imported_config)
        collected_texts.append(imported_text)
        collected_paths.extend(imported_paths)

    merged_config = _deep_merge_dicts(merged_config, raw_config)
    collected_texts.append(yaml_text)
    collected_paths.append(normalized_path)
    visited.remove(path_key)

    return (
        resolve_env_vars(merged_config),
        "\n".join(collected_texts),
        _deduplicate_paths(collected_paths),
    )


def load_resolved_yaml_config_from_disk(
    app_yaml_path: Path,
) -> tuple[Dict[str, Any], str, list[Path]]:
    return _load_yaml_document_with_imports(app_yaml_path)


def build_yaml_cache_entry(
    app_yaml_path: Path,
    yaml_config: Dict[str, Any],
    yaml_text: str,
    source_paths: Optional[list[Path]] = None,
) -> Dict[str, Any]:
    env_names = extract_env_var_names(yaml_text)
    paths = _deduplicate_paths(source_paths or [app_yaml_path])
    return {
        "signature": build_path_signature(app_yaml_path),
        "source_signatures": [build_path_signature(path) for path in paths],
        "env_names": env_names,
        "env_values": get_env_snapshot(env_names),
        "resolved_config": yaml_config,
    }


def get_cached_yaml_config(
    app_yaml_path: Path, startup_cache: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    entry = startup_cache.get("yaml")
    if not isinstance(entry, dict):
        return None
    source_signatures = entry.get("source_signatures")
    if isinstance(source_signatures, list) and source_signatures:
        current_signatures = []
        for signature in source_signatures:
            if not isinstance(signature, dict):
                return None
            raw_path = signature.get("path")
            if not raw_path:
                return None
            current_signatures.append(build_path_signature(Path(raw_path)))
        if current_signatures != source_signatures:
            return None
    elif entry.get("signature") != build_path_signature(app_yaml_path):
        return None
    env_names = entry.get("env_names") or []
    if entry.get("env_values") != get_env_snapshot(list(env_names)):
        return None
    yaml_config = entry.get("resolved_config")
    if isinstance(yaml_config, dict):
        logger.info(f"Loaded configuration from startup cache: {app_yaml_path}")
        return yaml_config
    return None


# ────────────────────────────────────────────────────────
# YAML -> Pydantic 映射层
# ────────────────────────────────────────────────────────

# YAML 顶层 key -> settings 字段名 映射（处理不一致的命名）
_YAML_SECTION_MAP: Dict[str, str] = {
    "history": "memory",
    "websocket": "server",       # 子字段通过 _YAML_FIELD_REMAP 处理
    "logging": "log",
    "vtube": "vtube",
    "debug": "debug",
}


def _remap_yaml_to_settings_structure(yaml_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 YAML 的 dict 结构转换为与 AppSettings 层级匹配的 dict。
    处理历史遗留的 key 命名不一致问题。
    """
    result: Dict[str, Any] = {}

    for key, value in yaml_config.items():
        if not isinstance(value, dict):
            continue

        # 映射 section 名
        target_key = _YAML_SECTION_MAP.get(key, key)

        if key == "history":
            # history -> memory，部分字段需要重命名
            memory_conf: Dict[str, Any] = {}
            for hk, hv in value.items():
                if hk == "directory":
                    memory_conf["history_dir"] = hv
                elif hk == "default_length":
                    memory_conf.setdefault("short_term_capacity", hv)
                elif hk == "short_term_capacity":
                    memory_conf["short_term_capacity"] = hv
                elif hk == "max_length":
                    memory_conf.setdefault("long_term_capacity", hv)
                elif hk == "long_term_capacity":
                    memory_conf["long_term_capacity"] = hv
                elif hk == "cleanup_interval_seconds":
                    memory_conf["history_cleanup_interval_seconds"] = hv
                elif hk == "archive_interval_seconds":
                    memory_conf["history_archive_interval_seconds"] = hv
                elif hk == "retention_days":
                    memory_conf["history_retention_days"] = hv
                elif hk == "auto_archive_enabled":
                    memory_conf["history_auto_archive_enabled"] = hv
                else:
                    memory_conf[hk] = hv
            result.setdefault("memory", {}).update(memory_conf)

        elif key == "websocket":
            # websocket -> server.ws_*
            ws_map = {
                "port": "ws_port",
                "heartbeat_interval": "ws_heartbeat_interval",
                "timeout": "ws_timeout",
                "message_merge_wait_ms": "ws_user_message_merge_wait_ms",
            }
            server_conf: Dict[str, Any] = {}
            for wk, wv in value.items():
                server_conf[ws_map.get(wk, wk)] = wv
            result.setdefault("server", {}).update(server_conf)

        elif key == "logging":
            # logging -> log（调试开关已迁移到 debug 节）
            log_map = {
                "level": "level",
                "console_level": "console_level",
            }
            log_conf: Dict[str, Any] = {}
            for lk, lv in value.items():
                if lk in log_map:
                    log_conf[log_map[lk]] = lv
            result.setdefault("log", {}).update(log_conf)

        elif key == "user":
            # user: 处理 display_name / name 别名
            user_conf = dict(value)
            if "display_name" not in user_conf and "name" in user_conf:
                user_conf["display_name"] = user_conf.pop("name")
            result["user"] = user_conf

        elif key == "model":
            # model 内部需要特殊处理 generation 子块和 path -> text_path
            model_conf = dict(value)
            if "path" in model_conf:
                model_conf["text_path"] = normalize_local_path(model_conf.pop("path"))
            if "default" in model_conf:
                model_conf["name"] = model_conf.pop("default")
            # generation 子块需要展平到 model 层
            if "generation" in model_conf and isinstance(model_conf["generation"], dict):
                gen = model_conf.pop("generation")
                for gk, gv in gen.items():
                    model_conf.setdefault(gk, gv)
            result["model"] = model_conf

        elif key == "vtube":
            # vtube: emotion_map -> emotion_hotkey_map
            vts_conf = dict(value)
            if "emotion_map" in vts_conf:
                vts_conf["emotion_hotkey_map"] = vts_conf.pop("emotion_map")
            result["vtube"] = vts_conf

        else:
            result[target_key] = value

    return result


def normalize_local_path(path: str) -> str:
    """标准化本地路径（占位，实际实现在 model_detector 中）"""
    return path


def apply_yaml_config(settings: Any, yaml_config: Dict[str, Any], _normalize_local_path):
    """
    将 YAML 配置应用到 settings 对象。
    使用 Pydantic model_validate 替代逐字段手动赋值。
    """
    global normalize_local_path
    normalize_local_path = _normalize_local_path

    try:
        # 1. 将 YAML 结构重映射为 settings 兼容结构
        mapped = _remap_yaml_to_settings_structure(yaml_config)

        # 2. 对每个 section 使用 model_validate 做部分更新
        for section_name, section_data in mapped.items():
            if not isinstance(section_data, dict):
                continue
            section_obj = getattr(settings, section_name, None)
            if section_obj is None:
                continue
            try:
                # 使用 model_validate 做部分更新（extra='allow' 保证不丢字段）
                updated = section_obj.__class__.model_validate(
                    section_obj.model_dump() | section_data
                )
                # 将更新后的值写回（Pydantic model 是 frozen=False）
                for field_name in updated.model_fields:
                    setattr(section_obj, field_name, getattr(updated, field_name))
            except Exception as e:
                logger.debug(f"Section '{section_name}' model_validate 失败，跳过: {e}")

        logger.info("Applied app.yaml configuration overrides")
    except Exception as e:
        logger.warning(f"Error applying yaml config: {e}")
