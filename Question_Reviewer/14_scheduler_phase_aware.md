# Phase-Aware 调度器

本分类共 4 条记录。按时间倒序（最新在前）排列。

---

### 10.132 Phase-Aware 调度器决策引擎重复计数 (2026-06-20)

*   **问题描述**: `decision_stats.total_decisions` 是实际任务数的 2 倍，且 bypass 决策未被记录
*   **复现步骤**:
    1. 提交 1 image + 2 vlm + 2 rag 任务
    2. 查看 always_migrate 策略的决策统计，total_decisions=5（应为 3，只有 image+vlm 触发决策）
*   **预期行为**: 每个任务只记录一次决策
*   **实际行为**: GPU_PREFERRED 任务在 submit_phase（路由）和 _execute_gpu_burst（执行）中各调用一次 decide()，重复计数
*   **修复方法**: decide() 新增 `record_history` 参数，submit_phase 路由决策传 `record_history=False`，只有 _execute_gpu_burst 执行决策才记录历史

### 10.131 Phase-Aware 调度器 backfill_hidden_time 始终为 0 (2026-06-20)

*   **问题描述**: 即使 CPU 任务与 GPU 任务并行执行，`backfill_hidden_time` 仍为 0
*   **复现步骤**:
    1. 提交 TTS（CPU）和 Image（GPU）并行任务
    2. TTS 先于 Image 开始执行（Image 需要迁移 LLM）
    3. TTS 执行期间 Image 开始（GPU 被占用）
    4. 查看 backfill 统计，`total_backfill_time_hidden_s` 为 0
*   **预期行为**: TTS 与 GPU 任务并行，应算 backfill，隐藏 GPU 等待时间
*   **实际行为**: backfill 只在任务开始时检查 GPU 占用，TTS 开始时 GPU 未被占用，不算 backfill
*   **修复方法**: 修改 backfill 统计逻辑，任务完成时检查 GPU 是否被占用（`is_backfill_at_start or self._gpu_occupied`），只要执行期间 GPU 被占用过就算 backfill

### 10.130 Phase-Aware 调度器 RESIDENT_MIGRATABLE 任务被错误路由到 backfill (2026-06-20)

*   **问题描述**: LLM（RESIDENT_MIGRATABLE）作为 workflow 阶段执行时，被路由到 backfill（CPU），而非在 GPU 上执行
*   **复现步骤**:
    1. 构建 workflow: RAG → LLM → TTS + Image
    2. 用 V2_PHASE_AWARE 策略执行
    3. 查看执行轨迹，LLM 在 CPU 上执行（strategy=backfill）
*   **预期行为**: LLM 应常驻 GPU 执行（持有 RESIDENT 租约）
*   **实际行为**: LLM 被路由到 backfill（CPU）
*   **根本原因**: LLM 的 device_affinity 是 GPU_PREFERRED，触发了决策引擎的 bypass 规则（规则2：GPU_PREFERRED 降级 CPU）。但 LLM 是 RESIDENT_MIGRATABLE 角色，不应被降级
*   **修复方法**: 在 `submit_phase` 中优先检查 `attrs.role == PhaseRole.RESIDENT_MIGRATABLE`，直接调用 `_execute_resident()` 在 GPU 上执行，不走决策引擎 bypass 逻辑

### 10.129 Phase-Aware 调度器 LLMState 降级时间统计为 0 (2026-06-20)

*   **问题描述**: `LLMState.total_degraded_time_s` 始终为 0，即使 LLM 被迁移过
*   **复现步骤**:
    1. 提交 GPU burst 任务触发 LLM 迁移
    2. 查看 `scheduler.get_stats()`，`llm_total_degraded_time_s` 为 0
*   **预期行为**: 降级时间应等于 LLM 在 CPU 上的总时长（从 enter_degraded 到 enter_normal）
*   **实际行为**: 始终为 0
*   **根本原因**: `enter_restoring()` 把 level 改成 RESTORING 后，`enter_normal()` 检查 `level == CPU_DEGRADED` 不成立，漏算降级时间
*   **修复方法**: 在 `enter_restoring()` 中累加降级时间（回迁期间 LLM 仍处于非 GPU 正常状态），`enter_normal()` 加兜底检查
