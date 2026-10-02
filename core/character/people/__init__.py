"""
人物档案系统

提供结构化的人物/角色档案存储、查询和注入能力。
档案分三类：
1. 角色自身人设档案（Aveline/Ling 的多版本人设，按面对对象分版本）
2. 用户自身档案（Master的基本信息）
3. 用户人际关系档案（Master视角下的其他人物）

所有档案统一使用 PersonProfile 数据模型，由 PeopleProfileManager 管理。
"""

from .models import PersonProfile, ProfileType, ProfileTarget
from .manager import get_people_profile_manager, PeopleProfileManager
from .extractor import PeopleProfileExtractor

__all__ = [
    "PersonProfile",
    "ProfileType",
    "ProfileTarget",
    "PeopleProfileManager",
    "get_people_profile_manager",
    "PeopleProfileExtractor",
]
