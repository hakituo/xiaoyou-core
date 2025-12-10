from typing import Dict, List, Optional
from .base import BaseTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())
    
    def get_tools_description(self) -> str:
        """
        Returns a formatted string describing all available tools.
        """
        descriptions = []
        for tool in self._tools.values():
            args_desc = tool.args_schema.schema_json() if tool.args_schema else "{}"
            descriptions.append(f"- Name: {tool.name}\n  Description: {tool.description}\n  Arguments: {args_desc}")
        return "\n\n".join(descriptions)
