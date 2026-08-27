"""Nightly 蒸馏的 Prompt、响应解析与零 API 信号规则。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")


class DistillationCodec:
    """蒸馏服务使用的无状态文本转换能力。"""

    @staticmethod
    def group_memories_by_time(
        messages: List[Dict[str, Any]],
        gap_seconds: float,
        max_group_size: int,
    ) -> List[List[Dict[str, Any]]]:
        """按时间连续性分组，组内超限时切分。"""
        ordered = sorted(
            messages,
            key=lambda item: float(item.get("timestamp", 0) or 0),
        )
        groups: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        previous_ts: float | None = None
        for message in ordered:
            timestamp = float(message.get("timestamp", 0) or 0)
            if previous_ts is not None and (
                timestamp - previous_ts > gap_seconds
                or len(current) >= max_group_size
            ):
                if current:
                    groups.append(current)
                current = []
            current.append(message)
            previous_ts = timestamp
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def generate_distillation_prompt(content: str) -> List[Dict[str, str]]:
        """生成稳定 system + 动态 user 的单条蒸馏 Prompt。"""
        from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
            MEMORY_DISTILLATION_SYSTEM_PROMPT,
            MEMORY_DISTILLATION_USER_TEMPLATE,
        )

        return [
            {"role": "system", "content": MEMORY_DISTILLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": MEMORY_DISTILLATION_USER_TEMPLATE.format(content=content),
            },
        ]

    @staticmethod
    def generate_batch_distillation_prompt(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """生成稳定 system + 编号动态条目的批量蒸馏 Prompt。"""
        from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
            MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT,
            MEMORY_DISTILLATION_BATCH_USER_TEMPLATE,
        )

        items = "\n\n".join(
            f"【条目{index}】\n"
            f"【说话者】{str(message.get('role', '') or 'unknown')}\n"
            f"{str(message.get('content', '') or '').strip()}"
            for index, message in enumerate(messages, start=1)
        )
        return [
            {"role": "system", "content": MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": MEMORY_DISTILLATION_BATCH_USER_TEMPLATE.format(
                    count=len(messages),
                    items=items,
                ),
            },
        ]

    @classmethod
    def parse_batch_distillation_response(
        cls,
        response: str,
    ) -> Dict[int, Tuple[str, List[str]]]:
        """解析批量蒸馏响应。"""
        results: Dict[int, Tuple[str, List[str]]] = {}
        if not response:
            return results
        pattern = re.compile(r"【条目(\d+)】")
        matches = list(pattern.finditer(response))
        if not matches:
            logger.warning(
                "批量蒸馏响应未匹配到任何【条目N】，原始响应: %s",
                response[:200],
            )
            return results
        for position, match in enumerate(matches):
            try:
                index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            start = match.end()
            end = (
                matches[position + 1].start()
                if position + 1 < len(matches)
                else len(response)
            )
            segment = response[start:end].strip()
            summary, keywords = cls.parse_distillation_response(segment)
            if summary:
                results[index] = (summary, keywords)
            else:
                logger.warning(
                    "批量蒸馏条目 %d 解析为空，跳过（segment='%s'）",
                    index,
                    segment[:100],
                )
        return results

    @staticmethod
    def empty_profile_signals(*, analyzed: bool) -> Dict[str, Any]:
        """构造蒸馏阶段的人物门控元数据。"""
        return {
            "profile_signal_version": 1,
            "profile_signal_analyzed": analyzed,
            "people_mentions": [],
            "role_update_candidates": [],
        }

    @staticmethod
    def _parse_profile_signal_values(raw_value: str) -> List[str]:
        """解析线索值，过滤空标记。"""
        empty_values = {"无", "none", "null", "nil", "没有", "无人物", "无更新"}
        values: List[str] = []
        for item in re.split(r"[,，、;/；|]", str(raw_value or "")):
            value = item.strip().strip("[]【】")
            if not value or value.lower() in empty_values:
                continue
            if value not in values:
                values.append(value)
        return values

    @classmethod
    def parse_profile_signals(cls, response: str) -> Dict[str, Any]:
        """从单条蒸馏响应中解析人物与角色演化线索。"""
        metadata = cls.empty_profile_signals(analyzed=False)
        if not response:
            return metadata
        people_match = re.search(
            r"【人物线索】\s*[：:]\s*(.*?)(?=\n|【|$)",
            response,
            re.S,
        )
        role_match = re.search(
            r"【角色演化】\s*[：:]\s*(.*?)(?=\n|【|$)",
            response,
            re.S,
        )
        metadata["profile_signal_analyzed"] = bool(people_match and role_match)
        if people_match:
            metadata["people_mentions"] = cls._parse_profile_signal_values(
                people_match.group(1)
            )
        if role_match:
            metadata["role_update_candidates"] = cls._parse_profile_signal_values(
                role_match.group(1)
            )
        return metadata

    @classmethod
    def parse_batch_profile_signals(
        cls,
        response: str,
    ) -> Dict[int, Dict[str, Any]]:
        """按条目号解析批量蒸馏中的人物门控线索。"""
        parsed: Dict[int, Dict[str, Any]] = {}
        pattern = re.compile(r"【条目(\d+)】")
        matches = list(pattern.finditer(response or ""))
        for position, match in enumerate(matches):
            try:
                index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            start = match.end()
            end = (
                matches[position + 1].start()
                if position + 1 < len(matches)
                else len(response)
            )
            parsed[index] = cls.parse_profile_signals(response[start:end].strip())
        return parsed

    @classmethod
    def detect_profile_signals_locally(
        cls,
        content: str,
        *,
        role: str = "",
    ) -> Dict[str, Any]:
        """短文本不调 LLM，用保守规则补齐人物门控元数据。"""
        metadata = cls.empty_profile_signals(analyzed=True)
        text = str(content or "").strip()
        if not text:
            return metadata
        person_pattern = re.compile(
            r"(?:我的|他的|她的|家里的|班上的)?"
            r"(?:妈妈|爸爸|父亲|母亲|哥哥|弟弟|姐姐|妹妹|"
            r"老师|同学|朋友|同事|亲戚|室友|班主任|教授|医生|"
            r"师傅|老板|邻居|叔叔|阿姨|爷爷|奶奶|"
            r"外公|外婆|男朋友|女朋友)"
            r"|(?:叫|名叫|姓)\s*[\u4e00-\u9fff]{1,4}"
        )
        if person_pattern.search(text):
            metadata["people_mentions"] = ["local_candidate"]
        normalized_role = str(role or "").strip().lower()
        if normalized_role in {"assistant", "aveline", "ling"} and re.search(
            r"(?:我|本人).{0,6}(?:喜欢|讨厌|不喜欢|习惯|偏好|"
            r"以后都|从不|总是|害怕|擅长|想要)",
            text,
        ):
            metadata["role_update_candidates"] = [normalized_role]
        return metadata

    @staticmethod
    def parse_distillation_response(response: str) -> Tuple[str, List[str]]:
        """解析 LLM 返回的梗概与关键词。"""
        summary = ""
        keywords: List[str] = []
        try:
            summary_match = re.search(
                r"【梗概】[：:](.*?)(?=\n|【|$)",
                response,
                re.S,
            )
            if summary_match:
                summary = summary_match.group(1).strip()
            keywords_match = re.search(
                r"【关键词】[：:](.*?)(?=\n|【|$)",
                response,
                re.S,
            )
            if keywords_match:
                keywords = [
                    keyword.strip()
                    for keyword in re.split(
                        r"[,，、\s]+",
                        keywords_match.group(1).strip(),
                    )
                    if keyword.strip()
                ]
        except Exception as exc:
            logger.error("解析蒸馏响应出错: %s, 原始响应: %s", exc, response)
        return summary, keywords
