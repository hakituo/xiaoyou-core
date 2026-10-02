/**
 * Phase-Aware 调度策略实现
 *
 * 核心决策逻辑：
 * 1. CPU-affine 任务（RAG/OCR）：旁路，不触发迁移
 * 2. GPU_PREFERRED 任务（VLM/TTS）：降级 CPU，不迁移 LLM
 * 3. GPU_REQUIRED 任务（Image）：
 *    - LLM 已降级 → 旁路（GPU 已空闲）
 *    - LLM 在推理且快完成 → 等待
 *    - 否则 → 迁移 LLM 释放显存
 */

#include "phase_strategy.h"
#include "resource_isolation_scheduler.h"
#include <algorithm>
#include <iostream>

namespace ai_scheduler {

// ============================================================
// 辅助构造函数（C++17 兼容，不用 designated initializers）
// ============================================================

/// 构造 PhaseAttributes
static PhaseAttributes makePhaseAttrs(
    PhaseRole role,
    DeviceAffinity affinity,
    bool preemptible,
    bool queueable,
    bool migratable,
    size_t vram_mb,
    double duration_s,
    bool downstream,
    bool upstream,
    bool overlap_gpu)
{
    PhaseAttributes a;
    a.role = role;
    a.device_affinity = affinity;
    a.preemptible = preemptible;
    a.queueable = queueable;
    a.migratable = migratable;
    a.vram_usage_mb = vram_mb;
    a.typical_duration_s = duration_s;
    a.is_downstream = downstream;
    a.is_upstream = upstream;
    a.can_overlap_with_gpu = overlap_gpu;
    return a;
}

/// 构造 MigrationDecision
static MigrationDecision makeDecision(
    bool should_migrate,
    const std::string& reason,
    double pred_duration,
    const MigrationCost& cost,
    double wait_cost = 0.0,
    double benefit = 0.0,
    const std::string& strategy = "bypass")
{
    MigrationDecision d;
    d.should_migrate = should_migrate;
    d.reason = reason;
    d.predicted_burst_duration_s = pred_duration;
    d.migration_cost = cost;
    d.wait_cost_s = wait_cost;
    d.benefit_s = benefit;
    d.strategy = strategy;
    return d;
}

// ============================================================
// Phase 预设
// ============================================================

PhaseAttributes getPhasePreset(const std::string& phase_name) {
    if (phase_name == "llm") {
        return makePhaseAttrs(
            PhaseRole::RESIDENT_MIGRATABLE, DeviceAffinity::GPU_PREFERRED,
            true, false, true, 6000, 3.0, false, false, false);
    } else if (phase_name == "image") {
        return makePhaseAttrs(
            PhaseRole::BURST_GPU_PINNED, DeviceAffinity::GPU_REQUIRED,
            false, true, false, 4000, 7.0, true, false, false);
    } else if (phase_name == "vlm") {
        return makePhaseAttrs(
            PhaseRole::BURST_GPU_PREFERRED, DeviceAffinity::GPU_PREFERRED,
            true, true, false, 2000, 2.5, true, false, true);
    } else if (phase_name == "tts") {
        return makePhaseAttrs(
            PhaseRole::BURST_CPU_LIGHT, DeviceAffinity::CPU_PREFERRED,
            true, true, false, 0, 2.0, true, false, true);
    } else if (phase_name == "rag") {
        return makePhaseAttrs(
            PhaseRole::BURST_CPU_LIGHT, DeviceAffinity::CPU_ONLY,
            true, true, false, 0, 0.8, false, true, true);
    } else if (phase_name == "ocr") {
        return makePhaseAttrs(
            PhaseRole::BURST_CPU_LIGHT, DeviceAffinity::CPU_ONLY,
            true, true, false, 0, 1.2, false, true, true);
    }
    return PhaseAttributes{};
}

// ============================================================
// Cost-Aware 决策引擎
// ============================================================

MigrationDecision CostAwareDecisionEngine::decide(
    const PhaseAttributes& burst_attrs,
    const LLMState& llm_state,
    size_t queue_depth,
    double llm_remaining_work_s)
{
    stats_.total_decisions++;
    double pred_duration = burst_attrs.typical_duration_s;

    // 规则 1：CPU-affine 任务旁路，不触发迁移
    if (isCpuAffine(burst_attrs.device_affinity)) {
        stats_.bypass_count++;
        return makeDecision(false, "CPU-affine 阶段旁路，不触发迁移",
            pred_duration, migration_cost_, 0, 0, "bypass");
    }

    // 规则 2：GPU_PREFERRED 任务降级 CPU，不迁移 LLM
    if (burst_attrs.device_affinity == DeviceAffinity::GPU_PREFERRED) {
        stats_.bypass_count++;
        std::string reason = (llm_state.level() == LLMServiceLevel::GPU_NORMAL)
            ? "GPU_PREFERRED 阶段降级 CPU，避免迁移 LLM"
            : "GPU_PREFERRED 阶段走 CPU（LLM 已降级）";
        return makeDecision(false, reason, pred_duration, migration_cost_, 0, 0, "bypass");
    }

    // 规则 3：GPU_REQUIRED 任务必须释放显存
    if (llm_state.level() == LLMServiceLevel::CPU_DEGRADED) {
        stats_.bypass_count++;
        return makeDecision(false, "LLM 已在 CPU 降级状态，GPU 空闲",
            pred_duration, migration_cost_, 0, 0, "bypass");
    }

    double migration_cost_s = migration_cost_.totalRoundTripMs() / 1000.0;

    // 规则 3a：LLM 在推理且快完成，短暂等待比迁移划算
    if (llm_remaining_work_s > 0
        && llm_remaining_work_s < short_burst_threshold_s_
        && queue_depth == 0) {
        stats_.wait_count++;
        return makeDecision(false, "LLM 即将完成，短暂等待比迁移划算",
            pred_duration, migration_cost_,
            llm_remaining_work_s, llm_remaining_work_s - migration_cost_s, "wait");
    }

    // 规则 3b：GPU_REQUIRED 必须迁移
    stats_.migrate_count++;
    return makeDecision(true, "GPU_REQUIRED 阶段需要显存，迁移 LLM 释放 GPU",
        pred_duration, migration_cost_, 0, -migration_cost_s, "migrate");
}

// ============================================================
// Always-Migrate 决策引擎
// ============================================================

MigrationDecision AlwaysMigrateDecisionEngine::decide(
    const PhaseAttributes& burst_attrs,
    const LLMState& llm_state,
    size_t queue_depth,
    double llm_remaining_work_s)
{
    stats_.total_decisions++;
    double pred_duration = burst_attrs.typical_duration_s;

    if (isCpuAffine(burst_attrs.device_affinity)) {
        stats_.bypass_count++;
        return makeDecision(false, "CPU-affine 阶段旁路",
            pred_duration, migration_cost_, 0, 0, "bypass");
    }

    if (llm_state.level() == LLMServiceLevel::CPU_DEGRADED) {
        stats_.bypass_count++;
        return makeDecision(false, "LLM 已降级",
            pred_duration, migration_cost_, 0, 0, "bypass");
    }

    stats_.migrate_count++;
    return makeDecision(true, "always-migrate 策略：无条件迁移",
        pred_duration, migration_cost_, 0, 0, "migrate");
}

// ============================================================
// DefaultPhaseAwareStrategy
// ============================================================

DefaultPhaseAwareStrategy::DefaultPhaseAwareStrategy(const PhaseAwareConfig& config)
    : config_(config)
    , lease_manager_(config.vram_total_mb)
{
    if (config.migration_policy == MigrationPolicy::ALWAYS_MIGRATE) {
        decision_engine_ = std::make_unique<AlwaysMigrateDecisionEngine>(config.migration_cost);
    } else {
        decision_engine_ = std::make_unique<CostAwareDecisionEngine>(
            config.migration_cost,
            config.short_burst_threshold_s,
            config.benefit_threshold_s,
            config.queue_pressure_threshold);
    }
}

std::string DefaultPhaseAwareStrategy::routeTask(
    const PhaseAttributes& attrs,
    const LLMState& llm_state,
    SchedulerPolicy policy)
{
    if (policy == SchedulerPolicy::SEQUENTIAL) {
        return "sequential";
    }
    if (attrs.role == PhaseRole::RESIDENT_MIGRATABLE) {
        return "resident_gpu";
    }
    if (policy == SchedulerPolicy::V1_DUAL_ROLE) {
        return "gpu_burst";
    }
    if (isCpuAffine(attrs.device_affinity)) {
        return "cpu_backfill";
    }
    if (attrs.device_affinity == DeviceAffinity::GPU_PREFERRED) {
        auto decision = decision_engine_->decide(attrs, llm_state, 0, 0.0);
        if (decision.strategy == "bypass") {
            return "cpu_backfill";
        }
    }
    return "gpu_burst";
}

std::shared_ptr<IWorker> DefaultPhaseAwareStrategy::selectWorkerForPhase(
    const PhaseAttributes& attrs,
    const std::vector<std::shared_ptr<IWorker>>& gpu_workers,
    const std::vector<std::shared_ptr<IWorker>>& cpu_workers,
    const std::shared_ptr<IWorker>& llm_worker)
{
    if (attrs.role == PhaseRole::RESIDENT_MIGRATABLE) {
        if (llm_worker && !llm_worker->isBusy()) return llm_worker;
        return nullptr;
    }
    if (isCpuAffine(attrs.device_affinity)) {
        for (const auto& worker : cpu_workers) {
            if (!worker->isBusy()) return worker;
        }
        return nullptr;
    }
    for (const auto& worker : gpu_workers) {
        if (worker != llm_worker && !worker->isBusy()) return worker;
    }
    return nullptr;
}

MigrationDecision DefaultPhaseAwareStrategy::shouldMigrateLLM(
    const PhaseAttributes& burst_attrs,
    const LLMState& llm_state,
    size_t queue_depth)
{
    return decision_engine_->decide(burst_attrs, llm_state, queue_depth, 0.0);
}

bool DefaultPhaseAwareStrategy::migrateLLMToCPU(bool urgent) {
    if (migrate_fn_) {
        bool ok = migrate_fn_(urgent);
        if (ok) {
            llm_state_.enterDegraded();
            lease_manager_.downgradeResident("llm_resident");
        }
        return ok;
    }
    llm_state_.enterDegraded();
    lease_manager_.downgradeResident("llm_resident");
    return true;
}

bool DefaultPhaseAwareStrategy::restoreLLMToGPU() {
    llm_state_.enterRestoring();
    if (restore_fn_) {
        bool ok = restore_fn_();
        if (ok) {
            llm_state_.enterNormal();
            lease_manager_.restoreResident("llm_resident", 6000);
        } else {
            llm_state_.enterDegraded();
        }
        return ok;
    }
    llm_state_.enterNormal();
    lease_manager_.restoreResident("llm_resident", 6000);
    return true;
}

} // namespace ai_scheduler
