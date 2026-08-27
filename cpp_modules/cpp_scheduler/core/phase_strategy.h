#pragma once
/**
 * Phase-Aware 调度策略接口与默认实现
 *
 * 把本地 AI 助手建模成多阶段 workflow，利用阶段级资源互补性：
 * - LLM decode phase: resident / migratable / latency-sensitive
 * - Image generation phase: GPU-exclusive / non-preemptible / queueable
 * - TTS phase: CPU-affine / downstream / can overlap
 * - RAG/OCR phase: CPU/DDR-affine / upstream / bypass GPU
 *
 * 与 Python 层 phase_aware 模块对齐，提供 C++ 原生的策略决策。
 */

#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <chrono>
#include <atomic>
#include <mutex>
#include <functional>
#include <cmath>

namespace ai_scheduler {

// ============================================================
// Phase-Aware 核心枚举
// ============================================================

/// 阶段角色：任务在 workflow 中的角色分类
enum class PhaseRole {
    RESIDENT_MIGRATABLE,  // 常驻可迁移（如 LLM）
    BURST_GPU_PINNED,     // GPU 独占 burst（如 Image Generation）
    BURST_GPU_PREFERRED,  // GPU 优先 burst（如 VLM），可降级 CPU
    BURST_CPU_LIGHT       // CPU 轻量 burst（如 RAG/OCR）
};

/// 设备亲和性：任务对设备的偏好
enum class DeviceAffinity {
    GPU_REQUIRED,   // 必须 GPU（如 Image Generation，显存需求大）
    GPU_PREFERRED,  // 优先 GPU（如 VLM/TTS），可降级 CPU
    CPU_ONLY,       // 只能 CPU（如 RAG embedding）
    CPU_PREFERRED   // 优先 CPU（如 OCR）
};

/// LLM 服务等级（降级状态机）
enum class LLMServiceLevel {
    GPU_NORMAL,     // LLM 在 GPU 上正常运行
    CPU_DEGRADED,   // LLM 迁移到 CPU，降级运行
    RESTORING       // LLM 正在从 CPU 回迁 GPU
};

/// 迁移策略
enum class MigrationPolicy {
    ALWAYS_MIGRATE,  // 来了就迁（v1 行为）
    COST_AWARE       // 代价感知（v2 行为）
};

/// 调度策略
enum class SchedulerPolicy {
    SEQUENTIAL,       // 串行执行（baseline）
    V1_DUAL_ROLE,     // 二元互斥（来了就迁，CPU 不 backfill）
    V2_PHASE_AWARE    // Phase-Aware + Cost-Aware + Backfilling
};

// ============================================================
// Phase 属性与任务
// ============================================================

/// 阶段属性：描述一个阶段对资源的需求和约束
struct PhaseAttributes {
    PhaseRole role = PhaseRole::BURST_CPU_LIGHT;
    DeviceAffinity device_affinity = DeviceAffinity::CPU_ONLY;
    bool preemptible = false;       // 是否可被抢占
    bool queueable = true;          // 是否可排队
    bool migratable = false;        // 是否可迁移
    size_t vram_usage_mb = 0;       // 显存需求（MB）
    double typical_duration_s = 0.0; // 典型执行时长（秒）
    bool is_downstream = false;     // 是否是下游阶段（依赖 LLM 输出）
    bool is_upstream = false;       // 是否是上游阶段（为 LLM 提供输入）
    bool can_overlap_with_gpu = false; // 是否可与 GPU 任务并行

    bool needsGpu() const { return device_affinity == DeviceAffinity::GPU_REQUIRED || device_affinity == DeviceAffinity::GPU_PREFERRED; }
    bool isCpuAffine() const { return device_affinity == DeviceAffinity::CPU_ONLY || device_affinity == DeviceAffinity::CPU_PREFERRED; }
};

/// 迁移代价：LLM GPU→CPU 迁移的各阶段耗时
struct MigrationCost {
    double kv_cache_save_ms = 250.0;   // KV Cache 保存到内存
    double vram_release_ms = 100.0;    // 显存释放
    double cpu_load_ms = 1500.0;       // CPU 实例加载
    double restore_ms = 2000.0;        // 回迁 GPU
    double service_gap_ms = 300.0;     // 服务中断

    /// 下行迁移总耗时（GPU→CPU）
    double totalDownlinkMs() const {
        return kv_cache_save_ms + vram_release_ms + cpu_load_ms;
    }

