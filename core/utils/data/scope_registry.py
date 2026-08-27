"""角色数据 scope 的唯一注册表与解析入口。

持久化目录一律由 persona JSON 的 ``meta.scope`` 决定。文件名、显示名、
历史别名只用于找到这个稳定 scope，不能直接成为新的数据目录名。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Optional

import structlog

from config.debug_config import is_debug_enabled
from core.utils.common import get_project_root

logger = structlog.get_logger(__name__)

_BUILTIN_ROLE_SCOPES = {"aveline", "ling", "xiaolu", "yeye"}
_SPECIAL_SCOPES = {"user", "dual_role"}
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 保留这些可变对象供旧导入路径兼容；刷新时原地更新，避免引用失效。
_VALID_SCOPES: set[str] = set(_BUILTIN_ROLE_SCOPES | _SPECIAL_SCOPES)
_DYNAMIC_SCOPES: dict[str, dict] = {}
_PERSONA_SLUG_TO_SCOPE: dict[str, str] = {}

_BUILTIN_SLUG_TO_SCOPE = {
    "aveline": "aveline",
    "core_aveline": "aveline",
    "ling": "ling",
    "core_ling": "ling",
    "wang_ling": "ling",
    "xiaolu": "xiaolu",
    "qq_official_1": "xiaolu",
    "yeye": "yeye",
    "qq_official_2": "yeye",
}

_PERSONA_CONFIGS_DIR = "core/character/configs"
_REGISTRY_INITIALIZED = False
_REGISTRY_LOCK = threading.RLock()
_ACTIVE_CONFIGS_DIR: Optional[Path] = None
_CONFIG_SNAPSHOT: tuple[int, int] = (0, 0)


def _default_configs_dir() -> Path:
    return (get_project_root() / _PERSONA_CONFIGS_DIR).resolve()


def _normalize_slug(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    stem = text.rsplit("/", 1)[-1]
    if stem.lower().endswith(".json"):
        stem = stem[:-5]
    return stem.strip().lower()


def _slug_candidates(value: object) -> set[str]:
    raw = _normalize_slug(value)
    if not raw:
        return set()
    safe = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", raw).strip("_")
    return {candidate for candidate in (raw, safe) if candidate}


def _config_snapshot(configs_dir: Path) -> tuple[int, int]:
    count = 0
    newest_mtime_ns = 0
    if not configs_dir.exists():
        return count, newest_mtime_ns
    for path in configs_dir.rglob("*.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        newest_mtime_ns = max(newest_mtime_ns, stat.st_mtime_ns)
    return count, newest_mtime_ns


def _infer_builtin_scope(json_file: Path, data: dict) -> str:
    """兼容旧内置 persona；新角色必须显式声明 meta.scope。"""
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    tokens = " ".join(
        [
            json_file.stem,
            str(identity.get("name") or ""),
            str(identity.get("cn_name") or ""),
        ]
    ).lower()
    if "ling" in tokens or "Ling" in tokens:
        return "ling"
    if "aveline" in tokens or "七濑" in tokens or "澪" in tokens:
        return "aveline"
    return ""


def _register_alias(alias: object, scope: str) -> None:
    for slug in _slug_candidates(alias):
        existing = _PERSONA_SLUG_TO_SCOPE.get(slug)
        if existing and existing != scope:
            logger.warning(
                "persona scope 别名冲突，保留先注册值",
                slug=slug,
                existing_scope=existing,
                ignored_scope=scope,
            )
            continue
        _PERSONA_SLUG_TO_SCOPE[slug] = scope


def _register_persona(json_file: Path, data: dict) -> None:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    scope = str(meta.get("scope") or "").strip().lower()
    if not scope:
        scope = _infer_builtin_scope(json_file, data)
    if not scope:
        return
    if not _SCOPE_PATTERN.fullmatch(scope):
        logger.warning(
            "忽略非法 persona scope；必须使用英文 snake_case",
            path=str(json_file),
            scope=scope,
        )
        return

    _VALID_SCOPES.add(scope)
    if scope not in _BUILTIN_ROLE_SCOPES:
        info = _DYNAMIC_SCOPES.setdefault(
            scope,
            {"dir": f"{scope}_data", "slugs": set()},
        )
        info["slugs"].add(json_file.stem.lower())

    _register_alias(scope, scope)
    _register_alias(json_file.stem, scope)

    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    for key in ("name", "cn_name", "en_name", "real_name", "role_id"):
        _register_alias(identity.get(key), scope)
    aliases = meta.get("aliases")
    if isinstance(aliases, list):
        for value in aliases:
            _register_alias(value, scope)


def _scan_persona_scopes_impl(configs_dir: Path) -> None:
    if not configs_dir.exists():
        return
    for json_file in sorted(configs_dir.rglob("*.json")):
        try:
            relative = json_file.relative_to(configs_dir)
        except ValueError:
            continue
        if any(part.lower() in {"legacy", "backup"} for part in relative.parts):
            continue
        if json_file.name.startswith("special_") or "reference_dialogue" in json_file.name:
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if "identity" not in data and "extends" not in data:
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("deprecated"):
            continue
        _register_persona(json_file, data)


def refresh_scope_registry(configs_dir: Optional[Path] = None) -> None:
    """重新扫描 persona 配置；新增角色后无需修改 Python 角色白名单。"""
    global _ACTIVE_CONFIGS_DIR, _CONFIG_SNAPSHOT, _REGISTRY_INITIALIZED
    target = Path(configs_dir).resolve() if configs_dir is not None else _default_configs_dir()
    with _REGISTRY_LOCK:
        _VALID_SCOPES.clear()
        _VALID_SCOPES.update(_BUILTIN_ROLE_SCOPES | _SPECIAL_SCOPES)
        _DYNAMIC_SCOPES.clear()
        _PERSONA_SLUG_TO_SCOPE.clear()
        _PERSONA_SLUG_TO_SCOPE.update(_BUILTIN_SLUG_TO_SCOPE)
        _scan_persona_scopes_impl(target)
        _ACTIVE_CONFIGS_DIR = target
        _CONFIG_SNAPSHOT = _config_snapshot(target)
        _REGISTRY_INITIALIZED = True

    if _DYNAMIC_SCOPES and is_debug_enabled("data_paths"):
        logger.info("persona scope 注册完成", scopes=list_dynamic_scopes())


def init_scope_registry() -> None:
    """首次使用时惰性初始化唯一注册表。"""
    if _REGISTRY_INITIALIZED:
        return
    refresh_scope_registry()


def _refresh_if_configs_changed() -> None:
    init_scope_registry()
    target = _ACTIVE_CONFIGS_DIR or _default_configs_dir()
    if _config_snapshot(target) != _CONFIG_SNAPSHOT:
        refresh_scope_registry(target)


def resolve_persona_slug_scope(slug: object) -> str:
    """把 persona 文件名、显示名或别名解析为稳定 scope。"""
    init_scope_registry()
    for candidate in _slug_candidates(slug):
        scope = _PERSONA_SLUG_TO_SCOPE.get(candidate)
        if scope:
            return scope
    _refresh_if_configs_changed()
    for candidate in _slug_candidates(slug):
        scope = _PERSONA_SLUG_TO_SCOPE.get(candidate)
        if scope:
            return scope
    return ""


def normalize_data_scope(scope: Optional[str], *, default: str = "user") -> str:
    """归一化显式 scope 或 persona 别名。"""
    init_scope_registry()
    value = str(scope or "").strip().lower()
    if value in _VALID_SCOPES:
        return value
    if value in {"default", "main", "front", "assistant", "qilai_wei", "core_aveline"}:
        return "aveline"
    if value in {"wang_ling", "core_ling"}:
        return "ling"
    resolved = resolve_persona_slug_scope(value)
    if resolved:
        return resolved
    return default if default in _VALID_SCOPES else "user"


def _unknown_persona_scope(slug: str) -> str:
    """未知中文 persona 不再直接生成中文目录，进入稳定隔离 scope。"""
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:12]
    scope = f"persona_{digest}"
    logger.warning(
        "persona 未声明 meta.scope，使用隔离 scope；请补齐配置",
        persona_slug=slug,
        fallback_scope=scope,
    )
    return scope


def resolve_active_persona_scope() -> str:
    """从当前 persona 文件名解析 scope。"""
    try:
        from core.character.managers.persona_manager import get_persona_manager

        current_filename = get_persona_manager().get_current_filename()
        resolved = resolve_persona_slug_scope(current_filename)
        if resolved:
            return resolved
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("从活跃 persona 解析 scope 失败", exc_info=True)
    return "aveline"


def resolve_data_scope_from_conversation_id(
    conversation_id: Optional[str],
    *,
    default: str = "aveline",
) -> str:
    """从 conversation_id 解析唯一持久化 scope。"""
    init_scope_registry()
    cid = str(conversation_id or "").strip().lower()
    if not cid:
        return normalize_data_scope(default, default="aveline")
    if "__scope__" in cid:
        scope_part = cid.split("__scope__", 1)[1].strip("_").split("__", 1)[0]
        return normalize_data_scope(scope_part, default=default)
    if cid.startswith("peer_"):
        return "dual_role"
    if cid in {"default", "default_user", "default_local", "default_user_local"}:
        return "user"

    marker = "__persona__" if "__persona__" in cid else "__circle__" if "__circle__" in cid else ""
    if marker:
        slug = cid.rsplit(marker, 1)[-1].strip("_").split("__", 1)[0]
        resolved = resolve_persona_slug_scope(slug)
        if resolved:
            return resolved
        return _unknown_persona_scope(slug)

    resolved = resolve_persona_slug_scope(cid)
    if resolved:
        return resolved
    return normalize_data_scope(default, default="aveline")


def resolve_memory_user_id(conversation_id: Optional[str]) -> str:
    """把 persona 会话统一转换为 ``<base>__scope__<scope>``。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return "default"
    if "__persona__" not in cid and "__circle__" not in cid:
        return cid
    marker = "__persona__" if "__persona__" in cid else "__circle__"
    base = cid.split(marker, 1)[0].rstrip("_")
    scope = resolve_data_scope_from_conversation_id(cid)
    return f"{base}__scope__{scope}"


