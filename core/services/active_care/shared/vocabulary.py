#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from core.utils.logger import get_logger
from core.utils.time_utils import current_hour, get_current_time_str
from config.integrated_config import get_settings
from core.services.active_care.storage.storage import ActiveCareStorage
from core.utils.data_paths import get_user_data_dir

logger = get_logger("ACTIVE_CARE_VOCAB")

# 读取不到配置时的默认每日单词推送时刻（早上 8 点，与催背时刻 12/16/20/22 错开）
DEFAULT_DAILY_VOCAB_PUSH_HOURS = (8,)


class ActiveCareVocabulary:
    def __init__(self, storage: ActiveCareStorage):
        self.settings = get_settings()
        self.storage = storage

    def _get_runtime_dir(self) -> str:
        return str(get_user_data_dir())

    @staticmethod
    def _daily_push_hours() -> list:
        """读取每日单词推送时刻（study.daily_vocab_push_hours，默认早上 8 点）。"""
        try:
            return get_settings().study.get_daily_vocab_push_hours()
        except Exception as e:
            logger.debug(
                f"读取每日单词推送时刻失败，使用默认 {DEFAULT_DAILY_VOCAB_PUSH_HOURS}: {e}"
            )
            return list(DEFAULT_DAILY_VOCAB_PUSH_HOURS)

    def daily_vocab_push_due(self) -> bool:
        """现在是否到了每日单词的推送时刻（供维护循环判断）。

        维护循环每小时跑一次，所以"何时推"收敛到这里的一个可配置时刻：
        - 未到最早的配置时刻 → 不推；
        - 已到 → 推（服务在时刻之后才启动时，当天补推一次）；
        - 今天已经推过 → 由 daily_vocab_status.json 的按日期去重兜底，不会重复。

        配置多个时刻时以最早的为准：每日单词一天只推一次，多配的时刻只是
        把"补推窗口"提前，不会变成多次轰炸。
        """
        if not getattr(self.settings.study, "enabled", False):
            return False
        return current_hour() >= min(self._daily_push_hours())

    async def check_daily_vocabulary(self):
        """推送今日单词（每天最多一次）。

        由 Active Care 维护循环在 study.daily_vocab_push_hours 到点后调用
        （见 core/services/active_care/core/watchdog.py）；到点判断在
        daily_vocab_push_due()，这里只负责"今天还没推过就推一次"。
        """
        try:
            if not getattr(self.settings.study, "enabled", False):
                return

            # 1. 检查状态文件
            runtime_dir = self._get_runtime_dir()
            vocab_file = os.path.join(runtime_dir, "daily_vocab_status.json")

            today_str = get_current_time_str("%Y-%m-%d")
            status = await self.storage.read_json_file(vocab_file)

            if status.get(today_str, False):
                return  # Already pushed today

            # 2. 从管理器获取单词
            logger.info("Fetching daily vocabulary from manager...")
            try:
                from core.tools.study.english.vocabulary_manager import (
                    get_vocabulary_manager,
                )

                vm = get_vocabulary_manager()
                words = vm.get_daily_words(limit=20)

                if not words:
                    logger.warning("No vocabulary words available.")
                    return

                # 格式化内容
                content_lines = ["📅 **每日单词 (Daily Vocabulary)**\n"]
                content_lines.append(
                    "Here are your 20 words for today! Keep it up! ✨\n"
                )

                for idx, item in enumerate(words):
                    word = item["word"]
                    translation = "暂无释义"
                    if item.get("translations"):
                        t = item["translations"][0]
                        translation = f"{t['type']}. {t['translation']}"

                    status_icon = "🆕" if item.get("status") == "new" else "🔄"
                    content_lines.append(
                        f"{idx + 1}. {status_icon} **{word}** - {translation}"
                    )

                content = "\n".join(content_lines)

                # 3. 推送通知（入队 + WebSocket 广播，点击直达背单词页）
                #    以前这里只发 `content` 而安卓端读 `body`，通知正文是空的；
                #    也没带 target，安卓只能靠"单词"关键词猜一个跳转页。
                from core.services.notification.app_push import (
                    TARGET_VOCAB,
                    async_push_app_notification,
                )

                await async_push_app_notification(
                    title="每日单词 (20个)",
                    content="每日单词已更新，点击查看今日单词...",
                    target=TARGET_VOCAB,
                    data={"type": "vocabulary", "full_text": content},
                    notification_type="vocabulary",
                )

                # 4. 保存状态
                status[today_str] = True
                await self.storage.write_json_file(vocab_file, status)

                logger.info("Daily vocabulary pushed.")

            except ImportError:
                logger.error("VocabularyManager not found.")
            except Exception as e:
                logger.error(f"Error processing vocabulary: {e}")

        except Exception as e:
            logger.error(f"Failed to generate daily vocabulary: {e}")

    async def check_daily_word_quiz(self):
        """检查并推送每日生词测验（如果今天还没有推送）"""
        try:
            if not getattr(self.settings.study, "enabled", False):
                return

            # 1. 检查状态文件
            runtime_dir = self._get_runtime_dir()
            quiz_status_file = os.path.join(runtime_dir, "daily_word_quiz_status.json")

            today_str = get_current_time_str("%Y-%m-%d")
            status = await self.storage.read_json_file(quiz_status_file)

            if status.get(today_str, False):
                return  # 今天已经推送过

            # 2. 通过 StudyService 获取生词测验数据
            logger.info("Fetching unfamiliar words for daily quiz...")
            try:
                from core.services.study.service import get_study_service

                result = get_study_service().run_tool(
                    "english",
                    "word_quiz",
                    {"action": "quiz", "count": 5, "priority": "high_count"},
                )

                if result.get("status") != "success":
                    logger.warning(f"Word quiz fetch failed: {result.get('message')}")
                    return

                words = result.get("words", [])
                if not words:
                    logger.info("No unfamiliar words to quiz.")
                    return

                # 3. 获取统计信息
                stats = get_study_service().run_tool(
                    "english",
                    "word_quiz",
                    {"action": "stats"},
                )

                # 4. 格式化推送内容
                content_lines = ["📝 **每日生词测验**\n"]
                content_lines.append("来测测这些单词你认不认识吧！\n")

                for idx, item in enumerate(words):
                    count_str = f"（不认识 {item['unknown_count']} 次）" if item["unknown_count"] > 0 else "（新词）"
                    content_lines.append(
                        f"{idx + 1}. **{item['word']}** {count_str}"
                    )

                if stats.get("status") == "success":
                    total = stats.get("total_words", 0)
                    struggling = stats.get("struggling_words", 0)
                    content_lines.append(
                        f"\n📊 生词本共 {total} 个词，其中 {struggling} 个需要重点复习"
                    )

                content = "\n".join(content_lines)

                # 5. 推送通知（点进去直达背单词页，而不是学习概览）
                from core.services.notification.app_push import (
                    TARGET_VOCAB,
                    async_push_app_notification,
                )

                await async_push_app_notification(
                    title="每日生词测验",
                    content="来测测这些单词你认不认识吧！",
                    target=TARGET_VOCAB,
                    data={"type": "word_quiz", "full_text": content, "words": words},
                    notification_type="word_quiz",
                )

                # 6. 保存状态
                status[today_str] = True
                await self.storage.write_json_file(quiz_status_file, status)

                logger.info("Daily word quiz pushed (%d words).", len(words))

            except Exception as e:
                logger.error(f"Error processing word quiz: {e}")

        except Exception as e:
            logger.error(f"Failed to generate daily word quiz: {e}")
