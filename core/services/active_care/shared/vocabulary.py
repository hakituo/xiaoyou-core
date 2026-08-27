#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time_str
from config.integrated_config import get_settings
from core.services.active_care.storage.storage import ActiveCareStorage
from core.utils.data_paths import get_user_data_dir

logger = get_logger("ACTIVE_CARE_VOCAB")


class ActiveCareVocabulary:
    def __init__(self, storage: ActiveCareStorage):
        self.settings = get_settings()
        self.storage = storage

    def _get_runtime_dir(self) -> str:
        return str(get_user_data_dir())

    async def check_daily_vocabulary(self):
        """检查并推送每日单词（如果今天还没有推送）"""
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

                # 3. 推送通知
                from core.managers.notification_manager import get_notification_manager

                nm = get_notification_manager()
                nm.add_notification(
                    user_id="default",
                    type="vocabulary",
                    title="每日单词 (20个)",
                    content="点击查看今日单词...",  # 简短预览
                    payload={"full_text": content},
                )

                try:
                    from core.interfaces.websocket.websocket_manager import (
                        get_websocket_manager,
                    )

                    ws_manager = get_websocket_manager()
                    if (
                        ws_manager
                        and getattr(ws_manager, "connections", None)
                        and len(ws_manager.connections) > 0
                    ):
                        await ws_manager.broadcast(
                            {
                                "type": "notification",
                                "title": "每日单词 (20个)",
                                "content": "每日单词已更新，点击查看今日单词...",
                                "data": {"type": "vocabulary", "full_text": content},
                                "timestamp": time.time(),
                            }
                        )
                except Exception as e:
                    logger.warning(f"Daily vocabulary websocket push failed: {e}")

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

                # 5. 推送通知
                from core.managers.notification_manager import get_notification_manager

                nm = get_notification_manager()
                nm.add_notification(
                    user_id="default",
                    type="word_quiz",
                    title="每日生词测验",
                    content="来测测这些单词你认不认识吧！",
                    payload={"full_text": content, "words": words},
                )

                try:
                    from core.interfaces.websocket.websocket_manager import (
                        get_websocket_manager,
                    )

                    ws_manager = get_websocket_manager()
                    if (
                        ws_manager
                        and getattr(ws_manager, "connections", None)
                        and len(ws_manager.connections) > 0
                    ):
                        await ws_manager.broadcast(
                            {
                                "type": "notification",
                                "title": "每日生词测验",
                                "content": "来测测这些单词你认不认识吧！",
                                "data": {
                                    "type": "word_quiz",
                                    "full_text": content,
                                    "words": words,
                                },
                                "timestamp": time.time(),
                            }
                        )
                except Exception as e:
                    logger.warning(f"Daily word quiz websocket push failed: {e}")

                # 6. 保存状态
                status[today_str] = True
                await self.storage.write_json_file(quiz_status_file, status)

                logger.info("Daily word quiz pushed (%d words).", len(words))

            except Exception as e:
                logger.error(f"Error processing word quiz: {e}")

        except Exception as e:
            logger.error(f"Failed to generate daily word quiz: {e}")
