"""
核心记忆写入工具 — 让 LLM 自主写入 MEMORY.md 各分区

工具列表：
- RecordPreferenceTool     — 记录用户偏好 → MEMORY.md 偏好区
- RecordExperienceTool     — 记录业务经验 → MEMORY.md 业务经验区
- RecordActiveTaskTool     — 记录活跃任务 → MEMORY.md 活跃任务区
- CompleteActiveTaskTool   — 完成任务（从活跃任务区移除）
- RecordSummaryTool        — 记录对话摘要 → MEMORY.md 摘要区

设计说明：
- 按 scope 隔离写入（aveline/ling/user），scope 优先从 conversation_id 解析
  （稳定，不依赖全局 persona_manager 状态），失败时回退到 persona_manager
- 用户级偏好（住址/通用回复风格）写到 user_data/MEMORY.md，所有角色共享
- 角色特定偏好（active care 表情/特定称呼）写到对应角色文件
- 所有写入经 SelfImprovementService 入口，触发 auto_slim 与日志记录
- 符合 prompt 中"以下情况自动记录学习"的设计意图
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("RecordMemoryTool")


# ── 辅助函数 ─────────────────────────────────────────────


def _resolve_scope_from_context(tool: BaseTool, default: str = "aveline") -> str:
    """从工具运行时上下文的 conversation_id 推导 scope。

    优先级：
    1. runtime_context 中的 conversation_id（最稳定，多会话并发安全）
    2. persona_manager 当前 persona（fallback，存在并发覆盖风险）
    3. default

    conversation_id 形如 `private_xxx__persona__aveline_qq_master`，
    其中 `__persona__` 后的 token 直接指示了角色。
    """
    # 优先用 conversation_id（runtime context 注入）
    cid = ""
    try:
        cid = str(tool._get_ctx("user_id") or "")  # noqa: SLF001
    except Exception:
        cid = ""

    if cid:
        try:
            from core.utils.conversation_labels import get_conversation_label_info
            info = get_conversation_label_info(cid)
            scope = info.get("storage_scope")
            if scope in {"aveline", "ling", "user", "dual_role"}:
                # dual_role 不算独立记忆区，回退到具体角色
                if scope == "dual_role":
                    # peer_chat 场景：根据 persona token 决定主角色
                    persona_token = cid.lower().split("__persona__", 1)[1].split("__", 1)[0] if "__persona__" in cid.lower() else ""
                    if "ling" in persona_token:
                        return "ling"
                    return "aveline"
                return scope
        except Exception as e:
            logger.debug("从 conversation_id 解析 scope 失败，回退 persona_manager: %s", e)

    # 回退：persona_manager（有并发风险，但聊胜于无）
    try:
        from core.utils.data_paths import _resolve_scope_from_active_persona
        return _resolve_scope_from_active_persona()
    except Exception:
        pass
    return default


# ── 工具 1：记录用户偏好 ─────────────────────────────────


class RecordPreferenceInput(BaseModel):
    preference: str = Field(
        description=(
            "用户偏好的简洁描述，例如「回复时不要用 emoji」"
            "「偏好简洁」「不喜欢官方腔调」。"
        )
    )
    scope: str = Field(
        default="role",
        description=(
            "偏好归属层级，决定写到哪个 MEMORY.md："
            "user=用户级（所有角色共享，如住址/通用回复风格/通用饮食禁忌）；"
            "role=角色级（仅当前角色适用，如 active care 表情/特定称呼/特定剧情偏好）。"
            "默认 role。拿不准时默认 role，因为角色级偏好写错地方只影响一个角色，"
            "用户级偏好写错会污染所有角色。"
        ),
    )


class RecordPreferenceTool(BaseTool):
    name = "record_preference"
    description = (
        "记录一条用户偏好到核心记忆（MEMORY.md 用户偏好区，永久保留）。"
        "在用户明确表达喜好/厌恶/习惯，或反复展示某种行为倾向时调用。"
        "只记录稳定、长期适用的偏好，不要记录一次性临时需求。"
        "scope=user 写到用户级（所有角色共享）；scope=role 写到当前角色级。"
    )
    short_description = "记录用户偏好到核心记忆"
    category = "memory"
    args_schema = RecordPreferenceInput

    async def _run(self, preference: str, scope: str = "role") -> str:
        preference = (preference or "").strip()
        if not preference:
            return "失败：preference 不能为空"

        scope = (scope or "role").strip().lower()
        if scope not in {"user", "role"}:
            return f"失败：scope 必须是 'user' 或 'role'，收到 {scope!r}"

        try:
            from core.services.self_improvement.service import get_self_improvement_service
            # 实际写入的 storage scope
            if scope == "user":
                storage_scope = "user"
            else:
                storage_scope = _resolve_scope_from_context(self)

            si = get_self_improvement_service(scope=storage_scope)
            ok = await si.add_preference(preference)
            if ok:
                return f"已记录用户偏好（layer={scope}, scope={storage_scope}）: {preference}"
            return f"该偏好已存在或语义重复，未重复记录（layer={scope}, scope={storage_scope}）"
        except Exception as e:
            logger.warning("record_preference 失败: %s", e, exc_info=True)
            return f"记录偏好失败: {e}"


# ── 工具 2：记录业务经验 ─────────────────────────────────


class RecordExperienceInput(BaseModel):
    experience: str = Field(
        description=(
            "业务经验/最佳实践的简洁描述，例如「状态信息应通过工具调用获取，"
            "不要直接注入 prompt」。"
        )
    )
    category: Optional[str] = Field(
        default="best_practice",
        description=(
            "经验分类标签，建议值：best_practice / insight / knowledge_gap。"
            "默认 best_practice。"
        ),
    )
    tags: Optional[str] = Field(
        default=None,
        description="可选，附加标签，用逗号分隔，例如：memory, prompt",
    )


class RecordExperienceTool(BaseTool):
    name = "record_experience"
    description = (
        "记录一条业务经验到核心记忆（MEMORY.md 业务经验区，≤15条）。"
        "在以下情况调用：发现可复用的最佳实践、归纳出有用的洞察、"
        "发现自己之前的知识有误。重复出现的经验会触发自动晋升。"
    )
    short_description = "记录业务经验到核心记忆"
    category = "memory"
    args_schema = RecordExperienceInput

    async def _run(
        self,
        experience: str,
        category: Optional[str] = "best_practice",
        tags: Optional[str] = None,
    ) -> str:
        experience = (experience or "").strip()
        if not experience:
            return "失败：experience 不能为空"

        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        tag_list = tag_list or None

        # category 前缀作为 tag 注入，便于检索
        cat = (category or "best_practice").strip() or "best_practice"
        if cat not in tag_list:
            tag_list = (tag_list or []) + [cat]

        try:
            from core.services.self_improvement.service import get_self_improvement_service
            scope = _resolve_scope_from_context(self)
            si = get_self_improvement_service(scope=scope)
            ok = await si.add_experience(experience, tags=tag_list)
            if ok:
                return f"已记录业务经验（scope={scope}）: {experience}"
            return f"该经验已存在，未重复记录（scope={scope}）"
        except Exception as e:
            logger.warning("record_experience 失败: %s", e, exc_info=True)
            return f"记录经验失败: {e}"


# ── 工具 3：记录活跃任务 ─────────────────────────────────


class RecordActiveTaskInput(BaseModel):
    task: str = Field(
        description=(
            "活跃任务的简洁描述，例如「为日记系统接入情感分析」"
            "「重构 memory_manager」。"
        )
    )


class RecordActiveTaskTool(BaseTool):
    name = "record_active_task"
    description = (
        "记录一条活跃任务到核心记忆（MEMORY.md 活跃任务区）。"
        "用于跟踪进行中的任务，完成后应调用 complete_active_task 移除。"
        "只在任务被搁置/等待/正在进行时记录，不要记录已完成或一次性任务。"
    )
    short_description = "记录活跃任务到核心记忆"
    category = "memory"
    args_schema = RecordActiveTaskInput

    async def _run(self, task: str) -> str:
        task = (task or "").strip()
        if not task:
            return "失败：task 不能为空"

        try:
            from core.services.self_improvement.service import get_self_improvement_service
            scope = _resolve_scope_from_context(self)
            si = get_self_improvement_service(scope=scope)
            ok = await si.add_active_task(task)
            if ok:
                return f"已记录活跃任务（scope={scope}）: {task}"
            return f"该任务已存在，未重复记录（scope={scope}）"
        except Exception as e:
            logger.warning("record_active_task 失败: %s", e, exc_info=True)
            return f"记录任务失败: {e}"


# ── 工具 4：完成活跃任务 ─────────────────────────────────


class CompleteActiveTaskInput(BaseModel):
    task: str = Field(
        description="要标记为完成的任务描述，需与记录时一致或近似。",
    )


class CompleteActiveTaskTool(BaseTool):
    name = "complete_active_task"
    description = (
        "标记活跃任务为已完成，从核心记忆活跃任务区移除。"
        "任务完成后调用以保持记忆干净。"
    )
    short_description = "标记活跃任务为已完成"
    category = "memory"
    args_schema = CompleteActiveTaskInput

    async def _run(self, task: str) -> str:
        task = (task or "").strip()
        if not task:
            return "失败：task 不能为空"

        try:
            from core.services.self_improvement.service import get_self_improvement_service
            scope = _resolve_scope_from_context(self)
            si = get_self_improvement_service(scope=scope)
            ok = await si.complete_task(task)
            if ok:
                return f"已移除完成的任务（scope={scope}）: {task}"
            return f"未找到匹配任务（scope={scope}）: {task}"
        except Exception as e:
            logger.warning("complete_active_task 失败: %s", e, exc_info=True)
            return f"完成任务失败: {e}"


# ── 工具 5：记录对话摘要 ─────────────────────────────────


class RecordSummaryInput(BaseModel):
    summary: str = Field(
        description=(
            "对话摘要的简洁描述，例如「用户决定采用方案A重构记忆系统，"
            "下周一开始」「用户对晚安消息的语义边界提出纠正」。"
            "7 天后会被自动精简或归档。"
        )
    )


class RecordSummaryTool(BaseTool):
    name = "record_summary"
    description = (
        "记录一条对话摘要到核心记忆（MEMORY.md 对话摘要区，7天后精简）。"
        "在用户做出决策、完成复杂任务（≥5步）、对话出现重要节点时调用。"
        "不要记录普通对话或临时细节。"
    )
    short_description = "记录对话摘要到核心记忆"
    category = "memory"
    args_schema = RecordSummaryInput

    async def _run(self, summary: str) -> str:
        summary = (summary or "").strip()
        if not summary:
            return "失败：summary 不能为空"

        try:
            from core.services.self_improvement.service import get_self_improvement_service
            scope = _resolve_scope_from_context(self)
            si = get_self_improvement_service(scope=scope)
            ok = await si.add_summary(summary)
            if ok:
                return f"已记录对话摘要（scope={scope}）: {summary}"
            return f"该摘要已存在，未重复记录（scope={scope}）"
        except Exception as e:
            logger.warning("record_summary 失败: %s", e, exc_info=True)
            return f"记录摘要失败: {e}"
