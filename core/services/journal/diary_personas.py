"""写日记的角色集合 —— 唯一入口。

真源是「注册角色」：``config/yaml/character_runtime.yaml`` 的 ``autonomous_roles``
（经 :mod:`core.character.runtime_roles` 读取）。角色画像（中英文名、scope）来自
:mod:`core.services.dual_role.personas` 的权威注册表。

日记链路（nightly 生成 / journal 读写 / persona 导出）一律从这里取角色，
**禁止再硬编码 aveline / ling**：注册了谁就给谁写日记，没注册的角色不写。
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger(__name__)

# 主人自己的日记 scope（不是角色，但读取日记条目时必须一起带上）
OWNER_SCOPE = "user"

# 日记里对「主人」的称呼（按角色视角）。未登记的角色默认用"他"。
_USER_ADDRESS_LABELS: Dict[str, str] = {
    "aveline": "用户",
    "ling": "他",
    "ye": "主人",
}
_DEFAULT_USER_LABEL = "他"


def _registered_role_ids() -> frozenset:
    """读取注册角色（拥有持续自主生活状态的角色集合）。"""
    try:
        from core.character.runtime_roles import get_autonomous_role_ids

        return frozenset(
            str(role_id or "").strip().lower()
            for role_id in get_autonomous_role_ids()
            if str(role_id or "").strip()
        )
    except Exception as exc:  # noqa: BLE001 - 配置异常不能让日记链路整个挂掉
        logger.warning("读取注册角色失败，本次无角色可写日记: %s", exc)
        return frozenset()


def get_diary_persona_ids() -> Tuple[str, ...]:
    """返回需要写日记的 role_id（有序、去重）。

    顺序优先跟随 ``PERSONAS`` 的注册顺序（aveline → ling → yeye → ye …），
    注册了但不在画像表里的角色排在后面，保证多次调用顺序稳定。
    """
    from core.services.dual_role.personas import PERSONAS

    configured = _registered_role_ids()
    if not configured:
        return ()
    ordered = [role_id for role_id in PERSONAS if role_id in configured]
    ordered.extend(sorted(configured.difference(ordered)))
    return tuple(ordered)


def is_diary_persona(role_id: str) -> bool:
    """该 role_id 是否是「注册了、要写日记」的角色。"""
    normalized = str(role_id or "").strip().lower()
    return bool(normalized) and normalized in get_diary_persona_ids()


def _profile(role_id: str):
    from core.services.dual_role.personas import get_persona

    return get_persona(str(role_id or "").strip().lower())


def get_diary_persona_name(role_id: str) -> str:
    """角色的权威中文名；未注册画像时回退 role_id 本身（绝不猜成别的角色）。"""
    profile = _profile(role_id)
    if profile is not None:
        return profile.cn_name
    return str(role_id or "").strip()


def get_diary_persona_names() -> Tuple[str, ...]:
    """注册角色的权威中文名列表（与 :func:`get_diary_persona_ids` 同序）。"""
    return tuple(get_diary_persona_name(role_id) for role_id in get_diary_persona_ids())


def get_diary_display_name(role_id: str) -> str:
    """日记/聊天上下文里该角色的自称标签。

    Aveline 用英文名（历史数据与 prompt 都这么写），其余角色用中文权威名。
    """
    profile = _profile(role_id)
    if profile is not None:
        return str(profile.en_name or profile.cn_name or role_id)
    return str(role_id or "").strip()


def get_diary_user_label(role_id: str) -> str:
    """日记上下文里该角色怎么称呼主人。"""
    return _USER_ADDRESS_LABELS.get(
        str(role_id or "").strip().lower(), _DEFAULT_USER_LABEL
    )


def get_diary_peer_ids(role_id: str) -> Tuple[str, ...]:
    """当前角色「认识」的其他注册角色（用于室友互动/证据边界）。

    判据统一走 ``personas.knows_role``：没有登记互识关系的角色（Ye等单角色）
    返回空元组 —— 它的日记里不该出现别人的对话。
    """
    from core.services.dual_role.personas import knows_role

    normalized = str(role_id or "").strip().lower()
    if not normalized:
        return ()
    return tuple(
        other
        for other in get_diary_persona_ids()
        if other != normalized and knows_role(normalized, other)
    )


def get_diary_entry_scopes() -> Tuple[str, ...]:
    """读取当天日记条目时要扫描的 scope（主人 + 所有注册角色）。"""
    return (OWNER_SCOPE, *get_diary_persona_ids())


def get_diary_read_scopes() -> Tuple[str, ...]:
    """「查看日记」场景要扫描的 scope（主人 + 注册角色 + 历史角色）。

    与 :func:`get_diary_entry_scopes` 的区别：后者只覆盖**当前注册**的角色，
    服务于写日记 / 生成 / 导出；而前端的日记浏览必须能看到**以前注册过、
    现在没注册**的角色留下的日记（不注册只是不再新增，历史不该消失），
    所以这里把画像表里登记过的角色 scope 一并纳入。

    多扫一个不存在的目录是廉价且安全的（``glob`` 前会先判 ``exists()``），
    宁可多扫也不能让历史日记读不出来。
    """
    from core.services.dual_role.personas import PERSONAS

    scopes: list[str] = [OWNER_SCOPE]
    for role_id in (*get_diary_persona_ids(), *PERSONAS.keys()):
        normalized = str(role_id or "").strip().lower()
        if normalized and normalized not in scopes:
            scopes.append(normalized)
    return tuple(scopes)


def get_diary_source_label(source: Optional[str]) -> str:
    """日记作者的展示名（供前端直接显示，避免前端再维护一份角色名硬编码）。

    - ``user``（主人手记）→ 「我」
    - 注册/历史角色 → 该角色在日记语境里的自称（Aveline 用英文名，其余用中文权威名）
    - 完全未知的 source → 原样返回，绝不猜成别的角色
    """
    normalized = str(source or "").strip().lower()
    if not normalized or normalized == OWNER_SCOPE:
        return "我"
    return get_diary_display_name(normalized)


def get_diary_summary_scopes(role_id: Optional[str] = None) -> Tuple[str, ...]:
    """读取每日总结时的回退链：本角色 → 其他注册角色 → 主人。

    仅「主人汇总视图」这类场景才需要回退；按角色隔离的读取只取第一个。
    """
    normalized = str(role_id or "").strip().lower()
    ids = get_diary_persona_ids()
    if normalized:
        chain = [normalized, *(other for other in ids if other != normalized)]
    else:
        chain = list(ids)
    chain.append(OWNER_SCOPE)
    return tuple(chain)


def iter_diary_persona_ids(role_ids: Iterable[str]) -> Tuple[str, ...]:
    """按输入顺序筛出要写日记的角色（去重）。"""
    allowed = set(get_diary_persona_ids())
    result: list[str] = []
    for role_id in role_ids:
        normalized = str(role_id or "").strip().lower()
        if normalized and normalized in allowed and normalized not in result:
            result.append(normalized)
    return tuple(result)
