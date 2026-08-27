# -*- coding: utf-8 -*-
"""context_budget 子包。

按职责拆分自原 context_budget.py（1138行），拆分为 4 个独立模块：
- history_fetch.py：历史获取与清洗（簇 A）
- history_compression.py：历史消息压缩（簇 B，纯函数）
- budget_apply.py：云端/本地上下文预算裁剪（簇 C）
- memory_injection.py：思考库与敏感记忆注入（簇 D）
- _utils.py：共享工具函数

外部统一从本 __init__.py 导入，保持原 context_budget.py 的公开 API 不变。
"""

from .history_fetch import fetch_history_for_scope
from .budget_apply import apply_cloud_history_budget, apply_local_context_budget
from .memory_injection import inject_thinking_store, inject_sensitive_memories

__all__ = [
    "fetch_history_for_scope",
    "apply_cloud_history_budget",
    "apply_local_context_budget",
    "inject_thinking_store",
    "inject_sensitive_memories",
]
