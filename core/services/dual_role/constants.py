from collections import OrderedDict
from typing import List, Optional
import re


# ============================================================
# 人设相关符号：从 personas 统一权威源 re-export（向后兼容）
# 依赖方向：constants → personas（单向）。真实定义见 personas.py。
# 外部代码 `from .constants import AVELINE_CANONICAL_NAME` 等仍可用。
# ============================================================
from .personas import (  # noqa: F401,E402
    AVELINE_CANONICAL_NAME,
    LING_CANONICAL_NAME,
    normalize_persona_name,
    persona_names_equal,
    AVELINE,
    LING,
    PERSONAS,
    DEFAULT_PERSONAS,
)

# 别名集合（从 personas 同步，保持外部引用名不变）
AVELINE_ALIAS_NAMES = AVELINE.aliases and set(AVELINE.aliases)
LING_ALIAS_NAMES = LING.aliases and set(LING.aliases)


def _build_source_map() -> dict:
    """构建 source token → 中文名 映射（从 PERSONAS 动态生成）

    自动覆盖每个角色的 role_id、config_filename(去掉.json)以及历史别名。
    新增角色时无需手工维护此表。
    """
    mapping = {}
    # 历史别名补充（不在 PersonaProfile.aliases 里,但旧数据/代码用过的 token）
    _LEGACY_ALIASES = {
        "aveline": ["qilai_wei", "qise_lei"],
        "ling": ["wang_ling"],
    }
    for p in PERSONAS.values():
        # role_id 作为 source token
        mapping[p.role_id] = p.cn_name
        # 别名
        for alias in (p.aliases or ()):
            mapping[str(alias).lower()] = p.cn_name
        # 历史别名
        for alias in _LEGACY_ALIASES.get(p.role_id, []):
            mapping[alias] = p.cn_name
    return mapping


def _build_file_map() -> dict:
    """构建 中文名/英文名 → 配置文件名 映射（从 PERSONAS 动态生成）"""
    mapping = {}
    for p in PERSONAS.values():
        mapping[p.cn_name] = p.config_filename
        if p.en_name:
            mapping[p.en_name] = p.config_filename
    return mapping


def _build_scope_map() -> dict:
    """构建 中文名 → scope 映射（从 PERSONAS 动态生成）"""
    return {p.cn_name: p.scope for p in PERSONAS.values()}


# 动态生成映射表（新增角色时自动包含,无需手工维护）
PERSONA_SOURCE_MAP = _build_source_map()
PERSONA_FILE_MAP = _build_file_map()
PERSONA_SCOPE_MAP = _build_scope_map()

LING_PERSONAS = {LING.cn_name}


def get_persona_scope(persona_name: str) -> str:
    """获取角色 scope（委托给 personas，兼容各种名字写法）"""
    from .personas import get_persona_by_name
    p = get_persona_by_name(persona_name)
    return p.scope if p else "aveline"


MIN_FRAGMENT_LEN = 4

LOW_SIGNAL_FRAGMENTS = {"你也是，早点休息", "嗯，你也是", "早点休息", "有"}

MAX_RECENT_FOR_DEDUP = 20


def infer_persona_name(content: str, tags: Optional[List[str]] = None, source: str = "") -> Optional[str]:
    """从内容推断说话角色名。兼容「七濑 澪」(带空格，官方) 和「七濑澪」(无空格，历史数据) 两种写法。"""
    content = str(content or "")
    if content.startswith("Ling："):
        return "Ling"
    if content.startswith("七濑 澪：") or content.startswith("七濑澪："):
        return "七濑 澪"

    tags_set = {str(tag).strip() for tag in (tags or []) if str(tag).strip()}
    if "Ling" in tags_set:
        return "Ling"
    if "七濑" in tags_set or "澪" in tags_set:
        return "七濑 澪"

    source_lower = str(source or "").strip().lower()
    if source_lower in PERSONA_SOURCE_MAP:
        return PERSONA_SOURCE_MAP[source_lower]
    return None


def normalize_fragment(text: str) -> str:
    candidate = " ".join(str(text or "").split())
    candidate = re.sub(r"[，,；;。!?！？]\s*[发哈啊呀呢嘛吧]$", "", candidate)
    candidate = re.sub(r"(。){2,}", "。", candidate)
    if "，" in candidate:
        left, right = candidate.rsplit("，", 1)
        if right.strip() and len(right.strip()) <= 1:
            candidate = left.strip()
    if "," in candidate:
        left, right = candidate.rsplit(",", 1)
        if right.strip() and len(right.strip()) <= 1:
            candidate = left.strip()
    candidate = candidate.rstrip("。！？；,.，、")
    return candidate.strip()


class RecentContentDedup:
    def __init__(self, max_size: int = MAX_RECENT_FOR_DEDUP):
        self._max_size = max_size
        self._recent: OrderedDict = OrderedDict()

    def add(self, content: str) -> None:
        key = content.lower().strip()
        self._recent[key] = True
        while len(self._recent) > self._max_size:
            self._recent.popitem(last=False)

    def is_duplicate(self, content: str) -> bool:
        return content.lower().strip() in self._recent
