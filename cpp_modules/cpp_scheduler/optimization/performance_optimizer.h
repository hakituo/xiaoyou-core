#ifndef PERFORMANCE_OPTIMIZER_H
#define PERFORMANCE_OPTIMIZER_H

#include "../monitoring/resource_monitor.h"
#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <vector>
#include <unordered_map>

namespace ai_scheduler::optimization {

// 优化策略枚举
enum class OptimizationStrategy {
    BALANCED,         // 平衡性能和资源使用
    PERFORMANCE_FIRST, // 优先考虑性能
    ENERGY_SAVING,     // 优先考虑节能
    RESPONSE_TIME,     // 优先考虑响应时间
    THROUGHPUT         // 优先考虑吞吐量
};

// 批处理配置
enum class BatchingPolicy {
    DYNAMIC,           // 动态批处理大小
    FIXED,             // 固定批处理大小
    ADAPTIVE           // 自适应批处理（根据负载调整）
};

// 线程池优化配置
struct ThreadPoolConfig {
    int min_threads;             // 最小线程数
    int max_threads;             // 最大线程数
    int thread_increment;        // 线程增量
    float cpu_threshold_high;    // CPU高阈值（触发增加线程）
    float cpu_threshold_low;     // CPU低阈值（触发减少线程）
    int adjustment_interval_ms;  // 调整间隔（毫秒）
    bool enable_hyperthreading;  // 是否启用超线程
};

// 批处理配置
struct BatchingConfig {
    BatchingPolicy policy;       // 批处理策略
    int min_batch_size;          // 最小批处理大小
    int max_batch_size;          // 最大批处理大小
    int default_batch_size;      // 默认批处理大小
    int batch_timeout_ms;        // 批处理超时时间
    float utilization_threshold; // 利用率阈值（用于自适应批处理）
};

// 内存缓存配置
struct CacheConfig {
    size_t max_cache_size_mb;    // 最大缓存大小（MB）
    size_t item_ttl_ms;          // 缓存项生存时间
    float eviction_threshold;    // 缓存驱逐阈值
    bool enable_compression;     // 是否启用压缩
};

// 任务优先级配置
enum class TaskPriority {
    CRITICAL,    // 关键任务
    HIGH,        // 高优先级
    MEDIUM,      // 中等优先级
    LOW,         // 低优先级
    BACKGROUND   // 后台任务
};

// 任务调度优化器接口
class ITaskSchedulerOptimizer {
public:
    virtual ~ITaskSchedulerOptimizer() = default;
    
