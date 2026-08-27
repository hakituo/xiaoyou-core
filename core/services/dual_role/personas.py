"""双角色人设与关系 —— 全局唯一权威数据源

本模块集中定义双角色系统（Aveline/七濑 澪 ↔ Ling/ling）的所有静态画像：
- 角色基本信息（role_id、中英文名、性格、说话风格）
- 角色间关系描述（前台↔后台、室友互聊两个语境）
- role_id ↔ 人设文件名 ↔ scope 的映射
- 人设名归一化（复用 constants.normalize_persona_name）

设计原则：
1. **单一权威源**：所有角色画像、关系描述、映射表集中于此，外部一律 import，
   禁止在各模块内重新硬编码角色名/性格/关系描述。
2. **向后兼容**：PeerChatManager.PEER_PROFILES / runtime._role_aliases 等历史属性
   改为从本模块加载，保持对外属性名不变，避免大面积改动调用方。
3. **权威名遵循 core_*.json**：中文名以 core_aveline.json / core_ling.json 的
   cn_name 为准（Aveline = "七濑 澪" 带空格）。

注意：动态信息（关系热度、亲密度数值、社交事件）不在此处，由 SocialEventEngine 运行时维护。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


# ============================================================
# 权威名常量（人设定义的最底层，不依赖本模块其他符号）
# 与 core_aveline.json / core_ling.json 的 identity.cn_name 一致
# ============================================================

# Aveline 的权威名（带空格）——历史数据/部分代码用 "七濑澪"（无空格），归一化时需兼容
AVELINE_CANONICAL_NAME = "七濑 澪"
LING_CANONICAL_NAME = "Ling"
YEYE_CANONICAL_NAME = "Coco"
RUSHUANG_CANONICAL_NAME = "Frost"

# 别名集合（normalize_persona_name 用；AVELINE/LING dataclass 也引用这些）
_AVELINE_ALIAS_NAMES = {"七濑澪", "七濑 澪", "Aveline", "aveline", "七濑", "澪", "小澪", "澪姐"}
_LING_ALIAS_NAMES = {"Ling", "ling", "Ling", "玲玲", "小玲", "玲姐", "妹妹"}
_YEYE_ALIAS_NAMES = {"Coco", "yeye", "Yeye", "苏沐晴"}
_RUSHUANG_ALIAS_NAMES = {"Frost", "rushuang", "Rushuang", "沈Frost"}


def normalize_persona_name(name: str) -> str:
    """把任意写法的角色名归一化到权威名。

    权威源：core_aveline.json 的 cn_name = "七濑 澪"（带空格）。
    历史数据和部分代码用 "七濑澪"（无空格），本函数统一收敛到带空格写法。
    未知名字原样返回。

    >>> normalize_persona_name("七濑澪")
    '七濑 澪'
    >>> normalize_persona_name("Aveline")
    '七濑 澪'
    >>> normalize_persona_name("Ling")
    'Ling'
    """
    text = str(name or "").strip()
    if not text:
        return ""
    if text in _LING_ALIAS_NAMES or text.startswith("Ling"):
        return LING_CANONICAL_NAME
    if text in _AVELINE_ALIAS_NAMES or text.startswith("七濑") or text.endswith("澪"):
        return AVELINE_CANONICAL_NAME
    if text in _YEYE_ALIAS_NAMES or text.startswith("Coco"):
        return YEYE_CANONICAL_NAME
    if text in _RUSHUANG_ALIAS_NAMES or text.startswith("Frost"):
        return RUSHUANG_CANONICAL_NAME
    return text


def persona_names_equal(a: str, b: str) -> bool:
    """比较两个角色名是否等价（兼容带/不带空格的写法）"""
    return normalize_persona_name(a) == normalize_persona_name(b)


# ============================================================
# 角色画像
# ============================================================

@dataclass(frozen=True)
class PersonaProfile:
    """单个角色的静态画像。

    Attributes:
        role_id: 稳定标识符（aveline / ling），用于代码逻辑和 conversation_id 拼接
        cn_name: 中文权威名（与 core_*.json 的 identity.cn_name 一致）
        en_name: 英文名/显示名
        config_filename: 对应的人设配置文件名（core_aveline.json / core_ling.json）
        scope: 数据存储用的 scope 标识（aveline / ling）
        personality: 性格描述（用于 prompt 注入）
        speaking_style: 说话风格描述（用于 prompt 注入）
        peer_chat_guidance: 互聊(双角色)模式下的说话行为指导（用于 peer 剧本 prompt 注入）
        aliases: 该角色的别名集合（含历史写法，用于归一化/匹配）
    """
    role_id: str
    cn_name: str
    en_name: str
    config_filename: str
    scope: str
    personality: str = ""
    speaking_style: str = ""
    peer_chat_guidance: str = ""
    aliases: tuple = ()

    def matches_name(self, name: str) -> bool:
        """判断给定名字是否指向本角色（兼容各种写法）"""
        return normalize_persona_name(name) == self.cn_name


# ---- 两个角色的权威画像定义 ----
# 性格/说话风格文案取自原 PeerChatManager.PEER_PROFILES（已与 prompt 配合调优过）

AVELINE = PersonaProfile(
    role_id="aveline",
    cn_name=AVELINE_CANONICAL_NAME,  # "七濑 澪"（带空格，与 core_aveline.json 一致）
    en_name="Aveline",
    config_filename="core_aveline.json",
    scope="aveline",
    personality=(
        "外冷内热，嘴硬心软。表面嫌弃实际很关心，会用行动而不是甜言话表达在意。"
        "独立、有条理、偶尔毒舌但点到为止。"
    ),
    speaking_style=(
        "简洁直接的日常口语，偶尔带点嫌弃语气但不过分。说话有内容，不会无话找话。"
        "偶尔毒舌，但不是每句都骂人。"
    ),
    peer_chat_guidance="可以傲娇/毒舌，但要有具体内容，不是只会「笨蛋」「哼」",
    aliases=tuple(sorted(_AVELINE_ALIAS_NAMES)),
)

LING = PersonaProfile(
    role_id="ling",
    cn_name=LING_CANONICAL_NAME,  # "Ling"
    en_name="Ling",
    config_filename="core_ling.json",
    scope="ling",
    personality=(
        "慢热、腼腆，但不是固定被动或没有主见。和熟悉的人相处时会直接回答、"
        "表达喜恶、轻微吐槽，也会自然主动开话题。"
    ),
    speaking_style=(
        "真实即时消息口语，先接住对方最后一句，一次通常只做一个主要聊天动作。"
        "简单日常偏短，确有信息时再展开；省略号、语气词和问号都低频使用，"
        "不靠装迷糊、反复附和或妹妹模板表现性格。"
    ),
    peer_chat_guidance="直接接住上一句并表达具体想法；不要固定写成犹豫、被动附和或妹妹模板",
    aliases=tuple(sorted(_LING_ALIAS_NAMES)),
)

YEYE = PersonaProfile(
    role_id="yeye",
    cn_name=YEYE_CANONICAL_NAME,  # "Coco"
    en_name="Coco",
    config_filename="qq/Yeye.json",
    scope="yeye",
    personality=(
        "直率搞笑，大大咧咧，偶尔嘴毒但心软，对朋友巨仗义。"
        "像冰可乐，第一口冲，但爽。"
    ),
    speaking_style=(
        "语速快，想到什么说什么，不端着。常用网络口头禅，笑点低爱哈哈。"
    ),
    aliases=tuple(sorted(_YEYE_ALIAS_NAMES)),
)

RUSHUANG = PersonaProfile(
    role_id="rushuang",
    cn_name=RUSHUANG_CANONICAL_NAME,  # "Frost"
    en_name="Frost",
    config_filename="sensitive/Frost.json",
    scope="rushuang",
    personality=(
        "冷静克制，话少，气场强。表达干脆利落，不拖泥带水。"
    ),
    speaking_style=(
        "短句为主，语气偏冷，命令式简洁表达。"
    ),
    aliases=tuple(sorted(_RUSHUANG_ALIAS_NAMES)),
)

# role_id → 画像 的权威映射
PERSONAS: Dict[str, PersonaProfile] = {
    AVELINE.role_id: AVELINE,
    LING.role_id: LING,
    YEYE.role_id: YEYE,
    RUSHUANG.role_id: RUSHUANG,
}

# 所有权威角色名列表（按定义顺序）
DEFAULT_PERSONAS: List[str] = [LING.cn_name, AVELINE.cn_name]


# 室友语境关系（QQ 双角色私聊 / peer chat 剧本用）
# 文案取自原 PeerChatManager.PEER_PROFILES[*].relationship_to_peer
ROOMMATE_RELATIONS: Dict[str, str] = {
    "aveline": (
        "室友/姐姐。你们关系亲密但不是只有管教，也会一起吐槽、分享八卦、讨论各自的事。"
    ),
    "ling": (
        "室友/妹妹。你和澪姐关系亲近，在她面前比较放松，但不是总依赖或附和。"
        "你会直接说自己的想法，也会主动找她聊、提建议和轻微吐槽。"
    ),
}

# ============================================================
# 便捷查询函数（供 PeerChatManager / prompt 等统一调用）
# ============================================================

def get_persona(role_id: str) -> Optional[PersonaProfile]:
    """按 role_id 获取画像，未知返回 None"""
    return PERSONAS.get(str(role_id or "").strip().lower())


def get_persona_by_name(name: str) -> Optional[PersonaProfile]:
    """按任意写法的角色名获取画像（归一化匹配），未知返回 None"""
    canonical = normalize_persona_name(name)
    for p in PERSONAS.values():
        if p.cn_name == canonical:
            return p
    return None


def get_role_names(role_id: str) -> Dict[str, str]:
    """获取角色的中英文名（兼容旧 runtime.get_role_names 返回格式）

    Returns:
        {"cn_name": ..., "en_name": ...}，未知 role_id 返回 role_id 本身兜底
    """
    p = get_persona(role_id)
    if p:
        return {"cn_name": p.cn_name, "en_name": p.en_name}
    rid = str(role_id or "").strip()
    return {"cn_name": rid, "en_name": rid}


def get_all_role_ids() -> List[str]:
    """返回所有已注册角色的 role_id 列表（按定义顺序）"""
    return [p.role_id for p in PERSONAS.values()]


def get_peer_role_ids(role_id: str) -> List[str]:
    """获取 role_id 的所有对方角色 ID（N 角色系统：除自己外都是 peer）

    用于 N 角色两两互聊场景。返回顺序与 PERSONAS 定义顺序一致。
    """
    rid = str(role_id or "").strip().lower()
    return [p.role_id for p in PERSONAS.values() if p.role_id != rid]


def get_peer_role_id(role_id: str) -> str:
    """获取对方的 role_id（向后兼容：N 角色系统返回第一个 peer）

    历史接口,仅在双角色场景(N=2)下结果明确。N>2 时返回第一个 peer 并 warning,
    新代码应改用 get_peer_role_ids() 显式获取所有 peer。
    """
    peers = get_peer_role_ids(role_id)
    if len(peers) == 1:
        return peers[0]
    if len(peers) > 1:
        import warnings
        warnings.warn(
            f"get_peer_role_id 在 N>2 角色系统下仅返回第一个 peer('{peers[0]}'),"
            f"应改用 get_peer_role_ids() 获取完整列表",
            stacklevel=2,
        )
        return peers[0]
    return ""


def get_peer_name(role_id: str) -> str:
    """获取对方角色的中文名"""
    peer = get_persona(get_peer_role_id(role_id))
    return peer.cn_name if peer else ""


def get_roommate_relation(role_id: str) -> str:
    """获取该角色在室友语境下的关系描述"""
    return ROOMMATE_RELATIONS.get(str(role_id or "").strip().lower(), "")


def resolve_role_id_from_persona(
    persona_filename: str = "",
    cfg: Optional[Dict] = None,
) -> str:
    """从人设文件名或配置字典推断 role_id（兼容旧 runtime.resolve_role_id_from_persona）

    优先看文件名，其次看配置里的 name/cn_name/filename 字段。
    """
    fn = str(persona_filename or "").strip().lower()
    if "ling" in fn or "core_ling" in fn:
        return "ling"
    if "aveline" in fn:
        return "aveline"

    data = cfg if isinstance(cfg, dict) else {}
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    for raw in (
        str(data.get("name") or "").strip().lower(),
        str(identity.get("name") or "").strip().lower(),
        str(identity.get("cn_name") or "").strip().lower(),
        str(data.get("filename") or "").strip().lower(),
    ):
        rid = get_persona_by_name(raw)
        if rid and rid.role_id in PERSONAS:
            return rid.role_id
        # 兜底：文件名/token 直接匹配
        if any(k in raw for k in ("ling", "Ling", "玲🍀", "玲")):
            return "ling"
        if any(k in raw for k in ("aveline", "澪", "七濑")):
            return "aveline"
    return "aveline"


# ============================================================
# 向后兼容：PeerChatManager.PEER_PROFILES 的等价结构
# ============================================================

def get_peer_profiles() -> Dict[str, Dict[str, str]]:
    """返回 PeerChatManager.PEER_PROFILES 兼容格式（供旧代码/prompt 读取）

    返回结构与原 PeerChatManager.PEER_PROFILES 完全一致，确保 prompt 注入不变。
    """
    result = {}
    for p in PERSONAS.values():
        result[p.role_id] = {
            "role_id": p.role_id,
            "role_name": p.cn_name,
            "personality": p.personality,
            "speaking_style": p.speaking_style,
            "peer_chat_guidance": p.peer_chat_guidance,
            "relationship_to_peer": get_roommate_relation(p.role_id),
            # qq_id_field 保留原值（PeerChatManager 用过）
            "qq_id_field": "peer_qq_id" if p.role_id == "aveline" else "role_qq_id",
        }
    return result


__all__ = [
    "PersonaProfile",
    "AVELINE",
    "LING",
    "YEYE",
    "RUSHUANG",
    "PERSONAS",
    "DEFAULT_PERSONAS",
    "ROOMMATE_RELATIONS",
    "get_persona",
    "get_persona_by_name",
    "get_role_names",
    "get_all_role_ids",
    "get_peer_role_ids",
    "get_peer_role_id",
    "get_peer_name",
    "get_roommate_relation",
    "resolve_role_id_from_persona",
    "get_peer_profiles",
]