    /// 往返迁移总耗时（GPU→CPU→GPU）
    double totalRoundTripMs() const {
        return totalDownlinkMs() + restore_ms;
    }
};

/// 迁移决策结果
struct MigrationDecision {
    bool should_migrate = false;
    std::string reason;
    double predicted_burst_duration_s = 0.0;
    MigrationCost migration_cost;
    double wait_cost_s = 0.0;     // 不迁移的等待代价
    double benefit_s = 0.0;       // 迁移收益 = wait_cost - migration_cost
    std::string strategy;         // "bypass" / "migrate" / "wait"
};

/// GPU 租约类型
enum class LeaseType {
    RESIDENT,  // 常驻租约（LLM）
    BURST,     // 短期租约（Image/VLM）
    SHARED     // 共享租约
};

/// GPU 租约
struct GPULease {
    std::string holder;
    PhaseRole holder_role = PhaseRole::BURST_GPU_PINNED;
    LeaseType lease_type = LeaseType::BURST;
    bool preemptible = false;
    double duration_pred_s = 0.0;
    size_t vram_required_mb = 0;
};

// ============================================================
// LLM 状态机
// ============================================================

/// LLM 状态：跟踪 LLM 在 GPU/CPU 之间的迁移
class LLMState {
public:
    LLMState()
        : level_(LLMServiceLevel::GPU_NORMAL)
        , current_device_("gpu")
        , migration_count_(0)
        , total_degraded_time_s_(0.0)
        , last_degraded_start_(0.0) {}

    /// 进入降级状态（GPU→CPU）
    void enterDegraded() {
        level_ = LLMServiceLevel::CPU_DEGRADED;
        current_device_ = "cpu";
        last_degraded_start_ = nowSeconds();
        migration_count_++;
    }

    /// 进入回迁状态（CPU→GPU）
    /// 回迁期间 LLM 仍处于"非 GPU 正常"状态，在此累加降级时间
    void enterRestoring() {
        if (level_ == LLMServiceLevel::CPU_DEGRADED && last_degraded_start_ > 0) {
            total_degraded_time_s_ += nowSeconds() - last_degraded_start_;
            last_degraded_start_ = 0.0;
        }
        level_ = LLMServiceLevel::RESTORING;
    }

    /// 恢复正常状态
    void enterNormal() {
        // 兜底：如果没经过 RESTORING 直接回 NORMAL
        if (level_ == LLMServiceLevel::CPU_DEGRADED && last_degraded_start_ > 0) {
            total_degraded_time_s_ += nowSeconds() - last_degraded_start_;
            last_degraded_start_ = 0.0;
        }
        level_ = LLMServiceLevel::GPU_NORMAL;
        current_device_ = "gpu";
    }

    // Getters
    LLMServiceLevel level() const { return level_; }
    const std::string& currentDevice() const { return current_device_; }
    size_t migrationCount() const { return migration_count_; }
    double totalDegradedTimeS() const { return total_degraded_time_s_; }

private:
    static double nowSeconds() {
        auto now = std::chrono::steady_clock::now();
        return std::chrono::duration<double>(now.time_since_epoch()).count();
    }

    LLMServiceLevel level_;
    std::string current_device_;
    size_t migration_count_;
    double total_degraded_time_s_;
    double last_degraded_start_;
};

// ============================================================
// Phase-Aware 决策引擎
// ============================================================

/// Phase-Aware 迁移决策引擎接口
class IPhaseDecisionEngine {
public:
    virtual ~IPhaseDecisionEngine() = default;

    /// 决策：是否迁移 LLM 到 CPU
    virtual MigrationDecision decide(
        const PhaseAttributes& burst_attrs,
        const LLMState& llm_state,
        size_t queue_depth = 0,
        double llm_remaining_work_s = 0.0) = 0;

    /// 决策统计
    struct DecisionStats {
        size_t total_decisions = 0;
        size_t migrate_count = 0;
        size_t bypass_count = 0;
        size_t wait_count = 0;
    };

