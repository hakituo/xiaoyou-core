"""
用户画像服务
负责管理用户画像数据的读写，与状态追踪完全独立

职责：
- 管理用户画像数据的读写
- 提供画像补全优先级查询接口
- 提供已覆盖话题查询/更新接口
- 管理 daily_push_priority 分析结果
"""
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger("USER_PROFILE", "active_care_schedule.log")

# 画像话题关键词映射表
PORTRAIT_KEYWORD_MAP: Dict[str, List[str]] = {
    "wakeup": [
        "起床", "醒了", "起来", "早安", "早上好", "刚醒", "睡醒",
        "自然醒", "闹钟", "起来了", "刚起来", "早起了",
    ],
    "meal": [
        "吃了", "吃完", "吃饭", "吃了饭", "吃了面", "吃了早", "吃了午", "吃了晚",
        "吃饱", "吃好", "吃过了", "正在吃", "在吃", "点了外卖", "喝了粥",
        "吃了个", "刚吃完", "不用吃了", "早餐", "午饭", "晚饭", "夜宵",
    ],
    "sleep": [
        "晚安", "睡了", "要睡", "去睡", "困了", "好困", "想睡",
        "准备睡", "先睡", "躺下", "不睡了",
    ],
    "activity": [
        "出门", "回来", "到家", "在外面", "逛街", "运动", "锻炼",
        "健身", "跑步", "散步", "打球", "游泳", "骑车", "爬山",
        "在家", "没出门", "宅着",
    ],
    "study": [
        "学习", "看书", "写作业", "复习", "背单词", "上课",
        "刷题", "做卷子", "写代码", "查资料", "在学", "学完",
    ],
    "mood": [
        "心情好", "心情不好", "开心", "难过", "烦", "郁闷", "emo",
        "焦虑", "压力", "累", "放松", "平静", "兴奋", "满足",
    ],
    "health": [
        "不舒服", "生病", "头疼", "肚子疼", "感冒", "发烧",
        "咳嗽", "嗓子疼", "胃不舒服", "难受", "好多了", "恢复",
        "吃药", "去医院", "看医生", "体检",
    ],
}

# 健康相关话题列表
HEALTH_TOPICS = ["wakeup", "sleep", "meal", "activity", "study", "mood", "health"]


