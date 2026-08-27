"""工具调度器 —— 替代 service.py 中的巨型 run_tool if-elif 链

设计原则：
1. 每个工具是独立 handler 函数，注册到 (category, tool_id) 映射表
2. 统一的 async-to-sync 辅助函数，消除重复的事件循环包装
3. 新增工具只需添加一个 handler 并注册，无需修改调度逻辑
"""
import asyncio
import json
from typing import Any, Callable, Dict

from core.utils.logger import get_logger

logger = get_logger("StudyDispatcher")


def _run_async_in_sync(coro_factory: Callable) -> Any:
    """在同步上下文中安全运行 async 协程，处理嵌套事件循环。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:

            def _run_sync():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(coro_factory())
                finally:
                    new_loop.close()

            return executor.submit(_run_sync).result()
    else:
        return asyncio.run(coro_factory())


def _parse_json_or_str(raw: Any) -> Any:
    """尝试将字符串解析为 JSON，失败则原样返回。"""
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return raw


class ToolDispatcher:
    """将 (category, tool_id) 映射到具体处理函数的调度器。"""

    def __init__(self, study_service: Any):
        self._svc = study_service
        self._base_dir = study_service.base_dir
        # 注册表：(category, tool_id) -> handler(params) -> Dict
        self._handlers: Dict[tuple, Callable] = {
            ("study_data", "manage"): self._handle_study_data,
            ("english", "word_quiz"): self._handle_word_quiz,
        }

    def dispatch(
        self, category: str, tool_id: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        handler = self._handlers.get((category, tool_id))
        if handler is None:
            return {
                "status": "error",
                "message": f"Tool not implemented or supported: {category}/{tool_id}",
            }
        try:
            return handler(params)
        except Exception as e:
            logger.error(f"Tool error [{category}/{tool_id}]: {e}")
            return {"status": "error", "message": str(e)}

    # ================================================================
    # 各工具 handler
    # ================================================================

    def _handle_study_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from core.tools.study_data_tool import StudyDataTool

        tool = StudyDataTool()
        result_str = _run_async_in_sync(lambda: tool._run(**params))
        return {"status": "success", "data": _parse_json_or_str(result_str)}

    def _handle_word_quiz(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # source: "daily"（每日新背日志） / "unfamiliar"（长期生词本） /
        # "both"（一次读取两者并保持结果分区，避免模型混淆来源）。
        source = str(params.get("source") or "daily").strip().lower()
        action = params.get("action", "quiz")
        count = int(params.get("count", 5))
        word = params.get("word")
        priority = params.get("priority", "random")
        raw_days = params.get("days")
        days = int(raw_days) if raw_days is not None else None
        date = params.get("date")

        if source not in {"daily", "unfamiliar", "both"}:
            return {
                "status": "error",
                "message": (
                    f"Unsupported word source: {source}. "
                    "Expected daily, unfamiliar, or both."
                ),
            }

        if source == "both":
            if action not in {"quiz", "stats"}:
                return {
                    "status": "error",
                    "message": (
                        "source=both only supports quiz/stats; choose daily or "
                        "unfamiliar for mark actions."
                    ),
                }
            return {
                "status": "success",
                "source": "both",
                "sources": {
                    "daily": self._run_daily_word_action(
                        action=action,
                        count=count,
                        word=word,
                        priority=priority,
                        days=days,
                        date=date,
                    ),
                    "unfamiliar": self._run_unfamiliar_word_action(
                        action=action,
                        count=count,
                        word=word,
                        priority=priority,
                    ),
                },
            }

        if source == "daily":
            return self._run_daily_word_action(
                action=action,
                count=count,
                word=word,
                priority=priority,
                days=days,
                date=date,
            )
        return self._run_unfamiliar_word_action(
            action=action,
            count=count,
            word=word,
            priority=priority,
        )

    @staticmethod
    def _run_daily_word_action(
        *,
        action: str,
        count: int,
        word: Any,
        priority: str,
        days: Any,
        date: Any,
    ) -> Dict[str, Any]:
        """执行 daily 来源动作，并把来源范围写入结果供模型核对。"""
        from core.tools.study.english.daily_word_log import get_daily_word_log

        log = get_daily_word_log()
        effective_date = date
        if effective_date is None and days is None:
            effective_date = log.get_yesterday_str()
        scope = (
            {"date": effective_date, "mode": "yesterday_default"}
            if effective_date
            else {"days": days, "mode": "recent_days"}
        )
        if action == "quiz":
            words = log.quiz(
                count=count,
                days=days or 1,
                date=effective_date,
                priority=priority,
            )
            dates_with_words = sorted(
                {
                    hit_date
                    for item in words
                    for hit_date in (
                        item.get("dates")
                        or ([item.get("date")] if item.get("date") else [])
                    )
                },
                reverse=True,
            )
            return {
                "status": "success",
                "source": "daily",
                "scope": scope,
                "dates_with_words": dates_with_words,
                "words": words,
            }
        if action == "stats":
            if effective_date:
                words = log.get_words_for_date(effective_date)
                result = {
                    "status": "success",
                    "total_words": len(words),
                    "struggling_words": sum(
                        1 for item in words if item.get("unknown_count", 0) >= 2
                    ),
                    "max_unknown_count": max(
                        (item.get("unknown_count", 0) for item in words),
                        default=0,
                    ),
                    "dates_with_words": [effective_date] if words else [],
                }
            else:
                result = log.stats(days=days or 1)
            return {**result, "source": "daily", "scope": scope}
        if action == "mark_unknown":
            if not word:
                return {"status": "error", "message": "Missing word"}
            return {
                "status": "success",
                "source": "daily",
                "data": log.mark_unknown(word, date=date),
            }
        if action == "mark_known":
            if not word:
                return {"status": "error", "message": "Missing word"}
            return {
                "status": "success",
                "source": "daily",
                "data": log.mark_known(word, date=date),
            }
        return {
            "status": "error",
            "source": "daily",
            "message": f"Unsupported word_quiz action: {action}",
        }

    def _run_unfamiliar_word_action(
        self,
        *,
        action: str,
        count: int,
        word: Any,
        priority: str,
    ) -> Dict[str, Any]:
        """执行长期生词本动作，并显式标注来源。"""
        from core.tools.study.english.unfamiliar_word_book import (
            get_unfamiliar_word_book,
        )

        book = get_unfamiliar_word_book()
        if action == "quiz":
            linked_words = None
            try:
                vocab_manager = getattr(self._svc, "vocab_manager", None)
                if vocab_manager is not None:
                    linked_words = vocab_manager.get_linked_unfamiliar_words()
            except Exception as exc:
                logger.warning("读取 App 错题联动词池失败，回退文件生词本: %s", exc)
            return {
                "status": "success",
                "source": "unfamiliar",
                "linked_with_app_mistakes": linked_words is not None,
                "words": book.quiz(
                    count=count,
                    word=word,
                    priority=priority,
                    word_pool=linked_words,
                ),
            }
        if action == "stats":
            return {**book.stats(), "source": "unfamiliar"}
        if action == "mark_unknown":
            if not word:
                return {"status": "error", "message": "Missing word"}
            return {
                "status": "success",
                "source": "unfamiliar",
                "data": book.mark_unknown(word),
            }
        if action == "mark_known":
            if not word:
                return {"status": "error", "message": "Missing word"}
            return {
                "status": "success",
                "source": "unfamiliar",
                "data": book.mark_known(word),
            }
        return {
            "status": "error",
            "source": "unfamiliar",
            "message": f"Unsupported word_quiz action: {action}",
        }
