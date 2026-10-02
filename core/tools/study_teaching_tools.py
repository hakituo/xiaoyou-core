"""教学闭环工具集（暴露给主 Agent 的高层语义接口）。

设计原则
--------
- **只暴露高层语义接口**，不把 ``record_topic`` / ``record_weakness`` /
  ``mark_mastered`` 这类低层函数直接丢给 LLM，避免模型自己拼调用顺序、
  写坏学习状态。
- 评价由 LLM 给出结构化 JSON，**状态更新由后端完成**；
  载荷不可信时直接放弃更新，绝不让解析失败变成「用户答错」。
- 与 ``TutorEngine``（规则/统计/计划层）分工：本模块负责教学情境与闭环。

工具清单
--------
- ``study_get_context``      读取持久化学习状态 + ZPD + 建议动作 + 到期复习（可选计划）
- ``study_record_teaching``  记录讲解 / 举例 / 提示（只推进到 learning）
- ``study_record_answer``    记录并评价用户作答（闭环核心）
- ``study_record_confusion`` 记录用户没听懂（进入薄弱与复习调度）
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _orchestrator():
    from core.services.study.teaching_orchestrator import get_teaching_orchestrator

    return get_teaching_orchestrator()


# ----------------------------------------------------------------------
# 读取：学习状态
# ----------------------------------------------------------------------


class StudyGetContextInput(BaseModel):
    message: Optional[str] = Field(
        default=None,
        description="用户当前这句话（可选）。传入后会顺带识别意图、知识点与最近发展区。",
    )
    subject: Optional[str] = Field(
        default=None,
        description="限定科目，如 math / physics / chemistry / biology。不传则自动识别。",
    )
    include_plan: bool = Field(
        default=False, description="是否同时返回今日学习计划。"
    )


class StudyGetContextTool(BaseTool):
    name = "study_get_context"
    description = (
        "读取用户的持久化学习状态：已掌握/正在学/薄弱的知识点、最近发展区、"
        "到期复习项与建议教学动作。开始教学或复习前应先调用，避免重复讲已掌握的内容。"
    )
    short_description = "读取学习状态（已掌握/薄弱/到期复习/建议动作）"
    args_schema = StudyGetContextInput
    category = "study"
    enabled_by_default = True

    async def _run(
        self,
        message: Optional[str] = None,
        subject: Optional[str] = None,
        include_plan: bool = False,
    ) -> str:
        def _sync() -> str:
            orch = _orchestrator()
            ctx = orch.get_context(message, subject)
            if include_plan:
                ctx["plan"] = orch.get_plan()
            return _dumps({"status": "success", "data": ctx})

        return await asyncio.to_thread(_sync)


# ----------------------------------------------------------------------
# 写入：教学接触
# ----------------------------------------------------------------------


class StudyRecordTeachingInput(BaseModel):
    subject: str = Field(description="科目，如 physics / math / chemistry / biology")
    concept: str = Field(description="本次讲解的知识点名称，如 简谐运动 / 导数")
    action: str = Field(
        default="taught",
        description="教学动作：taught(讲解) / explained(换角度解释) / hint(给提示)",
    )
    prerequisites: Optional[list[str]] = Field(
        default=None, description="该知识点的前置知识名称（可选，用于跨度判断）"
    )


class StudyRecordTeachingTool(BaseTool):
    name = "study_record_teaching"
    description = (
        "记录一次教学接触（你讲解了某个知识点）。只会把知识点标记为「正在学」，"
        "不会判定为已掌握——掌握必须由用户独立答对来证明。"
        "concept 请写简短稳定的知识点名，后续调用要复用同一个名字。"
    )
    short_description = "记录讲解/举例/提示"
    args_schema = StudyRecordTeachingInput
    category = "study"
    enabled_by_default = True

    async def _run(
        self,
        subject: str,
        concept: str,
        action: str = "taught",
        prerequisites: Optional[list] = None,
    ) -> str:
        def _sync() -> str:
            return _dumps(
                _orchestrator().record_teaching(
                    subject,
                    concept,
                    action=action,
                    source="tool",
                    prerequisites=prerequisites,
                )
            )

        return await asyncio.to_thread(_sync)


# ----------------------------------------------------------------------
# 写入：作答评价（闭环核心）
# ----------------------------------------------------------------------


class StudyRecordAnswerInput(BaseModel):
    subject: str = Field(description="科目，如 physics / math")
    concept: str = Field(description="本次作答对应的知识点名称")
    correctness: float = Field(
        description="答对程度 0.0-1.0。0.8 以上算答对，0.5-0.8 算部分正确，0.5 以下算答错。"
    )
    independent: bool = Field(
        default=True, description="用户是否独立作答（没看答案、没要提示）"
    )
    used_hint: bool = Field(default=False, description="本次是否给了提示")
    misconception: Optional[str] = Field(
        default=None, description="暴露出的具体误区（可选），如「把负号当成方向错误」"
    )
    confidence_delta: float = Field(
        default=0.0, description="用户自信度变化 -0.3~0.3（可选）"
    )
    user_answer: Optional[str] = Field(
        default=None, description="用户答案的简短摘要（可选）"
    )
    is_review: bool = Field(
        default=False, description="本次是否属于间隔复习（而非新学后的即时检验）"
    )


class StudyRecordAnswerTool(BaseTool):
    name = "study_record_answer"
    description = (
        "评价并记录用户对某个知识点的作答。调用前必须先让用户独立回答；"
        "用了提示就把 used_hint 设为 true。系统会据此更新掌握度、薄弱项与复习计划。"
        "concept 必须与本轮 study_get_context 或 study_record_teaching 用过的名称"
        "完全一致，不要另起别名或加限定词（写成不同名字会拆成两个知识点，学习记录会散开）。"
    )
    short_description = "评价并记录用户作答（更新掌握度）"
    args_schema = StudyRecordAnswerInput
    category = "study"
    enabled_by_default = True

    async def _run(
        self,
        subject: str,
        concept: str,
        correctness: float,
        independent: bool = True,
        used_hint: bool = False,
        misconception: Optional[str] = None,
        confidence_delta: float = 0.0,
        user_answer: Optional[str] = None,
        is_review: bool = False,
    ) -> str:
        def _sync() -> str:
            return _dumps(
                _orchestrator().record_answer(
                    subject,
                    concept,
                    {
                        "correctness": correctness,
                        "independent": independent,
                        "used_hint": used_hint,
                        "misconception": misconception,
                        "confidence_delta": confidence_delta,
                    },
                    user_answer=user_answer or "",
                    source="review" if is_review else "tool",
                    is_review=is_review,
                )
            )

        return await asyncio.to_thread(_sync)


# ----------------------------------------------------------------------
# 写入：自述没听懂
# ----------------------------------------------------------------------


class StudyRecordConfusionInput(BaseModel):
    subject: str = Field(description="科目，如 math / physics")
    concept: str = Field(description="用户没听懂的知识点名称")
    description: Optional[str] = Field(
        default=None, description="用户卡住的具体描述（可选）"
    )


class StudyRecordConfusionTool(BaseTool):
    name = "study_record_confusion"
    description = (
        "记录用户在某个知识点上没听懂。系统会把它加入薄弱项并按间隔复习安排，"
        "后续对话会优先补这个缺口。"
        "concept 请复用 study_get_context 返回的知识点名，不要另起别名。"
    )
    short_description = "记录用户没听懂的知识点"
    args_schema = StudyRecordConfusionInput
    category = "study"
    enabled_by_default = True

    async def _run(
        self, subject: str, concept: str, description: Optional[str] = None
    ) -> str:
        def _sync() -> str:
            return _dumps(
                _orchestrator().record_confusion(
                    subject, concept, description=description or "", source="tool"
                )
            )

        return await asyncio.to_thread(_sync)


# ----------------------------------------------------------------------
# 注册入口
# ----------------------------------------------------------------------

TEACHING_TOOL_CLASSES = (
    StudyGetContextTool,
    StudyRecordTeachingTool,
    StudyRecordAnswerTool,
    StudyRecordConfusionTool,
)


def register_teaching_tools(registry: Any) -> Dict[str, Any]:
    """把教学闭环工具注册到工具注册表。"""
    registered = []
    for cls in TEACHING_TOOL_CLASSES:
        registry.register(cls())
        registered.append(cls.name)
    return {"registered": registered}
