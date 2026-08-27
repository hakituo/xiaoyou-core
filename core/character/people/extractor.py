"""夜间人物档案提取门面。

本类只保留增量总流程、共享 LLM 重试入口和旧私有方法兼容层；原始对话、
候选门控、外部人物持久化、角色演化分别由兄弟模块负责。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, ts_to_str

from .conversation_source import PeopleConversationSource
from .external_profile_service import ExternalPeopleProfileService
from .role_update_service import RoleProfileUpdateService
from .signal_gate import PeopleProfileSignalGate

logger = get_logger("PeopleProfileExtractor")


class PeopleProfileExtractor:
    """协调增量人物档案提取，保持历史调用接口兼容。"""

    async def extract_and_update(
        self,
        user_id: str,
        manager: Any = None,
        *,
        memory_managers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """按增量水位筛选候选批次并更新人物/角色档案。"""
        self._llm_call_count = 0
        state = self._load_state()
        last_ts = float(state.get("last_processed_timestamp", 0.0))
        messages = self._get_new_messages(last_ts)
        if not messages:
            logger.info("无新增消息，跳过人物档案提取")
            return {
                "extracted_count": 0,
                "updated_count": 0,
                "created_count": 0,
                "llm_batches": 0,
                "skipped": "no_new_messages",
            }

        last_run = (
            ts_to_str(last_ts, "%Y-%m-%d %H:%M:%S") if last_ts > 0 else "无"
        )
        logger.info("待提取消息: %d 条（上次处理时间: %s）", len(messages), last_run)
        all_batches = self._group_into_batches(messages)
        people_batches, role_batches = self._apply_signal_gate(
            all_batches,
            memory_managers,
            last_ts,
        )
        max_ts = max(
            (float(message.get("timestamp", 0) or 0) for message in messages),
            default=last_ts,
        )
        if not people_batches and not role_batches:
            self._advance_state(max_ts)
            logger.info("无人物或角色演化线索，跳过详细提取（LLM 0 次）")
            return {
                "extracted_count": 0,
                "updated_count": 0,
                "created_count": 0,
                "role_update_count": 0,
                "llm_batches": 0,
                "skipped": "no_profile_signals",
            }

        people_stats = await self._extract_external_people(people_batches)
        role_update_count = await self._extract_role_updates(
            messages,
            batches=role_batches,
        )
        self._advance_state(max_ts)
        logger.info(
            "人物档案提取完成: 提取 %d 人, 更新 %d 人, 新建 %d 人, 角色更新 %d 条",
            people_stats["extracted_count"],
            people_stats["updated_count"],
            people_stats["created_count"],
            role_update_count,
        )
        return {
            **people_stats,
            "role_update_count": role_update_count,
            "llm_batches": self._llm_call_count,
        }

    def _apply_signal_gate(
        self,
        all_batches: List[List[Dict[str, Any]]],
        memory_managers: Optional[Dict[str, Any]],
        last_ts: float,
    ) -> tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]:
        """手动模式全量放行；nightly 按蒸馏线索筛选。"""
        if memory_managers is None:
            logger.info("手动提取未启用蒸馏门控: %d 批", len(all_batches))
            return all_batches, all_batches
        gate = self._collect_distillation_gate(memory_managers, last_ts)
        people_batches = self._select_candidate_batches(
            all_batches,
            gate["people"],
            signal_type="people",
        )
        role_batches = self._select_candidate_batches(
            all_batches,
            gate["role_updates"],
            signal_type="role_updates",
        )
        logger.info(
            "蒸馏线索门控: 原始=%d 批, 人物=%d 批, 角色演化=%d 批, "
            "蒸馏已分析=%d 条",
            len(all_batches),
            len(people_batches),
            len(role_batches),
            gate["analyzed_count"],
        )
        return people_batches, role_batches

    async def _extract_external_people(
        self,
        batches: List[List[Dict[str, Any]]],
    ) -> Dict[str, int]:
        """把外部人物候选批次交给专用服务。"""
        if not batches:
            return {
                "extracted_count": 0,
                "updated_count": 0,
                "created_count": 0,
            }
        from .manager import get_people_profile_manager

        service = ExternalPeopleProfileService(
            self._call_llm_with_prompt,
            self._format_batch,
        )
        return await service.extract_batches(
            batches,
            get_people_profile_manager(),
        )

    def _advance_state(self, max_timestamp: float) -> None:
        """两类候选均完成后推进增量水位。"""
        self._save_state(
            {
                "last_processed_timestamp": max_timestamp,
                "last_run_time": get_current_time().strftime("%Y-%m-%d %H:%M:%S"),
                "profile_signal_gate_version": 1,
            }
        )

    async def _call_llm(self, content: str, existing_profiles: str = "（无）") -> str:
        """兼容入口：构建外部人物 Prompt 后调用共享重试器。"""
        return await self._call_llm_with_prompt(
            self._build_prompt(content, existing_profiles)
        )

    async def _call_llm_with_prompt(
        self,
        prompt: "str | List[Dict[str, str]]",
    ) -> str:
        """调用人物档案模型，并对空流或可重试异常最多重试两次。"""
        import asyncio

        from core.services.scheduler.task.task_scheduler import get_global_scheduler
        from memory.nightly.config import get_memory_distillation_model

        max_retries = 2
        last_exc: Exception | None = None
        last_upstream_error = ""
        for attempt in range(max_retries + 1):
            full_response = ""
            llm_kwargs: Dict[str, Any] = {
                "max_tokens": 2000,
                "temperature": 0.3,
            }
            distillation_model = get_memory_distillation_model()
            if distillation_model:
                llm_kwargs["model_hint"] = distillation_model
            scheduler = get_global_scheduler()
            try:
                self._llm_call_count = getattr(self, "_llm_call_count", 0) + 1
                async for chunk in scheduler.submit_llm_task(prompt, **llm_kwargs):
                    if isinstance(chunk, str):
                        full_response += chunk
                    elif isinstance(chunk, dict):
                        if chunk.get("non_retryable"):
                            body = chunk.get("details", {}).get("body", "")
                            logger.error(
                                "LLM 不可重试错误，跳过重试: %s",
                                body or chunk.get("error", ""),
                            )
                            return ""
                        if chunk.get("error"):
                            last_upstream_error = str(chunk.get("error", ""))
                        if chunk.get("content"):
                            full_response += chunk["content"]
                if full_response.strip():
                    return full_response
                if attempt < max_retries:
                    logger.warning(
                        "LLM 返回空（第 %d 次），重试... 上游错误: %s",
                        attempt + 1,
                        last_upstream_error or "无",
                    )
                    await asyncio.sleep(2)
            except Exception as exc:
                last_exc = exc
                logger.error("LLM 调用失败（第 %d 次）: %s", attempt + 1, exc, exc_info=True)
                if attempt < max_retries:
                    await asyncio.sleep(2)
        logger.error(
            "LLM 调用失败，已重试 %d 次，最后一次异常: %r，上游错误: %s",
            max_retries,
            last_exc,
            last_upstream_error or "无",
        )
        return ""

    # 以下兼容层保留既有测试/诊断调用，实际职责在兄弟模块。
    def _get_state_path(self) -> Path:
        return PeopleConversationSource.get_state_path()

    def _load_state(self) -> Dict[str, Any]:
        return PeopleConversationSource.load_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        PeopleConversationSource.save_state(state)

    def _get_new_messages(self, last_processed_ts: float) -> List[Dict[str, Any]]:
        return PeopleConversationSource.load_new_messages(last_processed_ts)

    def _load_chat_history(self, last_processed_ts: float) -> List[Dict[str, Any]]:
        return PeopleConversationSource.load_new_messages(last_processed_ts)

    _group_into_batches = staticmethod(PeopleConversationSource.group_into_batches)
    _format_batch = staticmethod(PeopleConversationSource.format_batch)
    _format_existing_profiles = staticmethod(
        ExternalPeopleProfileService.format_existing_profiles
    )
    _collect_distillation_gate = staticmethod(PeopleProfileSignalGate.collect)
    _select_candidate_batches = staticmethod(PeopleProfileSignalGate.select_batches)
    _detect_local_batch_signals = staticmethod(
        PeopleProfileSignalGate.detect_local_signals
    )
    _build_prompt = staticmethod(ExternalPeopleProfileService.build_prompt)
    _parse_response = staticmethod(ExternalPeopleProfileService.parse_response)
    _update_existing_profile = staticmethod(
        ExternalPeopleProfileService.update_existing_profile
    )
    _create_new_profile = staticmethod(
        ExternalPeopleProfileService.create_new_profile
    )

    async def _extract_role_updates(
        self,
        messages: List[Dict[str, Any]],
        *,
        batches: Optional[List[List[Dict[str, Any]]]] = None,
    ) -> int:
        service = RoleProfileUpdateService(
            self._call_llm_with_prompt,
            self._group_into_batches,
        )
        return await service.extract_updates(messages, batches=batches)

    _format_batch_with_role = staticmethod(
        RoleProfileUpdateService.format_batch_with_role
    )
    _build_role_update_prompt = staticmethod(RoleProfileUpdateService.build_prompt)
    _parse_role_update_response = staticmethod(RoleProfileUpdateService.parse_response)
    _recover_complete_role_updates = staticmethod(
        RoleProfileUpdateService.recover_complete_updates
    )
