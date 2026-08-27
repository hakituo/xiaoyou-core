"""Nightly 记忆蒸馏执行服务。"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from core.services.journal.summary_guard import is_polluted_daily_summary_memory
from core.utils.logger import get_module_logger

from .config import get_memory_distillation_model
from .distillation_codec import DistillationCodec

logger = get_module_logger(__name__, "nightly_processor.log")
SchedulerProvider = Callable[[], Any]


class MemoryDistillationService(DistillationCodec):
    """执行单个记忆 scope 的候选筛选、批量请求与失败回退。"""

    def __init__(
        self,
        config: Dict[str, Any],
        scheduler_provider: SchedulerProvider,
    ) -> None:
        self.config = config
        self._scheduler_provider = scheduler_provider

    async def distill_memories_async(self, user_id: str, manager: Any) -> int:
        """筛选旧记忆并调用 LLM 进行蒸馏。"""
        threshold_hours = self.config.get("distillation_threshold_hours", 1)
        max_distill = self.config.get("max_distill_per_night", 50)
        threshold_ts = time.time() - (threshold_hours * 3600)
        recent_window_start_ts = time.time() - 86400
        distillation_model = get_memory_distillation_model()
        to_distill = self._collect_candidates(
            manager,
            threshold_ts,
            recent_window_start_ts,
            max_distill,
        )
        if not to_distill:
            return 0

        logger.info("发现 %d 条待蒸馏记忆，开始压缩...", len(to_distill))
        scheduler = self._scheduler_provider()
        gap_seconds = (
            float(self.config.get("distillation_group_gap_minutes") or 30) * 60
        )
        batch_size = int(self.config.get("distillation_batch_size") or 10)
        distilled_count = 0
        for group in self.group_memories_by_time(
            to_distill,
            gap_seconds,
            batch_size,
        ):
            short_items, long_items = self._split_by_length(group)
            distilled_count += self._persist_short_items(manager, short_items)
            if long_items:
                distilled_count += await self._distill_batch(
                    scheduler,
                    manager,
                    long_items,
                    distillation_model,
                )
        return distilled_count

    @staticmethod
    def _collect_candidates(
        manager: Any,
        threshold_ts: float,
        recent_window_start_ts: float,
        max_distill: int,
    ) -> List[Dict[str, Any]]:
        """在锁内收集本晚需要蒸馏的加权记忆。"""
        candidates: List[Dict[str, Any]] = []
        with manager.lock:
            for message in manager.weighted_memories.values():
                timestamp = float(message.get("timestamp", 0) or 0)
                if (
                    message.get("is_distilled")
                    or timestamp >= threshold_ts
                    or timestamp < recent_window_start_ts
                ):
                    continue
                if is_polluted_daily_summary_memory(message):
                    logger.warning(
                        "跳过被污染的每日总结记忆，不纳入蒸馏队列 [%s]",
                        str(message.get("id", ""))[:8],
                    )
                    continue
                candidates.append(message)
                if len(candidates) >= max_distill:
                    break
        return candidates

    @staticmethod
    def _split_by_length(
        group: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """把无需 LLM 的短内容和批量 LLM 内容分开。"""
        short_items = [
            item
            for item in group
            if not item.get("content") or len(str(item.get("content", ""))) < 20
        ]
        long_items = [
            item
            for item in group
            if item.get("content") and len(str(item.get("content", ""))) >= 20
        ]
        return short_items, long_items

    @classmethod
    def _persist_short_items(
        cls,
        manager: Any,
        messages: List[Dict[str, Any]],
    ) -> int:
        """短内容直接落盘，不消耗 LLM 请求。"""
        persisted = 0
        for message in messages:
            try:
                content = message.get("content", "")
                metadata = cls.detect_profile_signals_locally(
                    str(content or ""),
                    role=str(message.get("role") or ""),
                )
                if manager.update_memory_distillation(
                    message["id"],
                    content,
                    [],
                    distillation_metadata=metadata,
                ):
                    persisted += 1
            except Exception as exc:
                logger.error("蒸馏短内容 %s 时出错: %s", message.get("id"), exc)
        return persisted

    async def _distill_batch(
        self,
        scheduler: Any,
        manager: Any,
        messages: List[Dict[str, Any]],
        distillation_model: Optional[str],
    ) -> int:
        """蒸馏一个时间连续批次，失败时逐条回退。"""
        llm_kwargs: Dict[str, Any] = {
            "max_tokens": max(512, len(messages) * 150),
            "temperature": 0.3,
        }
        if distillation_model:
            llm_kwargs["model_hint"] = distillation_model
        full_response = ""
        try:
            prompt = self.generate_batch_distillation_prompt(messages)
            async for chunk in scheduler.submit_llm_task(prompt, **llm_kwargs):
                if isinstance(chunk, str):
                    full_response += chunk
                elif isinstance(chunk, dict) and chunk.get("content"):
                    full_response += chunk["content"]
        except Exception as exc:
            logger.error("批量蒸馏失败（%d 条），回退逐条: %s", len(messages), exc)
            persisted = 0
            for message in messages:
                if await self.distill_one_async(
                    scheduler,
                    manager,
                    message,
                    distillation_model,
                ):
                    persisted += 1
            return persisted
        return self._persist_batch_response(manager, messages, full_response)

    def _persist_batch_response(
        self,
        manager: Any,
        messages: List[Dict[str, Any]],
        response: str,
    ) -> int:
        """解析并落盘一个批量响应。"""
        results = self.parse_batch_distillation_response(response)
        profile_signals = self.parse_batch_profile_signals(response)
        persisted = 0
        for index, message in enumerate(messages, start=1):
            try:
                entry = results.get(index)
                if not entry:
                    logger.warning(
                        "批量蒸馏结果缺失条目 %d [%s]，原始响应长度=%s",
                        index,
                        message["id"][:8],
                        len(response),
                    )
                    continue
                summary, keywords = entry
                logger.info(
                    "蒸馏结果 [%s]: summary='%s', keywords=%s",
                    message["id"][:8],
                    summary,
                    keywords,
                )
                metadata = profile_signals.get(
                    index,
                    self.empty_profile_signals(analyzed=False),
                )
                if manager.update_memory_distillation(
                    message["id"],
                    summary,
                    keywords,
                    distillation_metadata=metadata,
                ):
                    persisted += 1
                    logger.info(
                        "蒸馏成功 [%s]: 梗概='%s...', 关键词=%s",
                        message["id"][:8],
                        summary[:30],
                        keywords[:3],
                    )
                else:
                    logger.warning("更新记忆失败 [%s]", message["id"][:8])
            except Exception as exc:
                logger.error("蒸馏单条记忆 %s 时出错: %s", message.get("id"), exc)
        return persisted

    async def distill_one_async(
        self,
        scheduler: Any,
        manager: Any,
        message: Dict[str, Any],
        distillation_model: Optional[str],
    ) -> bool:
        """单条记忆蒸馏，供批量失败时回退。"""
        try:
            content = message.get("content", "")
            if not content or len(content) < 20:
                metadata = self.detect_profile_signals_locally(
                    str(content or ""),
                    role=str(message.get("role") or ""),
                )
                return bool(
                    manager.update_memory_distillation(
                        message["id"],
                        content,
                        [],
                        distillation_metadata=metadata,
                    )
                )
            role = str(message.get("role") or "unknown")
            prompt = self.generate_distillation_prompt(
                f"【说话者】{role}\n{content}"
            )
            full_response = ""
            llm_kwargs: Dict[str, Any] = {
                "max_tokens": 200,
                "temperature": 0.3,
            }
            if distillation_model:
                llm_kwargs["model_hint"] = distillation_model
            async for chunk in scheduler.submit_llm_task(prompt, **llm_kwargs):
                if isinstance(chunk, str):
                    full_response += chunk
                elif isinstance(chunk, dict) and chunk.get("content"):
                    full_response += chunk["content"]
            summary, keywords = self.parse_distillation_response(full_response)
            metadata = self.parse_profile_signals(full_response)
            if not summary:
                logger.warning(
                    "蒸馏结果为空 [%s]: response='%s'",
                    message["id"][:8],
                    full_response[:100],
                )
                return False
            if manager.update_memory_distillation(
                message["id"],
                summary,
                keywords,
                distillation_metadata=metadata,
            ):
                logger.info(
                    "蒸馏成功 [%s]: 梗概='%s...', 关键词=%s",
                    message["id"][:8],
                    summary[:30],
                    keywords[:3],
                )
                return True
            logger.warning("更新记忆失败 [%s]", message["id"][:8])
            return False
        except Exception as exc:
            logger.error("蒸馏单条记忆 %s 时出错: %s", message.get("id"), exc)
            return False
