"""
人物档案查询工具

让 AI 主动查询人物的详细档案（detailed 层），包括已知事实。
与自动注入的薄摘要互补：注入只给 description，工具查询给完整详情。
"""

from typing import Type

from pydantic import BaseModel, Field

from core.tools.base import BaseTool


class QueryPersonProfileInput(BaseModel):
    name: str = Field(
        description="要查询的人物名字或别名（传入你实际知道的那个称呼即可）"
    )


class QueryPersonProfileTool(BaseTool):
    name = "query_person_profile"
    description = (
        "查询你认识的某个人的详细档案。当你需要回忆关于某人的详细信息时使用，"
        "比如他的学校、工作、性格特点、你们之间的关系细节等。"
        "传入人物的名字或别名即可。"
    )
    args_schema: Type[BaseModel] = QueryPersonProfileInput
    category = "memory"

    def _current_role_id(self) -> str:
        """当前对话角色：优先本次请求携带的 persona_filename，其次工具 scope 兜底。

        解析不出时返回当前 tool scope（历史行为），不会误判成别的角色。
        """
        try:
            from core.services.dual_role.personas import resolve_role_id

            resolved = resolve_role_id(str(self._get_ctx("persona_filename") or ""))  # noqa: SLF001
            if resolved:
                return resolved
        except Exception:
            pass
        try:
            return str(self.current_role_scope() or "").strip().lower()
        except Exception:
            return ""

    async def _run(self, name: str) -> str:
        from core.character.people import get_people_profile_manager

        # 按当前角色过滤：自己的人设档案可以查，互识同伴的档案可以查，
        # 其余角色的档案一律当作"不认识的人"（防止Ye查到Aveline）。
        viewer_role_id = self._current_role_id()
        manager = get_people_profile_manager()
        profile = manager.query_profile_details(name, viewer_role_id=viewer_role_id)

        if profile is None:
            return f"没有找到关于「{name}」的档案。可能是不认识的人，或者名字拼写不对。"

        lines = [f"【{profile.name} 的详细档案】"]

        # 基本信息（core_fields）
        if profile.core_fields:
            lines.append("\n基本信息：")
            for k, v in profile.core_fields.items():
                if v:
                    lines.append(f"  {k}：{v}")

        # 摘要描述
        if profile.description:
            lines.append(f"\n简介：{profile.description}")

        # 已知事实（detailed 层）
        facts = profile.get_known_facts()
        if facts:
            lines.append("\n已知事实：")
            for fact in facts:
                confidence_str = (
                    f"（置信度{fact.confidence:.0%}）" if fact.confidence < 1.0 else ""
                )
                lines.append(f"  - {fact.key}：{fact.value}{confidence_str}")

        # 元数据
        if profile.last_mentioned:
            lines.append(f"\n最后提及：{profile.last_mentioned}")
        if profile.mention_count > 0:
            lines.append(f"提及次数：{profile.mention_count}")

        return "\n".join(lines)