def resolve_data_scope_from_source(
    source: Optional[str],
    *,
    default: str = "user",
) -> str:
    """从业务 source 或角色别名解析 scope。"""
    raw = str(source or "").strip().lower()
    if raw in {"ling", "wang_ling", "Ling"}:
        return "ling"
    if raw in {
        "aveline",
        "qilai_wei",
        "七濑 澪",
        "active_care",
        "dual_role",
        "background_circle",
    }:
        return "aveline"
    return normalize_data_scope(raw, default=default)


def get_registered_role_scopes() -> set[str]:
    """返回当前所有角色 scope，不包含 user/dual_role。"""
    init_scope_registry()
    return set(_VALID_SCOPES - _SPECIAL_SCOPES)


def get_dynamic_scope_dir_name(scope: str) -> Optional[str]:
    init_scope_registry()
    info = _DYNAMIC_SCOPES.get(str(scope or "").strip().lower())
    return str(info["dir"]) if info else None


def list_dynamic_scopes() -> dict[str, dict]:
    init_scope_registry()
    return {
        scope: {"dir": info["dir"], "slugs": sorted(info["slugs"])}
        for scope, info in _DYNAMIC_SCOPES.items()
    }


__all__ = [
    "get_dynamic_scope_dir_name",
    "get_registered_role_scopes",
    "init_scope_registry",
    "list_dynamic_scopes",
    "normalize_data_scope",
    "refresh_scope_registry",
    "resolve_active_persona_scope",
    "resolve_data_scope_from_conversation_id",
    "resolve_data_scope_from_source",
    "resolve_memory_user_id",
    "resolve_persona_slug_scope",
]
