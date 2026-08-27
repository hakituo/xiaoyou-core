"""
元认知服务模块 - 实验性/待定

此模块当前为实验性状态，功能已被以下模块覆盖：
- 意图追踪: PersistentStateTracker + BERT 意图检测
- 主动提醒: Active Care (reminder/health_reminder/wake_up_greeting)
- 历史检索: RAG search_memory（语义级检索）
- 行为记录: 日记系统 (Journal) + tomorrow_tone 回注
- 去重/防重复: Active Care 三层去重 + 二次改写

保留此模块作为未来功能参考（AI 回复风格追踪、对话节奏感知、跨人设一致性校验）

注意：此模块不建议在生产环境中直接使用，可能在未来版本中移除。
"""

# 惰性导入，避免自动加载
def __getattr__(name: str):
    if name in ("TrackedIntent", "MetaIntentService", "get_meta_intent_service"):
        import warnings
        warnings.warn(
            f"core.services.metacognition.{name} 是实验性模块，功能已被其他模块覆盖，"
            "可能在未来版本中移除。",
            DeprecationWarning,
            stacklevel=2
        )
        from core.services.metacognition.service import (
            TrackedIntent,
            MetaIntentService,
            get_meta_intent_service,
        )
        _exports = {
            "TrackedIntent": TrackedIntent,
            "MetaIntentService": MetaIntentService,
            "get_meta_intent_service": get_meta_intent_service,
        }
        return _exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["TrackedIntent", "MetaIntentService", "get_meta_intent_service"]
