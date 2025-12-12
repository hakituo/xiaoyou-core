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
    
    def get_tools_description(self, include_names: List[str] = None) -> str:
        """
        Returns a formatted string describing available tools.
        If include_names is provided, only tools with those names are included.
        Simplified to reduce token usage.
        """
        descriptions = []
        for tool in self._tools.values():
            if include_names is not None and tool.name not in include_names:
                continue
            # Simplified argument description
            args_simple = {}
            if tool.args_schema:
                schema = tool.args_schema.schema()
                props = schema.get("properties", {})
                required = schema.get("required", [])
                
                for prop_name, prop_info in props.items():
                    desc = prop_info.get("description", "")
                    typ = prop_info.get("type", "any")
                    is_req = "*" if prop_name in required else ""
                    args_simple[f"{prop_name}{is_req}"] = f"{typ} - {desc}"
            
            import json
            args_desc = json.dumps(args_simple, ensure_ascii=False)
            descriptions.append(f"- Name: {tool.name}\n  Description: {tool.description}\n  Args: {args_desc}")
        return "\n".join(descriptions)
