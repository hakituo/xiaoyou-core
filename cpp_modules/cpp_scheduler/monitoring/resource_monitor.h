#ifndef RESOURCE_MONITOR_H
#define RESOURCE_MONITOR_H

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <vector>
#include <mutex>
#include <functional>

namespace ai_scheduler::monitoring {

// 系统资源使用情况结构体
enum class MonitorLevel {
    BASIC,     // 基本监控（CPU/GPU使用率）
    EXTENDED,  // 扩展监控（内存、线程、任务统计）
    DETAILED   // 详细监控（所有指标，包括延迟、队列状态）
};

// 性能指标结构体
struct PerformanceMetrics {
    // 系统资源指标
    std::atomic<float> cpu_utilization{0.0f};          // CPU使用率（%）
    std::atomic<float> gpu_utilization{0.0f};          // GPU使用率（%）
    std::atomic<size_t> memory_usage{0};               // 内存使用量（MB）
    std::atomic<size_t> gpu_memory_usage{0};           // GPU内存使用量（MB）
    std::atomic<int> active_threads{0};                // 活跃线程数
    
    // 任务性能指标
    std::atomic<uint64_t> llm_request_count{0};        // LLM请求总数
    std::atomic<uint64_t> tts_request_count{0};        // TTS请求总数
    std::atomic<uint64_t> image_request_count{0};      // 图像生成请求总数
    std::atomic<uint64_t> llm_success_count{0};        // LLM成功请求数
    std::atomic<uint64_t> tts_success_count{0};        // TTS成功请求数
    std::atomic<uint64_t> image_success_count{0};      // 图像生成成功请求数
    std::atomic<uint64_t> llm_total_time{0};           // LLM总处理时间（ms）
    std::atomic<uint64_t> tts_total_time{0};           // TTS总处理时间（ms）
    std::atomic<uint64_t> image_total_time{0};         // 图像生成总处理时间（ms）
    
    // 队列指标
    std::atomic<int> llm_queue_size{0};                // LLM队列大小
    std::atomic<int> tts_queue_size{0};                // TTS队列大小
    std::atomic<int> image_queue_size{0};              // 图像生成队列大小
    std::atomic<int> max_llm_queue_size{0};            // 最大LLM队列大小
    std::atomic<int> max_tts_queue_size{0};            // 最大TTS队列大小
    std::atomic<int> max_image_queue_size{0};          // 最大图像生成队列大小
    
    // 错误指标
    std::atomic<uint64_t> llm_error_count{0};          // LLM错误计数
    std::atomic<uint64_t> tts_error_count{0};          // TTS错误计数
    std::atomic<uint64_t> image_error_count{0};        // 图像生成错误计数
    std::atomic<uint64_t> timeout_count{0};            // 超时计数
    
    // 资源限制指标
    std::atomic<bool> cpu_throttled{false};            // CPU是否被节流
    std::atomic<bool> gpu_throttled{false};            // GPU是否被节流
    std::atomic<bool> memory_pressure{false};          // 是否有内存压力
};

// 监控事件回调类型
typedef std::function<void(const std::string& event_name, const PerformanceMetrics& metrics)> MonitorCallback;

// 资源监控类
class ResourceMonitor {
public:
    // 创建监控器实例（单例模式）
    static std::shared_ptr<ResourceMonitor> getInstance();
    
    // 析构函数
    ~ResourceMonitor();
    
    // 初始化监控器
    bool initialize(MonitorLevel level = MonitorLevel::EXTENDED, int interval_ms = 1000);
    
    // 关闭监控器
    void shutdown();
    
    // 开始监控
    bool start();
    
    // 停止监控
    void stop();
    
    // 获取当前性能指标
    PerformanceMetrics getCurrentMetrics() const;
    
    // 重置性能指标
    void resetMetrics();
    
    // 注册监控回调（当指标超过阈值时触发）
    void registerCallback(const std::string& metric_name, float threshold, 
                         MonitorCallback callback, bool once = false);
    
    // 注销监控回调
    void unregisterCallback(const std::string& metric_name);
    
    // 更新任务性能指标
    void updateTaskMetrics(const std::string& task_type, bool success, uint64_t processing_time);
    
    // 更新队列指标
    void updateQueueMetrics(const std::string& queue_type, int current_size);
    
    // 获取性能报告（JSON格式）
    std::string getPerformanceReport() const;
    
    // 导出性能数据到文件
    bool exportMetricsToFile(const std::string& filename) const;
    
    // 设置监控级别
    void setMonitorLevel(MonitorLevel level);
    
    // 获取监控级别
    MonitorLevel getMonitorLevel() const;
    
    // 是否正在运行
    bool isRunning() const;
    
    // 获取运行时间
    uint64_t getUptime() const;
    
    // 检查系统是否健康
    bool isSystemHealthy() const;
    