    // 优化任务调度策略
    virtual void optimizeScheduling(const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 获取推荐的线程池大小
    virtual int getOptimalThreadCount(const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 获取任务优先级建议
    virtual TaskPriority getTaskPriority(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 检查是否需要限流
    virtual bool shouldThrottleRequests(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 获取负载平衡建议
    virtual std::unordered_map<std::string, float> getLoadBalancingWeights() = 0;
};

// 批处理优化器接口
class IBatchingOptimizer {
public:
    virtual ~IBatchingOptimizer() = default;
    
    // 获取最优批处理大小
    virtual int getOptimalBatchSize(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 检查是否应该合并任务
    virtual bool shouldMergeTasks(const std::vector<std::string>& task_types, const monitoring::PerformanceMetrics& metrics) = 0;
    
    // 更新批处理策略
    virtual void updateBatchingPolicy(const BatchingConfig& config) = 0;
    
    // 获取当前批处理统计信息
    virtual std::unordered_map<std::string, int> getBatchingStatistics() = 0;
};

// 内存优化器接口
class IMemoryOptimizer {
public:
    virtual ~IMemoryOptimizer() = default;
    
    // 优化内存分配
    virtual void optimizeMemoryAllocation(size_t requested_size, void** ptr) = 0;
    
    // 释放优化后的内存
    virtual void freeOptimizedMemory(void* ptr) = 0;
    
    // 获取内存使用统计
    virtual monitoring::PerformanceMetrics getMemoryStatistics() = 0;
    
    // 设置内存限制
    virtual void setMemoryLimits(size_t max_usage_mb) = 0;
};

// 主要的性能优化管理器
class PerformanceOptimizationManager {
public:
    // 创建优化管理器实例
    static std::shared_ptr<PerformanceOptimizationManager> create();
    
    // 析构函数
    virtual ~PerformanceOptimizationManager();
    
    // 初始化优化管理器
    bool initialize(OptimizationStrategy strategy = OptimizationStrategy::BALANCED);
    
    // 关闭优化管理器
    void shutdown();
    
    // 设置优化策略
    void setOptimizationStrategy(OptimizationStrategy strategy);
    
    // 获取当前优化策略
    OptimizationStrategy getOptimizationStrategy() const;
    
    // 更新线程池配置
    void updateThreadPoolConfig(const ThreadPoolConfig& config);
    
    // 更新批处理配置
    void updateBatchingConfig(const BatchingConfig& config);
    
    // 更新缓存配置
    void updateCacheConfig(const CacheConfig& config);
    
    // 执行全局优化
    void optimize(const monitoring::PerformanceMetrics& metrics);
    
    // 获取优化建议
    std::vector<std::string> getOptimizationSuggestions(const monitoring::PerformanceMetrics& metrics);
    
    // 注册任务调度优化器
    void registerTaskSchedulerOptimizer(std::shared_ptr<ITaskSchedulerOptimizer> optimizer);
    
    // 注册批处理优化器
    void registerBatchingOptimizer(std::shared_ptr<IBatchingOptimizer> optimizer);
    
    // 注册内存优化器
    void registerMemoryOptimizer(std::shared_ptr<IMemoryOptimizer> optimizer);
    
    // 获取线程池优化器
    std::shared_ptr<ITaskSchedulerOptimizer> getTaskSchedulerOptimizer() const;
    
    // 获取批处理优化器
    std::shared_ptr<IBatchingOptimizer> getBatchingOptimizer() const;
    
    // 获取内存优化器
    std::shared_ptr<IMemoryOptimizer> getMemoryOptimizer() const;
    
    // 动态调整资源分配
    bool adjustResourceAllocation(const monitoring::PerformanceMetrics& metrics);
    
    // 预测资源需求
    struct ResourcePrediction {
        int optimal_threads;
        int optimal_batch_size;
        size_t memory_requirement_mb;
        float cpu_reserve_percent;
        float gpu_reserve_percent;
    };
    
    ResourcePrediction predictResourceNeeds(int estimated_tasks_per_second);
    
    // 检查系统瓶颈
    std::string identifyBottleneck(const monitoring::PerformanceMetrics& metrics);
    
    // 获取优化统计信息
    std::unordered_map<std::string, double> getOptimizationStatistics() const;
    
    // 启用/禁用特定优化
    void setOptimizationEnabled(const std::string& optimization_name, bool enabled);
    
    // 检查优化是否启用
    bool isOptimizationEnabled(const std::string& optimization_name) const;
    
    // 保存优化配置到文件
    bool saveConfiguration(const std::string& filename) const;
    
    // 从文件加载优化配置
    bool loadConfiguration(const std::string& filename);
    
private:
    // 私有构造函数
    PerformanceOptimizationManager();
    
    // 根据策略调整参数
    void adjustParametersForStrategy(OptimizationStrategy strategy);
    
    // 优化线程池
    void optimizeThreadPool(const monitoring::PerformanceMetrics& metrics);
    
    // 优化批处理
    void optimizeBatching(const monitoring::PerformanceMetrics& metrics);
    
    // 优化内存使用
    void optimizeMemory(const monitoring::PerformanceMetrics& metrics);
    
    // 优化任务优先级
    void optimizeTaskPriorities(const monitoring::PerformanceMetrics& metrics);
    
    // 优化负载平衡
    void optimizeLoadBalancing(const monitoring::PerformanceMetrics& metrics);
    
    // 优化器组件
    std::shared_ptr<ITaskSchedulerOptimizer> task_scheduler_optimizer_;
    std::shared_ptr<IBatchingOptimizer> batching_optimizer_;
    std::shared_ptr<IMemoryOptimizer> memory_optimizer_;
    
    // 配置参数
    ThreadPoolConfig thread_pool_config_;
    BatchingConfig batching_config_;
    CacheConfig cache_config_;
    
    // 优化策略
    OptimizationStrategy current_strategy_;
    
    // 优化开关
    std::unordered_map<std::string, bool> optimizations_enabled_;
    
    // 统计信息
    std::unordered_map<std::string, double> optimization_stats_;
    
    // 上次优化时间
    std::chrono::steady_clock::time_point last_optimization_time_;
    
    // 优化间隔
    int optimization_interval_ms_;
    
    // 互斥锁
    mutable std::mutex config_mutex_;
};

// 具体的任务调度优化器实现
class DefaultTaskSchedulerOptimizer : public ITaskSchedulerOptimizer {
public:
    DefaultTaskSchedulerOptimizer();
    ~DefaultTaskSchedulerOptimizer() override;
    
    void optimizeScheduling(const monitoring::PerformanceMetrics& metrics) override;
    int getOptimalThreadCount(const monitoring::PerformanceMetrics& metrics) override;
    TaskPriority getTaskPriority(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) override;
    bool shouldThrottleRequests(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) override;
    std::unordered_map<std::string, float> getLoadBalancingWeights() override;
    
    // 设置线程池配置
    void setThreadPoolConfig(const ThreadPoolConfig& config);
    
    // 设置优先级权重
    void setPriorityWeights(const std::unordered_map<std::string, float>& weights);
    
private:
    ThreadPoolConfig config_;
    std::unordered_map<std::string, float> task_priority_weights_;
    std::unordered_map<std::string, int> previous_queue_sizes_;
    std::chrono::steady_clock::time_point last_adjustment_time_;
};

// 具体的批处理优化器实现
class AdaptiveBatchingOptimizer : public IBatchingOptimizer {
public:
    AdaptiveBatchingOptimizer();
    ~AdaptiveBatchingOptimizer() override;
    
    int getOptimalBatchSize(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) override;
    bool shouldMergeTasks(const std::vector<std::string>& task_types, const monitoring::PerformanceMetrics& metrics) override;
    void updateBatchingPolicy(const BatchingConfig& config) override;
    std::unordered_map<std::string, int> getBatchingStatistics() override;
    
    // 记录批处理执行结果
    void recordBatchExecution(const std::string& task_type, int batch_size, double execution_time);
    
private:
    BatchingConfig config_;
    
    // 批处理性能历史
    struct BatchHistory {
        int count;
        double total_time;
        int min_batch_size;
        int max_batch_size;
        std::vector<std::pair<int, double>> history; // (batch_size, execution_time)
    };
    
    std::unordered_map<std::string, BatchHistory> batch_histories_;
    std::unordered_map<std::string, int> current_batch_sizes_;
    
    // 计算最佳批处理大小
    int calculateOptimalBatchSize(const std::string& task_type, const monitoring::PerformanceMetrics& metrics);
};

// 内存池优化器实现
class MemoryPoolOptimizer : public IMemoryOptimizer {
public:
    MemoryPoolOptimizer();
    ~MemoryPoolOptimizer() override;
    
    void optimizeMemoryAllocation(size_t requested_size, void** ptr) override;
    void freeOptimizedMemory(void* ptr) override;
    monitoring::PerformanceMetrics getMemoryStatistics() override;
    void setMemoryLimits(size_t max_usage_mb) override;
    
    // 预分配内存池
    bool preallocateMemory(size_t size_mb);
    
    // 清理未使用的内存
    void cleanUnusedMemory();
    
private:
    // 内存块结构
    struct MemoryBlock {
        void* ptr;
        size_t size;
        bool in_use;
        std::chrono::steady_clock::time_point allocation_time;
    };
    
    // 内存池
    std::vector<MemoryBlock> memory_pool_;
    
    // 内存块大小分类
    std::unordered_map<size_t, std::vector<MemoryBlock*>> free_blocks_;
    
    // 配置和统计
    CacheConfig config_;
    size_t total_allocated_;
    size_t peak_usage_;
    int allocation_count_;
    int free_count_;
    int pool_hit_count_;
    int pool_miss_count_;
    
    // 互斥锁
    std::mutex pool_mutex_;
    
    // 查找合适的空闲块
    MemoryBlock* findFreeBlock(size_t size);
    
    // 创建新的内存块
    MemoryBlock* createNewBlock(size_t size);
    
    // 驱逐旧的内存块
    void evictOldBlocks();
};

// 性能优化宏定义
#define OPTIMIZE_TASK(task_type, metrics) \
    auto __optimizer = ai_scheduler::optimization::PerformanceOptimizationManager::create(); \
    auto __priority = __optimizer->getTaskSchedulerOptimizer()->getTaskPriority(task_type, metrics); \
    bool __should_throttle = __optimizer->getTaskSchedulerOptimizer()->shouldThrottleRequests(task_type, metrics); \
    if (__should_throttle) { /* 实现限流逻辑 */ }

#define OPTIMIZE_BATCH(task_type, metrics, batch_size) \
    auto __batching_optimizer = ai_scheduler::optimization::PerformanceOptimizationManager::create()->getBatchingOptimizer(); \
    batch_size = __batching_optimizer->getOptimalBatchSize(task_type, metrics);

#define OPTIMIZE_MEMORY(size, ptr) \
    auto __memory_optimizer = ai_scheduler::optimization::PerformanceOptimizationManager::create()->getMemoryOptimizer(); \
    __memory_optimizer->optimizeMemoryAllocation(size, &ptr); \
    auto __cleanup = [__memory_optimizer, &ptr]() { \
        if (ptr) __memory_optimizer->freeOptimizedMemory(ptr); \
    };

} // namespace ai_scheduler::optimization

#endif // PERFORMANCE_OPTIMIZER_H