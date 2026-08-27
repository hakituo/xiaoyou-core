"""学习模式检测与科目分类 — 薄 re-export 层

实际逻辑已迁移到 core.services.study.mode_detector，
本文件保留仅为向后兼容，使 chat_agent.py 等调用方无需修改 import。
"""
import random
import time
from typing import Any, Dict, Optional

from core.services.study.mode_detector import (
    is_study_mode,
    classify_subject,
)
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")

__all__ = ["is_study_mode", "classify_subject", "get_english_word_context"]


def get_english_word_context(agent: Any) -> Optional[Dict[str, str]]:
    """从 agent 的词汇队列中取出下一个单词上下文（聊天注入用）。"""
    if not getattr(agent, "vocab_manager", None):
        return None

    try:
        if not agent.daily_word_queue:
            agent.daily_word_queue = agent.vocab_manager.get_daily_words(limit=20)
            random.shuffle(agent.daily_word_queue)
            if agent.daily_word_queue:
                logger.info(
                    f"Refilled daily word queue with {len(agent.daily_word_queue)} words"
                )

        while agent.daily_word_queue:
            word_obj = agent.daily_word_queue.pop(0)
            word = word_obj.get("word")
            # 跳过本轮已复习（已排到未来）的词，避免同一词在会话中反复出现，
            # 造成「他每次都说」的体感。
            if word and _is_word_already_done(agent, word):
                continue
            trans = word_obj.get("translations", [])

            trans_str = "; ".join(
                [f"{t.get('type')}. {t.get('translation')}" for t in trans]
            )

            return {
                "word": word,
                "meaning": trans_str,
                "status": word_obj.get("status", "new"),
            }
    except Exception as e:
        logger.warning(f"Failed to get English word: {e}")

    return None


def _is_word_already_done(agent: Any, word: str) -> bool:
    """判断某词本轮是否已复习（FSRS 已将其排到未来）。

    读取 vocab 进度：fsrs_due 为未来时间戳即说明刚复习过且未到期，跳过可避免
    同一词在同一会话里反复推送。
    """
    try:
        vm = getattr(agent, "vocab_manager", None)
        if vm is None:
            return False
        store = getattr(vm, "store", None)
        if store is None:
            return False
        progress = getattr(store, "progress", None)
        if not progress:
            return False
        data = progress.get(word.strip().lower())
        if not data:
            return False
        due = data.get("fsrs_due")
        if not due:
            return False
        return due > time.time()
    except Exception:
        return False
