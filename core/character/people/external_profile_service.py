"""外部人物档案的候选批次详细提取与持久化。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Awaitable, Callable, Dict, List

from core.utils.json_utils import looks_like_refusal, unwrap_redundant_brackets
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from .models import KnownFact, PersonProfile, ProfileType

logger = get_logger("PeopleProfileExtractor")
LlmCaller = Callable[[List[Dict[str, str]]], Awaitable[str]]
BatchFormatter = Callable[[List[Dict[str, Any]]], str]
_MIN_CONFIDENCE = 0.5


class ExternalPeopleProfileService:
    """只处理外部 PERSON 档案，不负责门控或角色档案。

    硬约束：**AI 角色永远不进人际关系档案**。Prompt 里虽然写了"不应该提取 AI 角色自己"
    （与历史人物、虚构人物同一档规则），但那只靠模型自觉——历史上没拦住，people_profiles/
    里至今躺着 aveline.json / ling.json。所以这里再兜一道代码级过滤：
    命中已注册角色的名字/别名一律丢弃。历史人物那类无法穷举的仍交给 Prompt 软规则。
    """

    @staticmethod
    def _matched_ai_role_id(name: str, aliases: Any = None) -> str:
        """名字或任一别名指向已注册 AI 角色时返回其 role_id，否则空串。"""
        try:
            from core.services.dual_role.personas import resolve_ai_role_id

            if resolve_ai_role_id(name):
                return resolve_ai_role_id(name)
            for alias in aliases or ():
                role_id = resolve_ai_role_id(alias)
                if role_id:
                    return role_id
        except Exception:
            return ""
        return ""

    @staticmethod
    def _is_ai_role_profile(profile: Any) -> bool:
        """已有档案是不是"AI 角色的档案"（用于从候选列表里剔除）。"""
        try:
            from core.services.dual_role.personas import role_id_of_people_profile

            return bool(
                role_id_of_people_profile(
                    getattr(profile, "profile_id", ""),
                    [getattr(profile, "name", ""), *(getattr(profile, "aliases", None) or ())],
                )
            )
        except Exception:
            return False

    def __init__(
        self,
        llm_caller: LlmCaller,
        batch_formatter: BatchFormatter,
    ) -> None:
        self._llm_caller = llm_caller
        self._batch_formatter = batch_formatter

    async def extract_batches(
        self,
        batches: List[List[Dict[str, Any]]],
        profile_manager: Any,
    ) -> Dict[str, int]:
        """逐批提取外部人物并更新/创建档案。"""
        extracted = 0
        updated = 0
        created = 0
        for index, batch in enumerate(batches, start=1):
            try:
                content = self._batch_formatter(batch)
                if not content.strip():
                    continue
                # 已有档案列表里剔除 AI 角色条目：否则模型会把"Aveline" match_existing 到
                # aveline.json 上，等于继续往那条不该存在的档案里写事实。
                existing = [
                    p
                    for p in profile_manager.list_all_people_profiles()
                    if not self._is_ai_role_profile(p)
                ]
                existing_text = self.format_existing_profiles(existing)
                response = await self._llm_caller(
                    self.build_prompt(content, existing_text)
                )
                if not response:
                    logger.warning("批次 %d: LLM 返回空", index)
                    continue
                people_data = self.parse_response(response)
                if not people_data:
                    logger.info("批次 %d: 未提取到人物", index)
                    continue
                logger.info("批次 %d: 提取到 %d 个人物", index, len(people_data))
                batch_stats = self._persist_people(people_data, profile_manager)
                extracted += batch_stats["extracted_count"]
                updated += batch_stats["updated_count"]
                created += batch_stats["created_count"]
            except Exception as exc:
                logger.error("批次 %d 处理失败: %s", index, exc)
        return {
            "extracted_count": extracted,
            "updated_count": updated,
            "created_count": created,
        }

    def _persist_people(
        self,
        people_data: List[Dict[str, Any]],
        profile_manager: Any,
    ) -> Dict[str, int]:
        """校验置信度并持久化一个批次的人物对象。"""
        extracted = 0
        updated = 0
        created = 0
        for person_info in people_data:
            confidence = float(person_info.get("confidence", 0.5) or 0.5)
            if confidence < _MIN_CONFIDENCE:
                logger.info(
                    "跳过低置信度人物: %s (confidence=%.2f)",
                    person_info.get("name", "?"),
                    confidence,
                )
                continue
            name = str(person_info.get("name") or "").strip()
            if not name:
                continue
            # 硬过滤：AI 角色（Aveline / Ling / Ye / Coco…）不是"用户的人际关系人物"，
            # 既不能新建档案，也不能被拿去更新那条历史遗留的角色档案。
            ai_role_id = self._matched_ai_role_id(
                name, person_info.get("aliases") or []
            )
            if ai_role_id:
                logger.info(
                    "跳过 AI 角色，不写入人际关系档案: %s (role_id=%s)",
                    name,
                    ai_role_id,
                )
                continue
            extracted += 1
            try:
                existing_profile = self._find_existing_profile(
                    person_info,
                    name,
                    profile_manager,
                )
                if existing_profile is not None:
                    self.update_existing_profile(
                        existing_profile,
                        person_info,
                        profile_manager,
                        confidence,
                    )
                    updated += 1
                else:
                    self.create_new_profile(
                        name,
                        person_info,
                        profile_manager,
                        confidence,
                    )
                    created += 1
            except Exception as exc:
                logger.error("更新人物档案失败 [%s]: %s", name, exc)
        return {
            "extracted_count": extracted,
            "updated_count": updated,
            "created_count": created,
        }

    @staticmethod
    def _find_existing_profile(
        person_info: Dict[str, Any],
        name: str,
        profile_manager: Any,
    ) -> Any:
        """优先按模型判定的已有名字匹配，再按名字/别名匹配。"""
        match_existing = str(person_info.get("match_existing") or "").strip()
        if match_existing:
            profile = profile_manager.query_profile_details(match_existing)
            if profile is not None:
                return profile
            logger.warning(
                "match_existing 指向的档案不存在: %s，改为创建新档案",
                match_existing,
            )
        return profile_manager.query_profile_details(name)

    @staticmethod
    def format_existing_profiles(profiles: List[Any]) -> str:
        """格式化已有档案列表，供模型去重。"""
        if not profiles:
            return "（无）"
        lines: List[str] = []
        for index, profile in enumerate(profiles, 1):
            aliases = ", ".join(profile.aliases) if profile.aliases else "无"
            role = profile.core_fields.get("role", "未知")
            lines.append(
                f"{index}. 名字: {profile.name}, 别名: [{aliases}], 角色: {role}"
            )
        return "\n".join(lines)

    @staticmethod
    def build_prompt(
        content: str,
        existing_profiles: str = "（无）",
    ) -> List[Dict[str, str]]:
        """构建稳定 system + 动态 user 的人物提取 Prompt。"""
        from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
            PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT,
            PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE,
        )

        return [
            {"role": "system", "content": PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE.format(
                    content=content,
                    existing_profiles=existing_profiles,
                ),
            },
        ]

    @staticmethod
    def parse_response(response: str) -> List[Dict[str, Any]]:
        """鲁棒解析人物提取 JSON。"""
        if not response or not response.strip():
            return []
        text = response.strip()
        if looks_like_refusal(text):
            logger.warning("LLM 拒答（非 JSON 回复），跳过本批: %s", text[:200])
            return []
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
                # 模型照抄 prompt 示例时会输出 {{...}}，剥掉双写的一层再试
                text = unwrap_redundant_brackets(text)
                data = json.loads(text)
            except json.JSONDecodeError:
                try:
                    fixed = text.replace("'", '"')
                    fixed = re.sub(r",\s*}", "}", fixed)
                    fixed = re.sub(r",\s*]", "]", fixed)
                    data = json.loads(fixed)
                except json.JSONDecodeError as exc:
                    logger.error(
                        "解析 LLM 返回的 JSON 失败: %s, 原始: %s",
                        exc,
                        response[:200],
                    )
                    return []
        if not isinstance(data, dict):
            return []
        people = data.get("people")
        if not isinstance(people, list):
            return []
        return [item for item in people if isinstance(item, dict)]

    @staticmethod
    def update_existing_profile(
        profile: PersonProfile,
        person_info: Dict[str, Any],
        profile_manager: Any,
        confidence: float,
    ) -> None:
        """合并已有人物档案。"""
        current_time = get_current_time().strftime("%Y-%m-%d %H:%M:%S")
        new_aliases = person_info.get("aliases") or []
        if isinstance(new_aliases, list):
            for alias_value in new_aliases:
                alias = str(alias_value).strip()
                if alias and alias not in profile.aliases:
                    profile.aliases.append(alias)
        role = person_info.get("role")
        if role and isinstance(role, str) and "role" not in profile.core_fields:
            profile.core_fields["role"] = role.strip()
        description = person_info.get("description")
        if description and isinstance(description, str) and not profile.description:
            profile.description = description.strip()
        ExternalPeopleProfileService._append_facts(
            profile,
            person_info.get("facts") or [],
            confidence,
            current_time,
        )
        profile.touch_mention(current_time)
        profile_manager.save_profile(profile)
        logger.info("更新人物档案: %s", profile.name)

    @staticmethod
    def create_new_profile(
        name: str,
        person_info: Dict[str, Any],
        profile_manager: Any,
        confidence: float,
    ) -> None:
        """创建新的人物档案。"""
        current_time = get_current_time().strftime("%Y-%m-%d %H:%M:%S")
        person_id = hashlib.md5(name.encode("utf-8")).hexdigest()[:12]
        aliases = [
            str(alias).strip()
            for alias in (person_info.get("aliases") or [])
            if isinstance(alias, str) and alias.strip()
        ]
        role = person_info.get("role")
        description = person_info.get("description")
        core_fields = {}
        if role and isinstance(role, str):
            core_fields["role"] = role.strip()
        source = (
            "nightly_extracted"
            if confidence >= 0.7
            else "low_confidence_extracted"
        )
        profile = PersonProfile(
            profile_id=person_id,
            profile_type=ProfileType.PERSON,
            name=name,
            aliases=aliases,
            core_fields=core_fields,
            description=(
                description.strip()
                if description and isinstance(description, str)
                else ""
            ),
            source=source,
            first_mentioned=current_time,
            last_mentioned=current_time,
            mention_count=1,
            updated_at=current_time,
        )
        ExternalPeopleProfileService._append_facts(
            profile,
            person_info.get("facts") or [],
            confidence,
            current_time,
        )
        profile_manager.save_profile(profile)
        logger.info(
            "创建新人物档案: %s (id=%s, confidence=%.2f)",
            name,
            person_id,
            confidence,
        )

    @staticmethod
    def _append_facts(
        profile: PersonProfile,
        facts: Any,
        confidence: float,
        current_time: str,
    ) -> None:
        """把结构化事实合并到档案。"""
        if not isinstance(facts, list):
            return
        for fact_data in facts:
            if not isinstance(fact_data, dict):
                continue
            key = str(fact_data.get("key") or "").strip()
            value = str(fact_data.get("value") or "").strip()
            if not key or not value:
                continue
            profile.add_known_fact(
                KnownFact(
                    key=key,
                    value=value,
                    confidence=confidence,
                    source="nightly_extracted",
                    updated_at=current_time,
                )
            )
