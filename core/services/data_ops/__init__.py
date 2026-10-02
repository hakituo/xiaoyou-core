"""数据运维（data-ops）包的惰性门面。

`service` / `api` 会连带拉起 `bert_analyzer` → transformers、onnxruntime 等重型依赖，
而这些依赖在轻量环境（CI 的 `uv sync --extra dev`，不含 models extra）里并不存在。
本包里同时有 `scene_facts` 这种只依赖标准库的纯函数模块，一旦 `__init__` 在导入期
就拉起整条依赖链，"只想用一个正则函数"的调用方也会被 transformers 缺失拖成
ImportError。因此这里改为按需解析（PEP 562）：

- `from core.services.data_ops import scene_facts` 只导入目标子模块；
- `from core.services.data_ops import get_data_ops_service` 这类门面符号，
  在真正取用时才导入 `service` / `api` / `core.api.contract`；
- `import core.services.data_ops.service` 不受影响，语义与惰性前一致。
"""

from importlib import import_module
from typing import Any

__all__ = [
    "DataOpsService",
    "get_data_ops_service",
    "validate_internal_token",
    "unauthorized_response",
    "submit_daily_digest",
    "submit_weekly_report",
    "submit_task_plan",
    "submit_human_daily_digest",
    "submit_human_weekly_report",
    "submit_memory_rule_analysis",
    "submit_memory_ai_shadow_analysis",
    "submit_memory_fusion_adjudication",
    "run_data_ops_task",
    "get_data_ops_task",
    "get_memory_rule_analysis_metrics",
    "get_memory_ai_shadow_metrics",
    "get_memory_fusion_metrics",
]

# 门面符号 -> 提供它的模块（相对包名以 "." 开头）
_LAZY_ATTR_MODULES = {
    "DataOpsService": ".service",
    "get_data_ops_service": ".service",
    "validate_internal_token": "core.api.contract",
    "unauthorized_response": ".api",
    "submit_daily_digest": ".api",
    "submit_weekly_report": ".api",
    "submit_task_plan": ".api",
    "submit_human_daily_digest": ".api",
    "submit_human_weekly_report": ".api",
    "submit_memory_rule_analysis": ".api",
    "submit_memory_ai_shadow_analysis": ".api",
    "submit_memory_fusion_adjudication": ".api",
    "run_data_ops_task": ".api",
    "get_data_ops_task": ".api",
    "get_memory_rule_analysis_metrics": ".api",
    "get_memory_ai_shadow_metrics": ".api",
    "get_memory_fusion_metrics": ".api",
}


def __getattr__(name: str) -> Any:
    """按需解析门面符号与子模块，避免导入期拉起重型依赖。"""
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name = _LAZY_ATTR_MODULES.get(name)
    if module_name is None:
        # 未登记的名字按子模块处理，保持 `from core.services.data_ops import <子模块>` 可用
        try:
            value = import_module(f".{name}", __name__)
        except ImportError as exc:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    else:
        value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_ATTR_MODULES))
