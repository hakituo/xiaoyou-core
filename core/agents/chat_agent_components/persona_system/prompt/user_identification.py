import re
from typing import Any, List, Optional

from core.character.aveline import get_aveline_user_profile
from core.character.managers.persona_manager import get_persona_manager
from memory.weighted_memory_manager import WeightedMemoryManager

def resolve_user_name(agent: Any, user_id: str, user_name: Optional[str] = None) -> str:
    """
    确定用户称呼
    优先级: 外部传入 > 配置固定 > 记忆系统(user_name) > 人设推断 > 默认"你"
    """
    if user_name:
        return user_name

    try:
        from config.integrated_config import get_settings
        fixed_name = str(get_settings().user.display_name or "").strip()
        if fixed_name:
            return fixed_name
    except Exception:
        pass

    if user_id:
        try:
            mem_name = _resolve_user_name_from_memory(agent, user_id)
            if mem_name:
                return mem_name
        except Exception:
            pass

    return "你"

def resolve_user_name_from_persona_logic() -> str:
    """从当前人设中尝试解析用户名字"""
    try:
        user_profile = get_aveline_user_profile()
        if user_profile and "name" in user_profile:
            prof_name = str(user_profile.get("name") or "").strip()
            if prof_name:
                return prof_name
    except Exception:
        pass

    try:
        pm = get_persona_manager()
        persona = pm.get_current_persona()
    except Exception:
        persona = {}

    if not isinstance(persona, dict):
        return ""

    candidates: List[str] = []
    identity = persona.get("identity")
    if isinstance(identity, dict):
        core_identity = identity.get("core_identity")
        if isinstance(core_identity, dict):
            candidates.append(str(core_identity.get("primary_objective") or ""))
        candidates.append(str(identity.get("context") or ""))
        candidates.append(str(identity.get("greeting") or ""))

    tmpl = persona.get("system_prompt_template")
    if isinstance(tmpl, str):
        candidates.append(tmpl)
    meta = persona.get("meta")
    if isinstance(meta, dict):
        field_desc = meta.get("field_descriptions")
        if isinstance(field_desc, dict):
            nested_tmpl = field_desc.get("system_prompt_template")
            if isinstance(nested_tmpl, str):
                candidates.append(nested_tmpl)

    patterns = [
        r"陪伴我的\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
        r"created by\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
        r"深深爱着\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
        r"爱着\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
        r"分析\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})\s*话语",
        r"对\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})\s*的事情",
    ]

    for text in candidates:
        s = str(text or "")
        if not s.strip():
            continue
        for pat in patterns:
            m = re.search(pat, s, flags=re.IGNORECASE)
            if m:
                name = (m.group(1) or "").strip()
                if name and name != "用户":
                    return name
    return ""

def _resolve_user_name_from_memory(agent_obj: Any, cid: Optional[str]) -> str:
    """从记忆中解析用户名字"""
    candidates = [str(cid or "").strip(), "default"]
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            mm = agent_obj._get_memory_manager(c)
            if not isinstance(mm, WeightedMemoryManager):
                continue
            with mm.lock:
                memories = sorted(
                    mm.weighted_memories.values(),
                    key=lambda x: x.get("timestamp", 0),
                    reverse=True,
                )

            for mem in memories[:120]:
                if mem.get("category") != "profile" and "profile" not in (mem.get("topics") or []):
                    continue
                content = str(mem.get("content", "") or "")
                m = re.search(r"用户名字\s*[:：]\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})", content)
                if m:
                    return (m.group(1) or "").strip()
        except Exception:
            continue
    return ""