    // 获取健康报告
    std::string getHealthReport() const;
    
private:
    // 私有构造函数（单例模式）
    ResourceMonitor();
    
    // 监控线程函数
    void monitorThreadFunc();
    
    // 收集系统资源信息
    void collectSystemMetrics();
    
    // 检查阈值并触发回调
    void checkThresholds();
    
    // 收集CPU使用率
    float collectCPUUtilization();
    
    // 收集GPU使用率（如果可用）
    float collectGPUUtilization();
    
    // 收集内存使用情况
    size_t collectMemoryUsage();
    
    // 收集GPU内存使用情况（如果可用）
    size_t collectGPUMemoryUsage();
    
    // 检查资源限制
    void checkResourceLimits();
    
    // 计算平均值、最大值等统计信息
    void calculateStatistics();
    
    // 监控配置
    MonitorLevel monitor_level_;
    int monitor_interval_ms_;
    std::atomic<bool> running_;
    std::unique_ptr<std::thread> monitor_thread_;
    
    // 性能指标
    PerformanceMetrics metrics_;
    mutable std::mutex metrics_mutex_;
    
    // 回调管理
    struct CallbackInfo {
        MonitorCallback callback;
        float threshold;
        bool once;
        bool triggered;
    };
    
    std::map<std::string, CallbackInfo> callbacks_;
    mutable std::mutex callbacks_mutex_;
    
    // 运行时间
    std::chrono::steady_clock::time_point start_time_;
    
    // 历史性能数据（用于趋势分析）
    struct MetricsSnapshot {
        PerformanceMetrics metrics;
        std::chrono::steady_clock::time_point timestamp;
    };
    
    std::vector<MetricsSnapshot> history_;
    mutable std::mutex history_mutex_;
    const size_t max_history_size_ = 100; // 保存最近100个快照
    
    // 静态实例指针
    static std::shared_ptr<ResourceMonitor> instance_;
    static std::mutex instance_mutex_;
};

// 性能优化辅助类
class PerformanceOptimizer {
public:
    // 创建优化器实例
    static std::shared_ptr<PerformanceOptimizer> create();
    
    // 析构函数
    virtual ~PerformanceOptimizer();
    
    // 根据当前负载调整线程池大小
    int optimizeThreadPoolSize(int current_size, const PerformanceMetrics& metrics);
    
    // 优化GPU内存使用
    bool optimizeGPUMemory(size_t current_usage, size_t max_usage);
    
    // 调整任务优先级策略
    void adjustTaskPriorities(const PerformanceMetrics& metrics);
    
    // 预测资源需求
    struct ResourcePrediction {
        float predicted_cpu_usage;
        float predicted_gpu_usage;
        size_t predicted_memory_usage;
        int recommended_threads;
    };
    
    ResourcePrediction predictResourceNeeds(int estimated_tasks_per_second);
    
    // 获取优化建议
    std::vector<std::string> getOptimizationSuggestions(const PerformanceMetrics& metrics);
    
    // 动态调整监控级别
    MonitorLevel suggestMonitorLevel(const PerformanceMetrics& metrics);
    
    // 检查是否需要资源扩展
    bool shouldScaleResources(const PerformanceMetrics& metrics);
    
    // 估算任务完成时间
    uint64_t estimateTaskCompletionTime(const std::string& task_type, const PerformanceMetrics& metrics);
    
private:
    // 私有构造函数
    PerformanceOptimizer();
    
    // 历史负载数据
    std::vector<float> cpu_usage_history_;
    std::vector<float> gpu_usage_history_;
    std::mutex history_mutex_;
    
    // 优化配置参数
    float cpu_threshold_high_ = 85.0f;
    float cpu_threshold_low_ = 30.0f;
    float gpu_threshold_high_ = 90.0f;
    float gpu_threshold_low_ = 40.0f;
    float memory_threshold_ = 80.0f;
    int min_threads_ = 2;
    int max_threads_ = 32;
};

// 性能监控宏定义，方便在代码中使用
#define MONITOR_TASK_START(task_type) \
    auto __task_start_time = std::chrono::high_resolution_clock::now();

#define MONITOR_TASK_END(task_type, success) \
    auto __task_end_time = std::chrono::high_resolution_clock::now(); \
    auto __task_duration = std::chrono::duration_cast<std::chrono::milliseconds>(__task_end_time - __task_start_time).count(); \
    ai_scheduler::monitoring::ResourceMonitor::getInstance()->updateTaskMetrics(task_type, success, __task_duration);

#define MONITOR_QUEUE_SIZE(queue_type, size) \
    ai_scheduler::monitoring::ResourceMonitor::getInstance()->updateQueueMetrics(queue_type, size);

#define MONITOR_CHECK_HEALTH() \
    ai_scheduler::monitoring::ResourceMonitor::getInstance()->isSystemHealthy()

} // namespace ai_scheduler::monitoring

#endif // RESOURCE_MONITOR_H