    virtual DecisionStats getDecisionStats() const = 0;
    virtual void resetStats() = 0;
};

/// Cost-Aware 决策引擎（v2 策略）
class CostAwareDecisionEngine : public IPhaseDecisionEngine {
public:
    CostAwareDecisionEngine(
        const MigrationCost& cost = MigrationCost(),
        double short_burst_threshold_s = 2.0,
        double benefit_threshold_s = 0.1,
        size_t queue_pressure_threshold = 2)
        : migration_cost_(cost)
        , short_burst_threshold_s_(short_burst_threshold_s)
        , benefit_threshold_s_(benefit_threshold_s)
        , queue_pressure_threshold_(queue_pressure_threshold) {}

    MigrationDecision decide(
        const PhaseAttributes& burst_attrs,
        const LLMState& llm_state,
        size_t queue_depth = 0,
        double llm_remaining_work_s = 0.0) override;

    DecisionStats getDecisionStats() const override {
        return stats_;
    }

    void resetStats() override {
        stats_ = DecisionStats{};
    }

private:
    MigrationCost migration_cost_;
    double short_burst_threshold_s_;
    double benefit_threshold_s_;
    size_t queue_pressure_threshold_;
    mutable DecisionStats stats_;
};

/// Always-Migrate 决策引擎（v1 baseline）
class AlwaysMigrateDecisionEngine : public IPhaseDecisionEngine {
public:
    AlwaysMigrateDecisionEngine(const MigrationCost& cost = MigrationCost())
        : migration_cost_(cost) {}

    MigrationDecision decide(
        const PhaseAttributes& burst_attrs,
        const LLMState& llm_state,
        size_t queue_depth = 0,
        double llm_remaining_work_s = 0.0) override;

    DecisionStats getDecisionStats() const override {
        return stats_;
    }

    void resetStats() override {
        stats_ = DecisionStats{};
    }

private:
    MigrationCost migration_cost_;
    mutable DecisionStats stats_;
};

// ============================================================
// GPU 租约管理器
// ============================================================

/// GPU 租约管理器：管理显存预算和租约分配
class GPULeaseManager {
public:
    explicit GPULeaseManager(size_t vram_total_mb = 8192)
        : vram_total_mb_(vram_total_mb), vram_used_mb_(0) {}

    /// 检查是否可以获取租约
    bool canAcquire(const GPULease& lease) const {
        return vram_used_mb_ + lease.vram_required_mb <= vram_total_mb_;
    }

    /// 获取租约
    bool acquire(const GPULease& lease) {
        if (!canAcquire(lease)) return false;
        vram_used_mb_ += lease.vram_required_mb;
        leases_[lease.holder] = lease;
        return true;
    }

    /// 释放租约
    bool release(const std::string& holder) {
        auto it = leases_.find(holder);
        if (it == leases_.end()) return false;
        vram_used_mb_ -= it->second.vram_required_mb;
        leases_.erase(it);
        return true;
    }

    /// 降级常驻租约（释放显存但保留记录）
    bool downgradeResident(const std::string& holder) {
        auto it = leases_.find(holder);
        if (it == leases_.end()) return false;
        vram_used_mb_ -= it->second.vram_required_mb;
        it->second.vram_required_mb = 0;
        return true;
    }

    /// 恢复常驻租约
    bool restoreResident(const std::string& holder, size_t vram_mb) {
        auto it = leases_.find(holder);
        if (it == leases_.end()) return false;
        if (vram_used_mb_ + vram_mb > vram_total_mb_) return false;
        vram_used_mb_ += vram_mb;
        it->second.vram_required_mb = vram_mb;
        return true;
    }

    // Getters
    size_t vramTotalMb() const { return vram_total_mb_; }
    size_t vramUsedMb() const { return vram_used_mb_; }
    size_t vramAvailableMb() const { return vram_total_mb_ - vram_used_mb_; }

private:
    size_t vram_total_mb_;
    size_t vram_used_mb_;
    std::unordered_map<std::string, GPULease> leases_;
};

// ============================================================
// Phase-Aware 调度器配置
// ============================================================

/// Phase-Aware 调度器配置
struct PhaseAwareConfig {
    SchedulerPolicy policy = SchedulerPolicy::V2_PHASE_AWARE;
    MigrationPolicy migration_policy = MigrationPolicy::COST_AWARE;
    size_t vram_total_mb = 8192;
    size_t max_concurrent_cpu = 2;
    MigrationCost migration_cost;
    double short_burst_threshold_s = 2.0;
    double benefit_threshold_s = 0.1;
    size_t queue_pressure_threshold = 2;
};

// ============================================================
// Phase-Aware 调度策略（注入到 ResourceIsolationScheduler）
// ============================================================

/// Phase-Aware 调度策略接口
/// 注入到 ResourceIsolationScheduler，替换硬编码的 selectWorker 逻辑
class IPhaseAwareStrategy {
public:
    virtual ~IPhaseAwareStrategy() = default;

