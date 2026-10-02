from __future__ import annotations

import datetime
import json
import re
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List

from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time

from .config import ANALYSIS_DIR

logger = get_module_logger(__name__, "nightly_processor.log")

NightlyTasksRunner = Callable[[str, Any], Dict[str, Any]]


class NightlyAnalysisService:
    """负责夜间消息分析、权重更新与结果落盘。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    def process_user_chat_history(
        self,
        user_id: str,
        manager: Any,
        *,
        target_date: datetime.date,
        run_nightly_async_tasks: NightlyTasksRunner,
    ) -> Dict[str, Any]:
        """处理单个用户的聊天记录。"""
        logger.info(f"开始处理用户 {user_id} 的聊天记录")

        if isinstance(target_date, datetime.datetime):
            target_date = target_date.date()
        local_tz = get_current_time().tzinfo
        window_start = datetime.datetime.combine(
            target_date,
            datetime.time.min,
            tzinfo=local_tz,
        )
        window_end = window_start + datetime.timedelta(days=1)
        window_start_ts = window_start.timestamp()
        window_end_ts = window_end.timestamp()
        today_messages: List[Dict[str, Any]] = []

        with manager.lock:
            for message in manager.weighted_memories.values():
                message_ts = float(message.get("timestamp", 0) or 0)
                if window_start_ts <= message_ts < window_end_ts:
                    today_messages.append(message)

        logger.info(
            "记忆 scope=%s 在目标日期 %s 共有 %d 条消息",
            user_id,
            target_date.isoformat(),
            len(today_messages),
        )

        topic_counter: Counter[str] = Counter()
        category_counter: Counter[str] = Counter()
        content_analysis = self.analyze_message_content(today_messages)

        for message in today_messages:
            topic_counter.update(message.get("topics", []))
            category = message.get("category")
            if category:
                category_counter[category] += 1

        topic_counter.update(content_analysis["detected_topics"])
        min_freq = self.config["min_frequency"]
        high_frequency_topics = [
            (topic, frequency)
            for topic, frequency in topic_counter.items()
            if frequency >= min_freq
        ]
        high_frequency_topics.sort(key=lambda item: item[1], reverse=True)
        high_frequency_topics = high_frequency_topics[
            : self.config["max_topics_to_update"]
        ]

        logger.info(f"用户 {user_id} 今日高频话题: {high_frequency_topics}")

        updated_topics: List[Dict[str, Any]] = []
        weight_increment = self.config["weight_increment"]
        for topic, _ in high_frequency_topics:
            for memory in manager.get_weighted_memories(topics=[topic], limit=20):
                manager.update_memory_weight(memory["id"], weight_increment)
                updated_topics.append(
                    {
                        "topic": topic,
                        "memory_id": memory["id"],
                        "new_weight": memory.get("weight", 0) + weight_increment,
                    }
                )

        nightly_tasks_result: Dict[str, Any] = {}
        try:
            # distillation_enabled 只由 scope task 内部控制蒸馏步骤，
            # 不能再连带关闭人物档案和全局 nightly 业务。
            nightly_tasks_result = run_nightly_async_tasks(user_id, manager)
        except Exception as exc:
            logger.error(f"夜间 scope 异步任务执行出错: {exc}")

        analysis_result = {
            "user_id": user_id,
            "target_date": target_date.isoformat(),
            "processing_time": datetime.datetime.now().isoformat(),
            "total_messages": len(today_messages),
            "high_frequency_topics": high_frequency_topics,
            "category_distribution": dict(category_counter),
            "updated_topics_count": len(updated_topics),
            "distilled_memories_count": nightly_tasks_result.get("distilled_count", 0),
            "daily_summary_generated": nightly_tasks_result.get("daily_summary", False),
            "monthly_summary_generated": nightly_tasks_result.get(
                "monthly_summary",
                False,
            ),
            "word_frequency": content_analysis["word_frequency"],
            "sentiment_analysis": content_analysis["sentiment_analysis"],
            "most_active_time": content_analysis["most_active_time"],
        }
        if nightly_tasks_result.get("_nightly_error"):
            analysis_result["nightly_scope_error"] = nightly_tasks_result[
                "_nightly_error"
            ]
        self.save_analysis_result(user_id, analysis_result, target_date=target_date)
        logger.info(
            f"用户 {user_id} 处理完成，更新了 {len(updated_topics)} 个话题相关的记忆权重"
        )
        return analysis_result

    @staticmethod
    def analyze_message_content(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析消息内容，提取关键词、话题和情绪。"""
        topic_keywords = {
            "技术": ["编程", "代码", "软件", "算法", "开发", "项目", "架构", "框架"],
            "生活": ["吃饭", "睡觉", "旅游", "购物", "电影", "音乐", "运动", "健康"],
            "工作": [
                "会议",
                "报告",
                "任务",
                "截止日期",
                "同事",
                "客户",
                "公司",
                "老板",
            ],
            "学习": ["考试", "作业", "书籍", "课程", "学校", "成绩", "老师", "学生"],
            "娱乐": [
                "游戏",
                "视频",
                "直播",
                "社交媒体",
                "明星",
                "综艺",
                "动漫",
                "小说",
            ],
            "情感": ["开心", "伤心", "生气", "难过", "高兴", "喜欢", "讨厌", "爱"],
            "天气": ["下雨", "晴天", "温度", "气候", "季节", "台风", "雪"],
            "健康": ["身体", "生病", "医院", "医生", "药物", "锻炼", "饮食", "休息"],
        }
        positive_emotions = ["开心", "高兴", "快乐", "喜欢", "兴奋", "满意", "幸福"]
        negative_emotions = [
            "伤心",
            "难过",
            "生气",
            "讨厌",
            "失望",
            "焦虑",
            "紧张",
            "害怕",
        ]

        word_counter: Counter[str] = Counter()
        detected_topics: List[str] = []
        emotion_scores = {"positive": 0, "negative": 0, "neutral": 0}
        time_counter: defaultdict[int, int] = defaultdict(int)

        for message in messages:
            content = message.get("content", "").lower()
            timestamp = message.get("timestamp", time.time())
            hour = datetime.datetime.fromtimestamp(timestamp).hour
            time_counter[hour] += 1

            words = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z0-9]+", content)
            word_counter.update([word for word in words if len(word) > 1])

            for topic, keywords in topic_keywords.items():
                if any(keyword in content for keyword in keywords):
                    detected_topics.append(topic)

            if any(emotion in content for emotion in positive_emotions):
                emotion_scores["positive"] += 1
            elif any(emotion in content for emotion in negative_emotions):
                emotion_scores["negative"] += 1
            else:
                emotion_scores["neutral"] += 1

        most_active_time = None
        if time_counter:
            most_active_hour = max(time_counter, key=time_counter.get)
            most_active_time = f"{most_active_hour:02d}:00-{most_active_hour + 1:02d}:00"

        return {
            "word_frequency": dict(word_counter.most_common(20)),
            "detected_topics": detected_topics,
            "sentiment_analysis": emotion_scores,
            "most_active_time": most_active_time,
        }

    @staticmethod
    def save_analysis_result(
        user_id: str,
        result: Dict[str, Any],
        *,
        target_date: datetime.date,
    ) -> None:
        """保存分析结果到文件。"""
        try:
            date_key = target_date.strftime("%Y%m%d")
            analysis_file = ANALYSIS_DIR / f"{user_id}_{date_key}.json"
            existing_results: List[Dict[str, Any]] = []

            if analysis_file.exists():
                try:
                    existing_results = json.loads(
                        analysis_file.read_text(encoding="utf-8")
                    )
                except Exception as exc:
                    logger.warning(f"读取现有分析结果时出错: {exc}")

            existing_results.append(result)
            analysis_file.write_text(
                json.dumps(existing_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug(f"已保存用户 {user_id} 的分析结果到 {analysis_file}")
        except Exception as exc:
            logger.error(f"保存分析结果时出错: {exc}")
