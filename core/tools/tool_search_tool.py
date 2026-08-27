"""按需发现工具的原生函数入口。"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .base import BaseTool


class SearchToolsInput(BaseModel):
    query: str = Field(description="用自然语言描述当前缺少的能力或要完成的动作")
    limit: int = Field(default=5, ge=1, le=8, description="最多返回多少个候选工具")


class SearchToolsTool(BaseTool):
    name = "search_tools"
    description = (
        "当当前已提供的工具无法完成用户请求时，按用户意图搜索可用工具。"
        "返回候选后，系统会在下一轮提供这些工具的完整参数定义。"
    )
    short_description = "搜索当前人设有权限使用的其他工具"
    category = "utility"
    args_schema = SearchToolsInput

    async def _run(self, query: str, limit: int = 5) -> str:
        agent = self._get_ctx("agent")
        registry = getattr(agent, "tool_registry", None)
        allowed_tool_names = self._get_ctx("allowed_tool_names", [])
        if registry is None:
            return json.dumps(
                {"type": "tool_discovery", "query": query, "tools": []},
                ensure_ascii=False,
            )

        matches = registry.search_tools(
            query,
            include_names=list(allowed_tool_names),
            limit=limit,
        )
        payload = {
            "type": "tool_discovery",
            "query": query,
            "tools": [item.to_dict() for item in matches],
            "instruction": "下一轮从候选工具中选择合适工具调用；不要向用户展示工具内部信息。",
        }
        return json.dumps(payload, ensure_ascii=False)