    /// 提交任务前的路由决策
    /// 返回目标设备："gpu_burst" / "cpu_backfill" / "resident_gpu" / "sequential"
    virtual std::string routeTask(
        const PhaseAttributes& attrs,
        const LLMState& llm_state,
        SchedulerPolicy policy) = 0;

    /// 选择 Worker（替换 ResourceIsolationScheduler::selectWorker）
    virtual std::shared_ptr<class IWorker> selectWorkerForPhase(
        const PhaseAttributes& attrs,
        const std::vector<std::shared_ptr<class IWorker>>& gpu_workers,
        const std::vector<std::shared_ptr<class IWorker>>& cpu_workers,
        const std::shared_ptr<class IWorker>& llm_worker) = 0;

    /// 是否应该迁移 LLM
    virtual MigrationDecision shouldMigrateLLM(
        const PhaseAttributes& burst_attrs,
        const LLMState& llm_state,
        size_t queue_depth = 0) = 0;

    /// 获取当前 LLM 状态
    virtual const LLMState& getLLMState() const = 0;

    /// 获取租约管理器
    virtual GPULeaseManager& getLeaseManager() = 0;

    /// 迁移 LLM 到 CPU
    virtual bool migrateLLMToCPU(bool urgent = false) = 0;

    /// 恢复 LLM 到 GPU
    virtual bool restoreLLMToGPU() = 0;

    /// 设置迁移回调
    virtual void setMigrationCallbacks(
        std::function<bool(bool urgent)> migrate_fn,
        std::function<bool()> restore_fn) = 0;
};

/// Phase-Aware 策略默认实现
class DefaultPhaseAwareStrategy : public IPhaseAwareStrategy {
public:
    explicit DefaultPhaseAwareStrategy(const PhaseAwareConfig& config = PhaseAwareConfig());

    std::string routeTask(
        const PhaseAttributes& attrs,
        const LLMState& llm_state,
        SchedulerPolicy policy) override;

    std::shared_ptr<IWorker> selectWorkerForPhase(
        const PhaseAttributes& attrs,
        const std::vector<std::shared_ptr<IWorker>>& gpu_workers,
        const std::vector<std::shared_ptr<IWorker>>& cpu_workers,
        const std::shared_ptr<IWorker>& llm_worker) override;

    MigrationDecision shouldMigrateLLM(
        const PhaseAttributes& burst_attrs,
        const LLMState& llm_state,
        size_t queue_depth = 0) override;

    const LLMState& getLLMState() const override { return llm_state_; }
    GPULeaseManager& getLeaseManager() override { return lease_manager_; }

    /// 迁移 LLM 到 CPU（需要外部注入实际迁移逻辑）
    void setMigrationCallbacks(
        std::function<bool(bool urgent)> migrate_fn,
        std::function<bool()> restore_fn) override {
        migrate_fn_ = std::move(migrate_fn);
        restore_fn_ = std::move(restore_fn);
    }

    /// 执行迁移
    bool migrateLLMToCPU(bool urgent = false) override;
    bool restoreLLMToGPU() override;

private:
    PhaseAwareConfig config_;
    LLMState llm_state_;
    GPULeaseManager lease_manager_;
    std::unique_ptr<IPhaseDecisionEngine> decision_engine_;
    std::function<bool(bool urgent)> migrate_fn_;
    std::function<bool()> restore_fn_;
};

// ============================================================
// Phase 预设（与 Python 层 PHASE_PRESETS 对齐）
// ============================================================

/// 获取预设阶段属性
PhaseAttributes getPhasePreset(const std::string& phase_name);

/// 判断阶段是否是 CPU 亲和的
inline bool isCpuAffine(DeviceAffinity affinity) {
    return affinity == DeviceAffinity::CPU_ONLY || affinity == DeviceAffinity::CPU_PREFERRED;
}

/// 判断阶段是否需要 GPU
inline bool needsGpu(DeviceAffinity affinity) {
    return affinity == DeviceAffinity::GPU_REQUIRED || affinity == DeviceAffinity::GPU_PREFERRED;
}

} // namespace ai_scheduler
