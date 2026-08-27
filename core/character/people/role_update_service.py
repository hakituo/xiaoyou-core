"""Aveline/Ling 角色档案演化提取。"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.utils.json_utils import extract_json_object
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from .models import KnownFact, ProfileTarget

logger = get_logger("PeopleProfileExtractor")
LlmCaller = Callable[[List[Dict[str, str]]], Awaitable[str]]
BatchGrouper = Callable[[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]
_MIN_CONFIDENCE = 0.5


class RoleProfileUpdateService:
    """只处理 ROLE 档案事实，不处理外部人物。"""

    def __init__(self, llm_caller: LlmCaller, batch_grouper: BatchGrouper) -> None:
        self._llm_caller = llm_caller
        self._batch_grouper = batch_grouper

    async def extract_updates(
        self,
        messages: List[Dict[str, Any]],
        *,
        batches: Optional[List[List[Dict[str, Any]]]] = None,
    ) -> int:
        """从候选对话批次提取角色持久偏好与习惯。"""
        if not messages:
            return 0
        selected = batches if batches is not None else self._batch_grouper(messages)
        logger.info("角色更新提取: %d 批", len(selected))
        if not selected:
            return 0

        from .manager import get_people_profile_manager

        profile_manager = get_people_profile_manager()
        total_updates = 0
        for index, batch in enumerate(selected, start=1):
            try:
                content = self.format_batch_with_role(batch)
                if not content.strip():
                    continue
                response = await self._llm_caller(self.build_prompt(content))
                if not response:
                    logger.warning("角色更新批次 %d: LLM 返回空", index)
                    continue
                updates = self.parse_response(response)
                if not updates:
                    logger.info("角色更新批次 %d: 未提取到角色更新", index)
                    continue
                logger.info(
                    "角色更新批次 %d: 提取到 %d 个角色更新",
                    index,
                    len(updates),
                )
                total_updates += self._persist_updates(updates, profile_manager)
            except Exception as exc:
                logger.error("角色更新批次 %d 失败: %s", index, exc)
        if total_updates > 0:
            logger.info("角色更新提取完成: 共更新 %d 条事实", total_updates)
        return total_updates

    @staticmethod
    def _persist_updates(updates: List[Dict[str, Any]], profile_manager: Any) -> int:
        """规范化角色名并合并角色事实。"""
        total_updates = 0
        current_time = get_current_time().strftime("%Y-%m-%d %H:%M:%S")
        for update in updates:
            role_name_raw = str(update.get("role") or "").strip().lower()
            facts = update.get("facts") or []
            if not role_name_raw or not isinstance(facts, list):
                continue
            role_identity = RoleProfileUpdateService._resolve_role(role_name_raw)
            if role_identity is None:
                logger.warning("未知角色: %s，跳过", role_name_raw)
                continue
            scope, normalized_name = role_identity
            profile = profile_manager.get_role_profile(
                scope=scope,
                role_name=normalized_name,
                target=ProfileTarget.DEFAULT.value,
            )
            if profile is None:
                logger.warning(
                    "找不到角色档案: scope=%s, name=%s",
                    scope,
                    normalized_name,
                )
                continue
            batch_updates = 0
            for fact_data in facts:
                if not isinstance(fact_data, dict):
                    continue
                key = str(fact_data.get("key") or "").strip()
                value = str(fact_data.get("value") or "").strip()
                if not key or not value:
                    continue
                confidence = float(fact_data.get("confidence") or 0.5)
                if confidence < _MIN_CONFIDENCE:
                    continue
                profile.add_known_fact(
                    KnownFact(
                        key=key,
                        value=value,
                        confidence=confidence,
                        source="role_update_extracted",
                        updated_at=current_time,
                    )
                )
                batch_updates += 1
                total_updates += 1
            if batch_updates > 0:
                profile.touch_mention(current_time)
                profile_manager.save_profile(profile)
                logger.info(
                    "更新角色档案: %s (新增 %d 条事实)",
                    normalized_name,
                    batch_updates,
                )
        return total_updates

    @staticmethod
    def _resolve_role(role_name: str) -> Optional[tuple[str, str]]:
        """把模型角色名归一化到 scope 与默认档案名。"""
        if role_name in {"aveline", "澪", "七濑澪", "七濑", "澪姐"}:
            return "aveline", "Aveline"
        if role_name in {"ling", "玲", "Ling"}:
            return "ling", "Ling"
        return None

    @staticmethod
    def format_batch_with_role(batch: List[Dict[str, Any]]) -> str:
        """格式化批次，并按 _source_role 区分 Aveline/Ling。"""
        lines: List[str] = []
        for message in batch:
            role = str(message.get("role") or "").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                prefix = "[用户]"
            elif role in {"assistant", "aveline", "ling"}:
                source_role = str(
                    message.get("_source_role") or ""
                ).strip().lower()
                if source_role == "ling":
                    prefix = "[Ling]"
                elif source_role == "aveline":
                    prefix = "[Aveline]"
                else:
                    prefix = "[AI]"
            else:
                prefix = f"[{role}]"
            lines.append(f"{prefix} {content}")
        return "\n".join(lines)

    @staticmethod
    def build_prompt(content: str) -> List[Dict[str, str]]:
        """构建稳定 system + 动态 user 的角色演化 Prompt。"""
        from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
            ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT,
            ROLE_UPDATE_EXTRACTION_USER_TEMPLATE,
        )

        return [
            {"role": "system", "content": ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": ROLE_UPDATE_EXTRACTION_USER_TEMPLATE.format(
                    content=content
                ),
            },
        ]

    @classmethod
    def parse_response(cls, response: str) -> List[Dict[str, Any]]:
        """鲁棒解析角色演化 JSON，并恢复被截断的完整对象。"""
        if not response or not response.strip():
            return []
        text = response.strip()
        parsed = extract_json_object(text)
        if isinstance(parsed, dict):
            updates = parsed.get("role_updates")
            if isinstance(updates, list):
                return [item for item in updates if isinstance(item, dict)]

        json_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if json_match:
            text = json_match.group(1).strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                fixed = text.replace("'", '"')
                fixed = re.sub(r",\s*}", "}", fixed)
                fixed = re.sub(r",\s*]", "]", fixed)
                data = json.loads(fixed)
            except json.JSONDecodeError as exc:
                recovered = cls.recover_complete_updates(text)
                if recovered:
                    logger.warning(
                        "角色更新 JSON 不完整，已恢复 %d 个完整对象",
                        len(recovered),
                    )
                    return recovered
                logger.error(
                    "解析角色更新 JSON 失败: %s, 原始: %s",
                    exc,
                    response[:200],
                )
                return []
        if not isinstance(data, dict):
            return []
        updates = data.get("role_updates")
        if not isinstance(updates, list):
            return []
        return [item for item in updates if isinstance(item, dict)]

    @staticmethod
    def recover_complete_updates(text: str) -> List[Dict[str, Any]]:
        """从被截断的 role_updates 数组恢复已闭合对象。"""
        marker = re.search(r'"role_updates"\s*:\s*\[', text)
        if not marker:
            return []
        objects: List[Dict[str, Any]] = []
        start: Optional[int] = None
        depth = 0
        in_string = False
        escaped = False
        for index in range(marker.end(), len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if in_string:
                if char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        item = json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        item = None
                    if isinstance(item, dict):
                        objects.append(item)
                    start = None
        return objects
