"""角色现场状态的按需工具入口，不从自然语言回复二次抽取。"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from core.services.data_ops.ye_runtime_state import (
    character_state_tool_enabled,
    update_character_scene_state,
)
from core.tools.base import BaseTool


class UpdateCharacterStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence: str = Field(min_length=1, max_length=300, description="本轮已发生的角色状态变化依据；不能是计划、假设、提问或用户自身经历")
    location: Optional[str] = Field(default=None, min_length=1, max_length=240, description="角色当前所在地点；省略保留，null清空")
    activity: Optional[str] = Field(default=None, min_length=1, max_length=240, description="角色当前正在做的事；省略保留，null清空")
    clothing: Optional[str] = Field(default=None, min_length=1, max_length=240, description="变化后的完整当前衣着；省略保留，null清空")
    people_present: Optional[str] = Field(default=None, min_length=1, max_length=240, description="当前在场人物；独处可填独自一人；省略保留，null清空")
    physical_state: Optional[str] = Field(default=None, min_length=1, max_length=240, description="角色当前身体或情绪状态；省略保留，null清空")
    current_possessions: Optional[str] = Field(default=None, min_length=1, max_length=240, description="变化后的完整持有物；放下某物后只保留其余物品，全部放下传null；省略保留")


class UpdateCharacterStateTool(BaseTool):
    name = "update_character_state"
    description = (
        "更新你作为当前角色的位置、活动、衣着、在场人物、身体状态和持有物。"
        "仅在本轮明确发生变化或纠正旧状态时调用；不能记录用户或其他角色的状态，"
        "不能把打算、假设、提问写成已发生的事实。只传变化字段，省略保留、null清空；"
        "衣着和持有物传变化后的完整内容。成功后最终回复须与保存结果一致，失败时不能声称已保存。"
    )
    short_description = "更新当前角色的位置、衣着、活动与持有物"
    category = "daily"
    args_schema = UpdateCharacterStateInput
    is_available_for_persona = staticmethod(character_state_tool_enabled)

    async def _run(self, **kwargs) -> str:
        # 在首次await前快照上下文，防止注册表共享工具实例被并发请求覆盖。
        context = dict(getattr(self, "_runtime_context", {}))
        if self.name not in context.get("allowed_tool_names", []):
            return json.dumps({"ok": False, "error": "当前会话无权调用此工具"}, ensure_ascii=False)
        request = UpdateCharacterStateInput.model_validate(kwargs)
        updates = request.model_dump(exclude_unset=True, exclude={"evidence"})
        result = await update_character_scene_state(
            conversation_id=str(context.get("user_id") or ""),
            persona_filename=context.get("persona_filename"),
            updates=updates,
            evidence=request.evidence,
        )
        return json.dumps(result, ensure_ascii=False)
