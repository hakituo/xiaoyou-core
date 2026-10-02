"""AI 影子分析与融合裁决（薄壳门面）。

拆分说明（薄壳门面 + 按职责拆子模块）
--------------------------------------
原 1125 行单文件按职责拆成下列子模块，本文件只做门面转发，
**对外路径与符号名不变**（``from memory.core.analysis_ops import ...`` 照旧可用）：

| 子模块 | 职责 |
|---|---|
| ``analysis_types.py``          | 融合配置 / 常量 / ``FusionResult`` / 通用清洗纯函数 |
| ``analysis_scoring.py``        | 打分与风险分级（``_compute_*`` / ``_assess_risk_level``） |
| ``analysis_shadow.py``         | ai_shadow 构建、BERT 分析与读写 |
| ``analysis_fusion.py``         | 融合动作执行与融合元数据写入 |
| ``analysis_adjudication.py``   | 批量融合裁决 ``apply_ai_shadow_adjudication`` |
| ``analysis_pending.py``        | 待分析记忆的规则分析（锁外）与结果落库（锁内） |
| ``analysis_pending_runner.py`` | 待分析批处理编排 ``process_pending_analysis`` |

拆分是**纯搬家**：未改逻辑、命名与断言，唯一差异是 import 与门面转发的样板行。
"""
from __future__ import annotations

# 兼容：原单文件模块顶层有 `import time`，保留同名属性以免按旧路径 patch 失效
import time  # noqa: F401

from memory.core.analysis_adjudication import (
    apply_ai_shadow_adjudication as apply_ai_shadow_adjudication,
)
from memory.core.analysis_fusion import (
    _apply_fusion_action as _apply_fusion_action,
)
from memory.core.analysis_fusion import (
    _write_fusion_metadata as _write_fusion_metadata,
)
from memory.core.analysis_pending import (
    _apply_pending_analysis_result as _apply_pending_analysis_result,
)
from memory.core.analysis_pending import (
    _prepare_pending_analysis as _prepare_pending_analysis,
)
from memory.core.analysis_pending_runner import (
    process_pending_analysis as process_pending_analysis,
)
from memory.core.analysis_scoring import (
    _assess_risk_level as _assess_risk_level,
)
from memory.core.analysis_scoring import (
    _compute_consistency_score as _compute_consistency_score,
)
from memory.core.analysis_scoring import (
    _compute_final_confidence as _compute_final_confidence,
)
from memory.core.analysis_scoring import (
    _compute_rule_score as _compute_rule_score,
)
from memory.core.analysis_scoring import (
    _compute_stability_score as _compute_stability_score,
)
from memory.core.analysis_scoring import (
    _compute_trigger_decision as _compute_trigger_decision,
)
from memory.core.analysis_shadow import (
    _build_ai_shadow_dict as _build_ai_shadow_dict,
)
from memory.core.analysis_shadow import (
    _build_bert_shadow_input as _build_bert_shadow_input,
)
from memory.core.analysis_shadow import (
    _run_bert_shadow_analysis as _run_bert_shadow_analysis,
)
from memory.core.analysis_shadow import (
    attach_ai_shadow_result as attach_ai_shadow_result,
)
from memory.core.analysis_shadow import (
    count_ai_shadow_results as count_ai_shadow_results,
)
from memory.core.analysis_shadow import (
    count_pending_analysis as count_pending_analysis,
)
from memory.core.analysis_shadow import (
    get_pending_analysis_items as get_pending_analysis_items,
)
from memory.core.analysis_types import (
    BLOCKED_DISCOURSE_LABELS as BLOCKED_DISCOURSE_LABELS,
)
from memory.core.analysis_types import (
    DEFAULT_FUSION_CONFIG as DEFAULT_FUSION_CONFIG,
)
from memory.core.analysis_types import (
    DISCOURSE_WEIGHT_PENALTIES as DISCOURSE_WEIGHT_PENALTIES,
)
from memory.core.analysis_types import (
    RISK_CATEGORIES as RISK_CATEGORIES,
)
from memory.core.analysis_types import (
    RISK_MEMORY_TYPES as RISK_MEMORY_TYPES,
)
from memory.core.analysis_types import (
    FusionConfig as FusionConfig,
)
from memory.core.analysis_types import (
    FusionResult as FusionResult,
)
from memory.core.analysis_types import (
    _clean_category as _clean_category,
)
from memory.core.analysis_types import (
    _clean_topics as _clean_topics,
)
from memory.core.analysis_types import (
    _ensure_analysis_meta as _ensure_analysis_meta,
)
from memory.core.analysis_types import (
    _safe_float as _safe_float,
)

# 兼容入口：原单文件模块顶层可见的导入（供 patch 与按旧路径引用）
from memory.core.discourse import (
    analyze_discourse as analyze_discourse,
)
from memory.core.discourse import (
    infer_state_event as infer_state_event,
)
from memory.core.lock_utils import (
    get_read_lock as get_read_lock,
)
from memory.core.lock_utils import (
    get_write_lock as get_write_lock,
)

# 对外契约：与原单文件时期的顶层公开符号一一对应，一个不少。
__all__ = [
    # 配置 / 常量 / 结果容器
    "BLOCKED_DISCOURSE_LABELS",
    "DEFAULT_FUSION_CONFIG",
    "DISCOURSE_WEIGHT_PENALTIES",
    "RISK_CATEGORIES",
    "RISK_MEMORY_TYPES",
    "FusionConfig",
    "FusionResult",
    # 通用清洗
    "_clean_category",
    "_clean_topics",
    "_ensure_analysis_meta",
    "_safe_float",
    # 影子结果
    "_build_ai_shadow_dict",
    "_build_bert_shadow_input",
    "_run_bert_shadow_analysis",
    "attach_ai_shadow_result",
    "count_ai_shadow_results",
    "count_pending_analysis",
    "get_pending_analysis_items",
    # 打分与融合
    "_assess_risk_level",
    "_compute_consistency_score",
    "_compute_final_confidence",
    "_compute_rule_score",
    "_compute_stability_score",
    "_compute_trigger_decision",
    "_apply_fusion_action",
    "_write_fusion_metadata",
    "apply_ai_shadow_adjudication",
    # 待分析批处理
    "_apply_pending_analysis_result",
    "_prepare_pending_analysis",
    "process_pending_analysis",
]
