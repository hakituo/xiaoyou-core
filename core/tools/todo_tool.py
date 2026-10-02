"""待办清单工具。

给所有角色共用的常驻能力：把这个角色记下的、关于主人的事存下来，做完了就划掉。
和 plan 系列工具的区别：plan 是按天排的学习生活计划（有学科、提醒、日期），
这里是不挑场景的随手待办，只管"有一件事要记着 / 这件事完了"。

待办按角色隔离：Aveline记的只有Aveline看得到，叶有自己的一份。
合成单工具是为了让常驻 schema 尽可能小——每多一个常驻工具，每轮对话都要多付一份定义。
"""

from __future__ import annotations

import asyncio
from typing import Optional, Type

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.services.workspace.todo_store import get_todo_store

_ACTIONS = ("list", "add", "done", "remove")


def _resolve_scope(persona_filename: Optional[str]) -> str:
    """把当前人设解析成稳定 scope，决定这份待办存在哪个角色目录下。"""
    try:
        from core.utils.data.scope_registry import resolve_persona_slug_scope

        return resolve_persona_slug_scope(persona_filename) or "user"
    except Exception:
        return "user"


class ManageTodoInput(BaseModel):
    action: str = Field(description="list/add/done/remove")
    title: str = Field(default="", description="add 时的待办内容")
    item_id: str = Field(default="", description="done/remove 时的编号")


class ManageTodoTool(BaseTool):
    name = "manage_todo"
    description = (
        "你的待办清单。list 看还没做的；add 记一条（主人要做的事、你答应过的，直接记）；"
        "done 划掉；remove 删掉记错的。做完立刻 done，不用先问。"
    )
    short_description = "记待办、查看待办、做完划掉"
    category = "todo"
    args_schema: Type[BaseModel] = ManageTodoInput

    async def _run(self, action: str = "list", title: str = "", item_id: str = "") -> str:
        # 上下文在首次 await 前快照：执行时工具实例是浅复制出来的
        scope = _resolve_scope(self._get_ctx("persona_filename"))
        store = get_todo_store(scope)
        act = str(action or "list").strip().lower()

        def _dispatch() -> str:
            if act == "list":
                return store.format_for_llm()
            if act == "add":
                if not str(title or "").strip():
                    return "add 需要给出 title"
                item = store.add_item(title)
                return f"记下了：{store.format_item(item)}\n\n{store.format_for_llm()}"
            if act == "done":
                item = store.update_item(item_id, {"status": "done"})
                return f"划掉了：{store.format_item(item)}\n\n{store.format_for_llm()}"
            if act == "remove":
                item = store.remove_item(item_id)
                return f"删掉了：{store.format_item(item)}\n\n{store.format_for_llm()}"
            return f"action 只能是 {''.join(a + '/' for a in _ACTIONS).rstrip('/')}"

        try:
            return await asyncio.to_thread(_dispatch)
        except ValueError as e:
            return str(e)