class UserProfileService:
    """用户画像服务，独立于状态追踪"""

    def __init__(self, storage):
        """
        Args:
            storage: ActiveCareStorage 实例，用于持久化
        """
        self.storage = storage
        self._cache: Dict[str, Any] = {}
        self._cache_loaded = False

    async def get_profile(self, scope: Optional[str] = None) -> Dict[str, Any]:
        """获取用户画像数据

        Args:
            scope: 可选的 scope（双QQ模式下隔离不同角色）

        Returns:
            用户画像字典
        """
        if not self._cache_loaded or scope:
            profile = await self.storage.get_user_profile(scope=scope)
            if not scope:
                self._cache = profile
                self._cache_loaded = True
            return profile
        return self._cache

    async def save_profile(self, updates: Dict[str, Any], scope: Optional[str] = None) -> Dict[str, Any]:
        """保存用户画像数据

        Args:
            updates: 要更新的键值对
            scope: 可选的 scope

        Returns:
            更新后的完整画像
        """
        result = await self.storage.save_user_profile(updates, scope=scope)
        if not scope:
            self._cache.update(updates)
        return result

    # ==================== 画像优先级 ====================

    async def get_portrait_priority(self, scope: Optional[str] = None) -> List[str]:
        """获取画像补全优先级列表"""
        profile = await self.get_profile(scope=scope)
        return profile.get("portrait_priority") or []

    async def set_portrait_priority(self, priority: List[str], scope: Optional[str] = None):
        """设置画像补全优先级列表"""
        await self.save_profile({"portrait_priority": priority}, scope=scope)

    # ==================== 已覆盖话题 ====================

    async def get_covered_topics(self, scope: Optional[str] = None) -> List[str]:
        """获取用户已覆盖的话题列表"""
        profile = await self.get_profile(scope=scope)
        return profile.get("covered_topics") or []

    async def add_covered_topics(self, topics: List[str], scope: Optional[str] = None):
        """添加已覆盖话题

        Args:
            topics: 要添加的话题列表
            scope: 可选的 scope
        """
        if not topics:
            return
        current = await self.get_covered_topics(scope=scope)
        merged = list(set(current + topics))
        await self.save_profile({"covered_topics": merged}, scope=scope)

    async def set_covered_topics(self, topics: List[str], scope: Optional[str] = None):
        """设置已覆盖话题列表"""
        await self.save_profile({"covered_topics": topics}, scope=scope)

    # ==================== 每日推送优先级 ====================

    async def get_daily_push_priority(self, scope: Optional[str] = None) -> Dict[str, Any]:
        """获取每日推送优先级分析结果"""
        profile = await self.get_profile(scope=scope)
        return profile.get("daily_push_priority") or {}

    async def save_daily_push_priority(
        self,
        *,
        date: str,
        ranked: List[Any],
        summary: str = "",
        raw_text: str = "",
        reduced_mode: bool = False,
        scope: Optional[str] = None,
    ):
        """保存每日推送优先级分析结果

        Args:
            date: 日期字符串 YYYY-MM-DD
            ranked: 排序后的优先级列表
            summary: 摘要
            raw_text: 原始文本
            reduced_mode: 是否处于减少模式
            scope: 可选的 scope
        """
        now = time.time()
        priority_data = {
            "date": date,
            "ranked": ranked,
            "summary": summary[:300],
            "raw_text": raw_text[:8000],
            "analysis_ts": now,
            "reduced_mode": reduced_mode,
        }
        await self.save_profile({"daily_push_priority": priority_data}, scope=scope)

    async def is_daily_push_priority_valid(self, date: str, scope: Optional[str] = None) -> bool:
        """检查每日推送优先级是否有效（是否是今天的）

        Args:
            date: 日期字符串 YYYY-MM-DD
            scope: 可选的 scope

        Returns:
            是否有效
        """
        priority = await self.get_daily_push_priority(scope=scope)
        return priority.get("date") == date and bool(priority.get("ranked"))

    # ==================== 画像完整度 ====================

    async def get_portrait_completeness(self, scope: Optional[str] = None) -> Dict[str, Any]:
        """获取画像完整度信息"""
        profile = await self.get_profile(scope=scope)
        return profile.get("portrait_completeness") or {}

    async def set_portrait_completeness(self, completeness: Dict[str, Any], scope: Optional[str] = None):
        """设置画像完整度信息"""
        await self.save_profile({"portrait_completeness": completeness}, scope=scope)

    # ==================== 话题覆盖检测 ====================

    def detect_user_already_covered(self, recent_history: List[Dict[str, Any]]) -> set:
        """检测用户最近消息中已经明确表示过的话题

        通过关键词匹配用户最近的消息，判断用户是否已经明确表示
        起床/吃饭/睡觉等，避免 LLM 生成矛盾的内容。

        Args:
            recent_history: 最近聊天记录

        Returns:
            已覆盖的话题集合，如 {"wakeup", "meal"}
        """
        if not recent_history:
            return set()

        # 只取用户消息
        user_texts = []
        for msg in recent_history:
            if str(msg.get("role", "")).lower() == "user":
                content = str(msg.get("content", "")).strip().lower()
                if content:
                    user_texts.append(content)

        if not user_texts:
            return set()

        combined_text = " ".join(user_texts)
        covered = set()

        for topic, keywords in PORTRAIT_KEYWORD_MAP.items():
            if any(kw in combined_text for kw in keywords):
                covered.add(topic)

        return covered

    def check_keyword_coverage(
        self,
        recent_history: List[Dict[str, Any]],
        candidate_topics: List[str],
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        """关键词兜底检测：检查用户最近消息中是否包含画像话题关键词

        Args:
            recent_history: 最近聊天记录
            candidate_topics: 候选画像话题列表
            exclude: 已检测到的话题，跳过

        Returns:
            已覆盖的话题列表
        """
        exclude_set = set(exclude or [])
        topics_to_check = [t for t in candidate_topics if t not in exclude_set]
        if not topics_to_check or not recent_history:
            return []

        # 只取用户消息，拼接为小写文本
        user_texts = []
        for msg in recent_history:
            if str(msg.get("role", "")).lower() == "user":
                content = str(msg.get("content", "")).strip().lower()
                if content:
                    user_texts.append(content)

        if not user_texts:
            return []

        combined_text = " ".join(user_texts)
        covered = []
        for topic in topics_to_check:
            keywords = PORTRAIT_KEYWORD_MAP.get(topic, [])
            if any(kw in combined_text for kw in keywords):
                covered.append(topic)

        return covered

    # ==================== 缓存管理 ====================

    def invalidate_cache(self):
        """使缓存失效"""
        self._cache = {}
        self._cache_loaded = False
