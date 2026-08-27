"""
人物档案数据模型

统一的三层结构：
- core_fields: 结构化核心字段（姓名/生日/角色等），常驻注入
- description: 摘要层（一段话总结），常驻注入
- detailed: 详细事实层（性格/语言风格/known_facts），按需查询

档案分三类：
- role: 角色自身人设（Aveline/Ling 的多版本人设，按 target 分版本）
- self: 用户自身档案（Master的基本信息）
- person: 用户人际关系档案（Master视角下的其他人物）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ProfileType(str, Enum):
    """档案类型"""

    ROLE = "role"        # 角色自身人设（Aveline/Ling）
    SELF = "self"        # 用户自身档案（Master）
    PERSON = "person"    # 用户人际关系档案（Master的朋友等）


class ProfileTarget(str, Enum):
    """
    人设面向的对象（仅对 role 类型有意义）

    同一个角色面对不同人会有不同态度：
    - Aveline 对Master：傲娇女友
    - Aveline 对Ling：室友/姐姐
    """

    QI = "qi"              # 面对Master
    LING = "ling"          # 面对Ling
    AVELINE = "aveline"    # 面对Aveline
    DEFAULT = "default"    # 默认/兜底


@dataclass
class KnownFact:
    """
    单条已知事实

    用于 detailed 层，存储细颗粒度的事实信息。
    每条带 confidence，夜间更新时高置信度覆盖低置信度。
    history 字段记录该 key 的历史值（支持体重、年级等会变的属性）。
    """

    key: str                                    # 事实键（如"学校"）
    value: str                                  # 事实值（如"XX高中"）
    confidence: float = 0.5                     # 置信度 0-1
    source: str = "unknown"                     # 来源（seeded/nightly_extracted/runtime）
    updated_at: str = ""                        # 最后更新时间
    history: List[Dict[str, Any]] = field(default_factory=list)  # 历史值记录

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "updated_at": self.updated_at,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnownFact":
        history_raw = data.get("history") or []
        history = [h for h in history_raw if isinstance(h, dict)] if isinstance(history_raw, list) else []
        return cls(
            key=str(data.get("key") or ""),
            value=str(data.get("value") or ""),
            confidence=float(data.get("confidence") or 0.5),
            source=str(data.get("source") or "unknown"),
            updated_at=str(data.get("updated_at") or ""),
            history=history,
        )


@dataclass
class PersonProfile:
    """
    人物档案

    统一模型，覆盖三类档案：角色人设/用户自身/人际关系。
    三层结构：core_fields（核心）+ description（摘要）+ detailed（详细）。
    """

    # === 标识 ===
    profile_id: str                             # 档案唯一ID（如 Aveline_Qi / _self / wang_ling）
    profile_type: ProfileType                   # 档案类型
    name: str                                   # 显示名
    aliases: List[str] = field(default_factory=list)  # 别名/昵称

    # === 路由 ===
    role_scope: str = ""                        # 角色域（aveline/ling/user），仅 role 类型需要
    target: ProfileTarget = ProfileTarget.DEFAULT  # 面向对象，仅 role 类型需要

    # === 三层内容 ===
    core_fields: Dict[str, Any] = field(default_factory=dict)   # 核心结构化字段
    description: str = ""                       # 摘要层（一段话总结，注入用这个）
    detailed: Dict[str, Any] = field(default_factory=dict)      # 详细事实层

    # === 元数据 ===
    source: str = "seeded_from_persona"         # 来源
    first_mentioned: str = ""                   # 首次提及时间
    last_mentioned: str = ""                    # 最后提及时间
    mention_count: int = 0                      # 提及次数
    updated_at: str = ""                        # 最后更新时间

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于持久化）"""
        return {
            "profile_id": self.profile_id,
            "profile_type": self.profile_type.value,
            "name": self.name,
            "aliases": list(self.aliases),
            "role_scope": self.role_scope,
            "target": self.target.value,
            "core_fields": dict(self.core_fields),
            "description": self.description,
            "detailed": dict(self.detailed),
            "source": self.source,
            "first_mentioned": self.first_mentioned,
            "last_mentioned": self.last_mentioned,
            "mention_count": self.mention_count,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonProfile":
        """从字典反序列化"""
        # 兼容 profile_type 字段
        ptype_raw = str(data.get("profile_type") or "person").lower()
        try:
            ptype = ProfileType(ptype_raw)
        except ValueError:
            ptype = ProfileType.PERSON

        # 兼容 target 字段
        target_raw = str(data.get("target") or "default").lower()
        try:
            target = ProfileTarget(target_raw)
        except ValueError:
            target = ProfileTarget.DEFAULT

        return cls(
            profile_id=str(data.get("profile_id") or ""),
            profile_type=ptype,
            name=str(data.get("name") or ""),
            aliases=list(data.get("aliases") or []),
            role_scope=str(data.get("role_scope") or ""),
            target=target,
            core_fields=dict(data.get("core_fields") or {}),
            description=str(data.get("description") or ""),
            detailed=dict(data.get("detailed") or {}),
            source=str(data.get("source") or "seeded_from_persona"),
            first_mentioned=str(data.get("first_mentioned") or ""),
            last_mentioned=str(data.get("last_mentioned") or ""),
            mention_count=int(data.get("mention_count") or 0),
            updated_at=str(data.get("updated_at") or ""),
        )

    def save(self, path: Path) -> None:
        """保存到 JSON 文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> Optional["PersonProfile"]:
        """从 JSON 文件加载"""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None

    # === 便捷访问 ===

    def get_known_facts(self) -> List[KnownFact]:
        """获取详细事实层的 known_facts 列表"""
        facts_raw = self.detailed.get("known_facts") or []
        if not isinstance(facts_raw, list):
            return []
        return [KnownFact.from_dict(f) for f in facts_raw if isinstance(f, dict)]

    def add_known_fact(self, fact: KnownFact) -> None:
        """
        添加或更新一条已知事实

        同 key 的事实：高置信度覆盖低置信度，同置信度则更新。
        当 value 发生变化时，把旧值 push 到新事实的 history 里
        （支持体重、年级等会变的属性保留历史轨迹）。
        """
        facts = self.get_known_facts()
        existing_idx = None
        for i, f in enumerate(facts):
            if f.key == fact.key:
                existing_idx = i
                break

        if existing_idx is not None:
            existing = facts[existing_idx]
            # 值变化时，把旧值记入 history（保留旧 history 轨迹）
            if fact.value != existing.value:
                fact.history = list(existing.history)
                fact.history.append({
                    "value": existing.value,
                    "updated_at": existing.updated_at,
                    "source": existing.source,
                })
            else:
                # 值没变，保留旧 history
                fact.history = list(existing.history)

            # 高置信度覆盖低置信度；同置信度也更新（新信息）
            if fact.confidence >= existing.confidence:
                facts[existing_idx] = fact
            else:
                # 低置信度不覆盖高置信度，但保留作为备选
                facts.append(fact)
        else:
            facts.append(fact)

        self.detailed["known_facts"] = [f.to_dict() for f in facts]

    def touch_mention(self, timestamp: str = "") -> None:
        """更新提及时间戳和计数"""
        if not self.first_mentioned:
            self.first_mentioned = timestamp
        self.last_mentioned = timestamp
        self.mention_count += 1
        self.updated_at = timestamp

    def matches_name(self, query: str) -> bool:
        """
        判断查询字符串是否匹配本档案的名字或别名

        用于运行时判断"消息里是否提到了这个人"。
        """
        query_lower = query.strip().lower()
        if not query_lower:
            return False
        if query_lower == self.name.strip().lower():
            return True
        for alias in self.aliases:
            if alias and query_lower == alias.strip().lower():
                return True
        return False

    def get_injection_summary(self, *, thick: bool = False) -> str:
        """
        生成注入摘要文本

        Args:
            thick: True 返回较厚的摘要（含 core_fields），
                   False 返回精简摘要（仅 description）

        Returns:
            注入到 prompt 的摘要文本
        """
        lines: List[str] = []

        if thick and self.core_fields:
            lines.append(f"姓名：{self.name}")
            for k, v in self.core_fields.items():
                if v:
                    lines.append(f"{k}：{v}")
            if self.description:
                lines.append(f"简介：{self.description}")
        else:
            if self.description:
                lines.append(f"{self.name}：{self.description}")
            elif self.core_fields:
                # 没有 description 时回退到 core_fields
                parts = [f"{k}={v}" for k, v in self.core_fields.items() if v]
                if parts:
                    lines.append(f"{self.name}（{'，'.join(parts)}）")

        return "\n".join(lines) if lines else ""
