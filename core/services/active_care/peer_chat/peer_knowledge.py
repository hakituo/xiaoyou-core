"""双角色互聊知识防火墙（信息权限隔离）

核心目标：消除 Peer Chat 的"两个角色共享一个数据库脑子"的认知泄漏
（epistemic leakage），并阻止主人私聊素材跨关系泄漏到互聊剧本里。

信息分层（每个角色只能说自己权限内的话）：

- shared_context          双方共同可观察的公共事实（时间、双方可见活动）
- role.private_state      角色 A 自己的内部状态（精力/心情/饥饿）
- role.known_about_peer   角色 A 观察/知道的对方（可观察活动、生病等）
- role.master_material    角色 A 与主人的私聊素材（仅 A 自己知道）
- peer.private_state      角色 B 自己的内部状态
- peer.known_about_role   角色 B 观察/知道的 A
- peer.master_material    角色 B 与主人的私聊素材（仅 B 自己知道）

剧本生成器虽然能同时看到双方全部状态，但最高规则约束：
角色只能依据"自己知道"的信息说话，不得使用其本人尚不知道、未观察到、
未被告诉的信息。与主人的私聊内容属于"该角色自己知道"，除非是显然可观察
的日常琐事，否则不得向对方转述。

另提供 validate_peer_script：对生成剧本做代码级越权/泄漏/私密检查（Validator 层）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT", "peer_chat.log")

# 主人私聊素材中的保密信号：命中则整行不进入 Peer Chat
_SECRECY_MARKERS = (
    "先别告诉", "别告诉", "不要告诉", "别告诉她", "别告诉他",
    "别跟她说", "别跟他说", "别和别人说", "别跟别人说", "别和她说",
    "保密", "只告诉你", "只跟你说", "悄悄", "偷偷", "这是我们之间",
    "不要让", "别让她知道", "别让他知道", "别说出去", "不要说出去",
)

# 角色内部状态（他人不可知）：精力/心情/饥饿/健康分
_PRIVATE_LIFE_KEYS = ("energy", "mood", "mood_score", "hunger", "thirst", "health")

# 可被同居室友观察的状态：当前活动、生病
_OBSERVABLE_KEYS = ("current_activity", "activity", "is_sick")


def filter_secret_lines(text: str) -> str:
    """从主人私聊素材中剔除含保密信号的整行（该行只对当事角色可见）。

    逐行过滤而非整段丢弃：保留其余可分享的日常内容，避免素材完全为空。
    """
    if not str(text or "").strip():
        return ""
    kept = []
    for line in str(text).splitlines():
        if any(marker in line for marker in _SECRECY_MARKERS):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _life(bio_state: Any) -> Dict[str, Any]:
    """兼容获取 bio_state.life（旧结构 life 直接平铺的也接受）"""
    if not isinstance(bio_state, dict):
        return {}
    life = bio_state.get("life")
    if isinstance(life, dict):
        return life
    return dict(bio_state)


def _observable_desc(bio_state: Any) -> str:
    """从角色状态提取"对方可观察"的描述（活动/生病），空则返回空串。"""
    life = _life(bio_state)
    parts: List[str] = []
    activity = str(
        life.get("current_activity")
        or life.get("activity")
        or (bio_state.get("activity") if isinstance(bio_state, dict) else "")
        or ""
    ).strip()
    if activity and str(activity).lower() not in ("unknown", "idle", "none"):
        parts.append(f"在{activity}")
    is_sick = False
    for src in (life, bio_state if isinstance(bio_state, dict) else {}):
        if src.get("is_sick"):
            is_sick = True
            break
    if is_sick:
        parts.append("身体不太舒服")
    return "，".join(parts) if parts else ""


def _private_desc(bio_state: Any) -> str:
    """从角色状态提取"自己内部"的描述（精力/心情/饥饿），空则返回空串。"""
    life = _life(bio_state)
    parts: List[str] = []

    def _f(key: str, default: float = 50.0) -> float:
        try:
            v = float(life.get(key, default))
            return v
        except (TypeError, ValueError):
            return default

    energy = _f("energy")
    if energy < 20:
        parts.append("很累")
    elif energy < 50:
        parts.append("有点疲惫")
    elif energy > 80:
        parts.append("精力不错")

    # mood 兼容新旧字段（mood / mood_score）
    mood_raw = life.get("mood")
    if mood_raw in (None, ""):
        mood_raw = life.get("mood_score")
    mood = str(mood_raw or "").strip()
    if mood and mood.lower() not in ("neutral", "normal", "unknown", "none"):
        parts.append(f"心情{mood}")

    hunger = _f("hunger", 100.0)
    if hunger < 30:
        parts.append("很饿")
    elif hunger < 60:
        parts.append("有点饿了")

    return "，".join(parts) if parts else ""


def build_knowledge_buckets(
    *,
    role_id: str,
    peer_role_id: str,
    role_name: str,
    peer_name: str,
    bio_state: Any,
    peer_bio_state: Any,
    master_history_by_role: Dict[str, str],
    time_str: str = "",
) -> Dict[str, Any]:
    """把双方状态 + 主人私聊素材按信息权限拆分为知识分桶。

    Returns:
        {
          "time_str": ...,
          "shared_context": 双方共同可观察事实（时间 + 双方可见活动）
          "role":   {"private_state":..., "known_about_peer":..., "master_material":...}
          "peer":   {"private_state":..., "known_about_peer":..., "master_material":...}
          "role_id" / "peer_role_id": 供 Validator 判断说话者
        }
    """
    shared_parts: List[str] = []
    if time_str:
        shared_parts.append(f"当前时间：{time_str}")

    role_observable = _observable_desc(bio_state)
    peer_observable = _observable_desc(peer_bio_state)
    # 双方住在一起，彼此正在做什么是可观察的公共事实。
    # 注意主语与描述的对应关系：说"你看到 X"时描述必须是 X 的活动，
    # 说"X 看到你"时描述必须是"你"（= role）的活动 —— 两者不能对调，
    # 否则会把角色自己的活动当成对方的活动写进 prompt（认知串味）。
    if peer_observable:
        shared_parts.append(f"你看到{peer_name}：{peer_observable}")
    if role_observable:
        shared_parts.append(f"{peer_name}看到你：{role_observable}")

    role_master = filter_secret_lines(str(master_history_by_role.get(role_id) or ""))
    peer_master = filter_secret_lines(str(master_history_by_role.get(peer_role_id) or ""))

    return {
        "time_str": time_str,
        "shared_context": "，".join(shared_parts) if shared_parts else "",
        "role": {
            "private_state": _private_desc(bio_state),
            "known_about_peer": _observable_desc(peer_bio_state),
            "master_material": role_master,
        },
        "peer": {
            "private_state": _private_desc(peer_bio_state),
            "known_about_peer": _observable_desc(bio_state),
            "master_material": peer_master,
        },
        "role_id": role_id,
        "peer_role_id": peer_role_id,
    }


# ============================================================
# ⑥ Validator：剧本越权 / 隐私泄漏 / 私密信号代码级检查
# ============================================================

# 对方内部状态的关键词：命中时检查说话者是否有权限
_PRIVATE_STATE_KEYWORDS = (
    "很累", "有点疲惫", "疲惫", "精力", "心情", "饿了", "很饿", "没吃饱",
)
# 保密信号（剧本里角色说出主人明确要保密的内容）
_SCRIPT_SECRECY_MARKERS = (
    "别告诉", "别和别人说", "保密", "只告诉你", "别跟", "不要告诉",
)


def validate_peer_script(
    script: List[Dict[str, Any]],
    knowledge: Dict[str, Any],
    *,
    role_id: str = "",
    peer_role_id: str = "",
) -> List[str]:
    """代码级校验剧本是否存在信息越权/隐私泄漏。

    检查项：
    1. 说话者提到对方"私有状态"（对方精力/心情/饥饿只有对方自己知道）→ 越权
    2. 剧本中出现保密信号（主人明确要求保密的内容被搬进互聊）→ 泄漏
    3. 剧本引用主人私聊素材时，必须由对应角色说出，且不能由对方转述

    Args:
        script: 剧本列表 [{role, content}]
        knowledge: build_knowledge_buckets 的结果（含各角色权限范围）

    Returns:
        违规项列表（空表示通过）
    """
    if not script:
        return []
    k = knowledge or {}
    rid = str(role_id or k.get("role_id") or "").strip()
    pid = str(peer_role_id or k.get("peer_role_id") or "").strip()
    violations: List[str] = []

    role_private = str((k.get("role") or {}).get("private_state") or "").strip()
    peer_private = str((k.get("peer") or {}).get("private_state") or "").strip()
    role_known_peer = str((k.get("role") or {}).get("known_about_peer") or "").strip()
    peer_known_role = str((k.get("peer") or {}).get("known_about_peer") or "").strip()

    for idx, line in enumerate(script):
        speaker = str(line.get("role") or "").strip()
        content = str(line.get("content") or "").strip()
        if not content:
            continue
        is_role = speaker == rid or (rid and speaker and speaker not in (pid, ""))

        # 1. 越权：角色提到对方私有状态（仅当对方私有描述非空且说话者已知范围里没有）
        # private_of_other = 对方的私有状态；known_of_other = **说话者**对对方的已知范围。
        # 判定逻辑是"说出对方私有特征词，但该词不在说话者观察得到的信息里"→ 越权。
        # 所以 is_role 时应取 role.known_about_peer（role 视角下对 peer 的已知），
        # 取成 peer.known_about_peer（peer 视角下对 role 的已知）会把两侧对调。
        private_of_other = peer_private if is_role else role_private
        known_of_other = role_known_peer if is_role else peer_known_role
        if private_of_other and known_of_other:
            # 对方私有描述里的特征词，若未出现在"已知对方"描述中，则属于越权
            for kw in _PRIVATE_STATE_KEYWORDS:
                if kw in private_of_other and kw not in known_of_other and kw in content:
                    violations.append(
                        f"第{idx + 1}条越权：{speaker}提到对方的私有状态『{kw}』"
                        f"（对方自己才知道，{speaker}不该知道）"
                    )
                    break

        # 2. 保密信号：角色说出保密内容
        for marker in _SCRIPT_SECRECY_MARKERS:
            if marker in content:
                violations.append(
                    f"第{idx + 1}条隐私风险：出现保密信号『{marker}』，"
                    f"可能是主人明确要求保密的内容被搬进互聊"
                )
                break

    if violations:
        logger.warning(
            "Peer Chat: 剧本校验未通过 %d 项: %s",
            len(violations), " | ".join(violations),
        )
    return violations
