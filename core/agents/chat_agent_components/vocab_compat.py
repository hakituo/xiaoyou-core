"""词汇模块兼容辅助。

用于在学习词汇子包缺失时，避免 ChatAgent 导入阶段直接崩溃。
"""

from __future__ import annotations

from typing import Any, Optional

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


def create_vocab_manager() -> Optional[Any]:
    """按需创建词汇管理器。

    当前仓库可能不存在 `core.tools.study` 兼容包。
    这里做延迟导入，缺失时返回 None，让主对话继续可用。
    """
    try:
        from core.tools.study.english.vocabulary_manager import VocabularyManager

        manager = VocabularyManager()
        logger.info("Initialized VocabularyManager")
        return manager
    except ModuleNotFoundError as exc:
        logger.warning("VocabularyManager module unavailable: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Failed to initialize VocabularyManager: %s", exc)
        return None
