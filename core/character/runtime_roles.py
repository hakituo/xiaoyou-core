"""角色通用运行时能力集合。

这里维护“哪些角色拥有持续自主生活状态”的统一入口。
CharacterDaily、ActivityInstance、睡眠问候、Active Care 等只是消费者，
不再各自维护角色白名单。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(get_project_root()) / "config" / "yaml" / "character_runtime.yaml"
_DEFAULT_AUTONOMOUS_ROLES = frozenset({"aveline", "ling", "ye"})


def _normalize_roles(values: Any) -> frozenset[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(
        str(value or "").strip().lower()
        for value in values
        if str(value or "").strip()
    )


def _load_runtime_yaml_roles() -> frozenset[str]:
    try:
        if not _CONFIG_PATH.exists():
            return frozenset()
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return frozenset()
        return _normalize_roles(raw.get("autonomous_roles"))
    except Exception as exc:  # noqa: BLE001 - 配置损坏不能阻断主服务启动
        logger.warning("读取 character_runtime.yaml 失败: %s", exc)
        return frozenset()


def get_autonomous_role_ids(*, settings: Any = None) -> frozenset[str]:
    """返回拥有持续自主生活状态的角色集合。

    新配置 `config/yaml/character_runtime.yaml` 是权威源。
    为兼容旧部署，文件缺失/为空时才读取旧的
    `life_simulation.active_care_enabled_roles`；两者都不可用时回退到安全默认值。
    """
    configured = _load_runtime_yaml_roles()
    if configured:
        return configured

    try:
        from core.utils.config_accessor import get_config

        legacy = _normalize_roles(
            get_config(
                "life_simulation.active_care_enabled_roles",
                default=None,
                settings=settings,
            )
        )
        if legacy:
            logger.warning(
                "character_runtime.autonomous_roles 未配置，暂用旧 "
                "life_simulation.active_care_enabled_roles；请迁移到通用配置"
            )
            return legacy
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取旧角色白名单失败: %s", exc)

    return _DEFAULT_AUTONOMOUS_ROLES


def is_autonomous_role(role_id: str, *, settings: Any = None) -> bool:
    """判断角色是否属于通用自主生活角色集合。"""
    normalized = str(role_id or "").strip().lower()
    return bool(normalized) and normalized in get_autonomous_role_ids(settings=settings)


def filter_autonomous_roles(
    role_ids: Iterable[str],
    *,
    settings: Any = None,
) -> tuple[str, ...]:
    """按输入顺序筛出自主生活角色，并去重。"""
    allowed = get_autonomous_role_ids(settings=settings)
    result: list[str] = []
    seen: set[str] = set()
    for role_id in role_ids:
        normalized = str(role_id or "").strip().lower()
        if normalized and normalized in allowed and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)
