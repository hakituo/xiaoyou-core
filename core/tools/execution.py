"""统一工具执行边界：当前角色授权集合及单次调用上下文隔离。"""

from copy import copy
import json
from typing import Any, Mapping, Optional


async def execute_tool_call(
    *, agent: Any, tool_name: str, arguments: Mapping[str, Any],
    user_id: str, allowed_tool_names: list[str],
    persona_filename: Optional[str] = None, is_sensitive_mode: bool = False,
    used_tool_names: Optional[list[str]] = None,
    last_user_text: str = "",
) -> str:
    """不接受模型自选角色、路径或权限；使用编排层传入的当前请求快照。

    ``used_tool_names`` 是本请求级的收集容器，供跨请求 carryover 使用。
    判断口径是「授权通过并真正进入执行」，不看业务结果：
    ``BaseTool.run()`` 会把工具内部异常转成错误字符串，调用方无法可靠区分，
    而天气接口超时这类失败恰恰需要下一轮重试同一个工具。

    ``last_user_text`` 是本轮用户消息原文，注入给需要「只能引用用户原话」的
    工具做校验（如学习模式的 subject/topic 反脑补）。
    """
    registry = getattr(agent, "tool_registry", None)
    if tool_name not in allowed_tool_names or registry is None or not registry.is_enabled(tool_name):
        return json.dumps({"ok": False, "error": "当前角色未获准调用该工具", "tool": tool_name}, ensure_ascii=False)
    if not isinstance(arguments, Mapping):
        return json.dumps({"ok": False, "error": "工具参数必须为对象"}, ensure_ascii=False)
    # 注册表保存可复用实现；每次调用使用独立上下文，避免不同角色并发串写。
    tool = copy(registry.get_tool(tool_name))
    tool.set_runtime_context({
        "agent": agent, "user_id": user_id, "persona_filename": persona_filename,
        "scope": "sensitive" if is_sensitive_mode else "sfw",
        "allowed_tool_names": list(allowed_tool_names),
        "last_user_text": str(last_user_text or ""),
    })
    if used_tool_names is not None and tool_name not in used_tool_names:
        used_tool_names.append(tool_name)
    return await tool.run(**dict(arguments))
