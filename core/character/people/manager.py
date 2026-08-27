"""
人物档案管理器

职责：
1. 加载三类档案（角色人设/用户自身/人际关系）
2. 按名字/alias 匹配消息中提到的人物
3. 生成注入摘要文本（角色人设 + 用户档案 + 提及人物）
4. 更新档案（夜间提取回写）

缓存策略：
- 角色人设档案：跨请求缓存，人设切换时失效
- 用户自身档案：跨请求缓存，更新时失效
- 人际关系档案：跨请求缓存，更新时失效
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional

from core.utils.data_paths import (
    get_role_profile_path,
    get_user_people_profile_path,
    get_user_people_profiles_dir,
    get_user_person_profile_path,
)
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from .models import (
    PersonProfile,
    ProfileTarget,
    ProfileType,
)

logger = get_logger("PeopleProfileManager")


class PeopleProfileManager:
    """
    人物档案管理器（单例）

    统一管理三类档案的加载、查询、注入和更新。
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 缓存：profile_id → PersonProfile
        self._cache: Dict[str, PersonProfile] = {}
        self._cache_lock = threading.RLock()

        # 人际关系档案索引：name/alias_lower → profile_id
        self._people_name_index: Dict[str, str] = {}
        self._people_index_dirty = True

    # ========== 缓存管理 ==========

    def clear_cache(self) -> None:
        """清除所有缓存（档案更新或人设切换时调用）"""
        with self._cache_lock:
            self._cache.clear()
            self._people_name_index.clear()
            self._people_index_dirty = True

    def clear_role_cache(self, scope: str) -> None:
        """清除某个角色的缓存"""
        with self._cache_lock:
            keys_to_remove = [
                k for k in self._cache
                if k.startswith(f"{scope}_") or k.startswith("role:")
            ]
            for k in keys_to_remove:
                self._cache.pop(k, None)
            self._people_index_dirty = True

    def _get_cached(self, cache_key: str) -> Optional[PersonProfile]:
        with self._cache_lock:
            return self._cache.get(cache_key)

    def _set_cached(self, cache_key: str, profile: PersonProfile) -> None:
        with self._cache_lock:
            self._cache[cache_key] = profile

    # ========== 角色人设档案 ==========

    def get_role_profile(
        self,
        scope: str,
        role_name: str,
        target: str,
    ) -> Optional[PersonProfile]:
        """
        获取角色多版本人设档案

        Args:
            scope: 角色域（aveline/ling）
            role_name: 角色名（如 Aveline / Ling）
            target: 面向对象（如 Qi / Ling / Aveline / default）

        Returns:
            人设档案，不存在返回 None
        """
        cache_key = f"role:{scope}:{role_name}:{target}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        path = get_role_profile_path(scope, role_name, target)
        profile = PersonProfile.load(path)
        if profile is not None:
            self._set_cached(cache_key, profile)
        return profile

    def get_role_profile_for_conversation(
        self,
        conversation_id: Optional[str],
        role_name: str,
    ) -> Optional[PersonProfile]:
        """
        根据 conversation_id 自动路由角色人设档案

        从 conversation_id 推断 scope 和 target，返回对应版本人设。
        例如：
        - 和Master的私聊 → Aveline_Qi
        - 和Ling的背景对话 → Aveline_Ling
        """
        from core.utils.data_paths import resolve_data_scope_from_conversation_id

        scope = resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
        target = self._infer_target_from_conversation(conversation_id, scope)
        return self.get_role_profile(scope, role_name, target)

    def _infer_target_from_conversation(
        self,
        conversation_id: Optional[str],
        scope: str,
    ) -> str:
        """
        从 conversation_id 推断人设面向的对象

        规则：
        - peer_ling* → Aveline 面对Ling → target=Ling
        - peer_aveline* → Ling面对Aveline → target=Aveline
        - 普通私聊 → 面对Master → target=Qi
        - 其他 → default
        """
        cid = str(conversation_id or "").strip().lower()
        if not cid:
            return ProfileTarget.DEFAULT.value

        if cid.startswith("peer_ling") or "__persona__ling" in cid or "__circle__ling" in cid:
            return ProfileTarget.LING.value
        if cid.startswith("peer_aveline") or "__persona__aveline" in cid or "__circle__aveline" in cid:
            return ProfileTarget.AVELINE.value
        # 普通私聊（和Master）
        return ProfileTarget.QI.value

    # ========== 用户自身档案 ==========

    def get_user_self_profile(self) -> Optional[PersonProfile]:
        """获取用户自身档案（Master的基本信息）"""
        cache_key = "self:_self"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        path = get_user_person_profile_path()
        profile = PersonProfile.load(path)
        if profile is not None:
            self._set_cached(cache_key, profile)
        return profile

    # ========== 用户人际关系档案 ==========

    def get_person_profile(self, person_id: str) -> Optional[PersonProfile]:
        """获取用户人际关系中的某个角色档案"""
        cache_key = f"person:{person_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        path = get_user_people_profile_path(person_id)
        profile = PersonProfile.load(path)
        if profile is not None:
            self._set_cached(cache_key, profile)
        return profile

    def list_all_people_profiles(self) -> List[PersonProfile]:
        """列出所有用户人际关系档案"""
        profiles: List[PersonProfile] = []
        profiles_dir = get_user_people_profiles_dir()
        if not profiles_dir.exists():
            return profiles

        for json_file in profiles_dir.glob("*.json"):
            # 跳过以 _ 开头的内部文件（如 _extractor_state.json）
            if json_file.name.startswith("_"):
                continue
            try:
                profile = PersonProfile.load(json_file)
                if profile is not None:
                    profiles.append(profile)
                    # 缓存
                    cache_key = f"person:{profile.profile_id}"
                    self._set_cached(cache_key, profile)
            except Exception as e:
                logger.error(f"加载人物档案失败 {json_file}: {e}")

        return profiles

    def _ensure_people_name_index(self) -> None:
        """确保人际关系名字索引已构建"""
        if not self._people_index_dirty:
            return
        with self._cache_lock:
            self._people_name_index.clear()
            for profile in self.list_all_people_profiles():
                # 名字和所有别名都指向 profile_id
                names = [profile.name] + list(profile.aliases)
                for n in names:
                    n_lower = str(n or "").strip().lower()
                    if n_lower:
                        self._people_name_index[n_lower] = profile.profile_id
            self._people_index_dirty = False

    def find_mentioned_people(self, message_text: str) -> List[PersonProfile]:
        """
        从消息文本中找出提到的人物（基于 alias 字符串匹配）

        Args:
            message_text: 消息文本

        Returns:
            匹配到的人物档案列表
        """
        if not message_text:
            return []

        self._ensure_people_name_index()
        text_lower = message_text.lower()

        matched_ids: set = set()
        matched_profiles: List[PersonProfile] = []

        # 按名字长度倒序匹配（避免"Ling"被"玲"抢先匹配）
        sorted_names = sorted(self._people_name_index.keys(), key=len, reverse=True)
        for name_lower in sorted_names:
            if name_lower in text_lower:
                profile_id = self._people_name_index[name_lower]
                if profile_id not in matched_ids:
                    profile = self.get_person_profile(profile_id)
                    if profile is not None:
                        matched_ids.add(profile_id)
                        matched_profiles.append(profile)

        return matched_profiles

    def find_mentioned_people_semantic(
        self,
        message_text: str,
        top_k: int = 3,
        threshold: float = 0.5,
    ) -> List[PersonProfile]:
        """
        从消息文本中语义匹配人物（复用记忆系统向量）

        用于发现"我那个同学"这种未命名提及。
        当前实现为 alias 匹配的补充，后续接入向量搜索。

        Args:
            message_text: 消息文本
            top_k: 返回最多 top_k 个
            threshold: 相似度阈值

        Returns:
            匹配到的人物档案列表
        """
        # TODO: 后续接入记忆系统的向量搜索
        # 当前先返回空，让 alias 匹配负责
        return []

    # ========== 注入 ==========

    def inject_for_chat(
        self,
        scope: str,
        role_name: str,
        target: str,
        message_text: str = "",
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        生成聊天时的完整人物档案注入文本

        注入策略（分三档）：
        1. 角色自身人设（厚）：core_fields + description
        2. 用户自身档案（厚）：core_fields + description
        3. 提及的其他人物（薄）：仅 description

        Args:
            scope: 角色域（aveline/ling）
            role_name: 角色名（如 Aveline / Ling）
            target: 面向对象（如 Qi / Ling / default）
            message_text: 当前消息文本（用于判断提及谁）
            conversation_id: 会话ID（用于自动路由）

        Returns:
            注入文本
        """
        sections: List[str] = []

        # 1. 角色自身人设
        role_profile = self.get_role_profile(scope, role_name, target)
        if role_profile:
            summary = role_profile.get_injection_summary(thick=True)
            if summary:
                sections.append(f"【你的人设】\n{summary}")

        # 2. 用户自身档案（常驻）
        user_profile = self.get_user_self_profile()
        if user_profile:
            summary = user_profile.get_injection_summary(thick=True)
            if summary:
                sections.append(f"【用户档案】\n{summary}")

        # 3. 提及的其他人物（按需）
        mentioned = self.find_mentioned_people(message_text or "")
        for person in mentioned:
            # 跳过用户自己（已在上一步注入）
            if person.profile_type == ProfileType.SELF:
                continue
            summary = person.get_injection_summary(thick=False)
            if summary:
                sections.append(f"【提及人物】\n{summary}")

        return "\n\n".join(sections) if sections else ""

    # ========== 更新 ==========

    def save_profile(self, profile: PersonProfile) -> bool:
        """
        保存档案到磁盘并更新缓存

        夜间提取器更新档案后调用此方法持久化。
        """
        try:
            # 确定存储路径
            path = self._resolve_profile_path(profile)
            if path is None:
                logger.error(f"无法确定档案存储路径: {profile.profile_id}")
                return False

            profile.updated_at = get_current_time().strftime("%Y-%m-%d %H:%M:%S")
            profile.save(path)

            # 更新缓存
            cache_key = self._make_cache_key(profile)
            if cache_key:
                self._set_cached(cache_key, profile)

            # 人际关系档案更新后，名字索引需要重建
            if profile.profile_type == ProfileType.PERSON:
                self._people_index_dirty = True

            return True
        except Exception as e:
            logger.error(f"保存档案失败 {profile.profile_id}: {e}")
            return False

    def _resolve_profile_path(self, profile: PersonProfile) -> Optional[Path]:
        """根据档案类型解析存储路径"""
        if profile.profile_type == ProfileType.ROLE:
            return get_role_profile_path(
                profile.role_scope,
                profile.name.split()[0] if profile.name else "Role",
                profile.target.value,
            )
        elif profile.profile_type == ProfileType.SELF:
            return get_user_person_profile_path()
        else:  # PERSON
            return get_user_people_profile_path(profile.profile_id)

    def _make_cache_key(self, profile: PersonProfile) -> str:
        """根据档案类型生成缓存键"""
        if profile.profile_type == ProfileType.ROLE:
            return f"role:{profile.role_scope}:{profile.name}:{profile.target.value}"
        elif profile.profile_type == ProfileType.SELF:
            return "self:_self"
        else:  # PERSON
            return f"person:{profile.profile_id}"

    # ========== 查询工具 ==========

    def query_profile_details(self, name_or_alias: str) -> Optional[PersonProfile]:
        """
        按名字或别名查询人物档案的完整详细信息

        供 query_person_profile 工具调用。
        查找顺序：人际关系档案 → 角色人设档案 → 用户自身档案
        """
        query_lower = str(name_or_alias or "").strip().lower()
        if not query_lower:
            return None

        # 1. 人际关系档案
        self._ensure_people_name_index()
        profile_id = self._people_name_index.get(query_lower)
        if profile_id:
            profile = self.get_person_profile(profile_id)
            if profile:
                return profile

        # 2. 用户自身档案
        user_profile = self.get_user_self_profile()
        if user_profile and user_profile.matches_name(query_lower):
            return user_profile

        # 3. 角色人设档案（遍历 aveline/ling 的所有版本）
        for scope in ("aveline", "ling"):
            role_name = "Aveline" if scope == "aveline" else "Ling"
            for target in ProfileTarget:
                profile = self.get_role_profile(scope, role_name, target.value)
                if profile and profile.matches_name(query_lower):
                    return profile

        return None


# ========== 单例入口 ==========

_people_profile_manager: Optional[PeopleProfileManager] = None
_manager_lock = threading.Lock()


def get_people_profile_manager() -> PeopleProfileManager:
    """获取 PeopleProfileManager 单例"""
    global _people_profile_manager
    if _people_profile_manager is None:
        with _manager_lock:
            if _people_profile_manager is None:
                _people_profile_manager = PeopleProfileManager()
    return _people_profile_manager
