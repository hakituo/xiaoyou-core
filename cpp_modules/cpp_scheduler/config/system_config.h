#ifndef SYSTEM_CONFIG_H
#define SYSTEM_CONFIG_H

#include <string>
#include <unordered_map>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>

namespace ai_scheduler::config {

// 工作器类型枚举
enum class WorkerType {
    GPU_LLM,       // GPU LLM工作器
    CPU_TTS,       // CPU TTS工作器
    GPU_IMAGE,     // GPU图像生成工作器
    UNKNOWN
};

// 工作器配置
enum class WorkerConfigKey {
    // 通用配置
    ENABLED,           // 是否启用
    MAX_THREADS,       // 最大线程数
    MIN_THREADS,       // 最小线程数
    QUEUE_CAPACITY,    // 队列容量
    BATCH_SIZE,        // 批处理大小
    MAX_BATCH_SIZE,    // 最大批处理大小
    MIN_BATCH_SIZE,    // 最小批处理大小
    BATCH_TIMEOUT_MS,  // 批处理超时时间(毫秒)
    MAX_CONCURRENT_TASKS, // 最大并发任务数
    
    // GPU特定配置
    GPU_ID,            // GPU设备ID
    MAX_GPU_MEMORY_MB, // 最大GPU内存使用(MB)
    GPU_UTIL_THRESHOLD, // GPU利用率阈值
    
    // CPU特定配置
    CPU_AFFINITY,      // CPU亲和性
    CPU_PRIORITY,      // CPU优先级
    
    // LLM特定配置
    LLM_MODEL_PATH,    // 模型路径
    LLM_CONTEXT_SIZE,  // 上下文大小
    LLM_TEMPERATURE,   // 温度参数
    LLM_MAX_TOKENS,    // 最大生成令牌数
    
    // TTS特定配置
    TTS_MODEL_PATH,    // TTS模型路径
    TTS_VOICE,         // 语音选择
    TTS_SAMPLE_RATE,   // 采样率
    TTS_SPEED,         // 语速
    TTS_PITCH,         // 音调
    
    // 图像生成特定配置
    IMAGE_MODEL_PATH,  // 图像模型路径
    IMAGE_DEFAULT_WIDTH, // 默认图像宽度
    IMAGE_DEFAULT_HEIGHT, // 默认图像高度
    IMAGE_STEPS,       // 生成步数
    IMAGE_GUIDANCE_SCALE, // 引导尺度
    
    // 资源限制
    MAX_MEMORY_MB,     // 最大内存使用(MB)
    MAX_CPU_USAGE_PERCENT, // 最大CPU使用率(%)
    
    // 高级配置
    ENABLE_CACHING,    // 是否启用缓存
    CACHE_SIZE_MB,     // 缓存大小(MB)
    LOG_LEVEL,         // 日志级别
    METRICS_COLLECTION_INTERVAL_MS // 指标收集间隔
};

// API服务器配置
enum class APIServerConfigKey {
    ENABLED,           // 是否启用API服务器
    PORT,              // 服务器端口
    HOST,              // 主机地址
    MAX_CONNECTIONS,   // 最大连接数
    CONNECTION_TIMEOUT_MS, // 连接超时时间
    ENABLE_SSL,        // 是否启用SSL
    SSL_CERT_PATH,     // SSL证书路径
    SSL_KEY_PATH,      // SSL密钥路径
    ENABLE_COMPRESSION, // 是否启用压缩
    MAX_REQUEST_SIZE_MB, // 最大请求大小
    RATE_LIMIT_PER_SECOND, // 每秒请求限制
};

// 监控配置
enum class MonitoringConfigKey {
    ENABLED,           // 是否启用监控
    COLLECTION_INTERVAL_MS, // 收集间隔(毫秒)
    ENABLE_CPU_MONITORING, // 是否监控CPU
    ENABLE_GPU_MONITORING, // 是否监控GPU
    ENABLE_MEMORY_MONITORING, // 是否监控内存
    ENABLE_DISK_MONITORING, // 是否监控磁盘
    ENABLE_NETWORK_MONITORING, // 是否监控网络
    METRICS_EXPORT_PORT, // 指标导出端口
    ENABLE_PROMETHEUS_EXPORT, // 是否启用Prometheus导出
    ALERT_THRESHOLD_CPU, // CPU警告阈值
    ALERT_THRESHOLD_GPU, // GPU警告阈值
    ALERT_THRESHOLD_MEMORY, // 内存警告阈值
};

// 优化配置
enum class OptimizationConfigKey {
    ENABLED,           // 是否启用优化
    STRATEGY,          // 优化策略
    AUTO_TUNE_THREADS, // 是否自动调整线程数
    AUTO_TUNE_BATCH_SIZE, // 是否自动调整批处理大小
    ENABLE_MEMORY_OPTIMIZATION, // 是否启用内存优化
    ENABLE_TASK_PRIORITIZATION, // 是否启用任务优先级
    ENABLE_BATCHING,   // 是否启用批处理
    OPTIMIZATION_INTERVAL_MS, // 优化间隔(毫秒)
};

// 日志级别
enum class LogLevel {
    TRACE,
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    FATAL
};

// 配置值类型
class ConfigValue {
public:
    // 构造函数 - 字符串类型
    ConfigValue(const std::string& value);
    
    // 构造函数 - 整数类型
    ConfigValue(int64_t value);
    
    // 构造函数 - 浮点数类型
    ConfigValue(double value);
    
    // 构造函数 - 布尔类型
    ConfigValue(bool value);
    
    // 默认构造函数
    ConfigValue();
    
    // 获取字符串值
    std::string asString() const;
    
    // 获取整数值
    int64_t asInt() const;
    
    // 获取浮点数
    double asDouble() const;
    
    // 获取布尔值
    bool asBool() const;
    
    // 判断值是否有效
    bool isValid() const;
    
    // 等于运算符
    bool operator==(const ConfigValue& other) const;
    
    // 不等于运算符
    bool operator!=(const ConfigValue& other) const;
    
private:
    // 值的类型
    enum class Type {
        STRING,
        INTEGER,
        DOUBLE,
        BOOLEAN,
        NONE
    } type_;
    
    // 值存储
    std::string string_value_;
    int64_t int_value_;
    double double_value_;
    bool bool_value_;
};

// 系统配置管理器
class SystemConfig {
public:
    // 获取单例实例
    static std::shared_ptr<SystemConfig> getInstance();
    
    // 析构函数
    virtual ~SystemConfig();
    
    // 初始化配置
    bool initialize(const std::string& config_file = "");
    
    // 从文件加载配置
    bool loadFromFile(const std::string& config_file);
    
    // 从JSON字符串加载配置
    bool loadFromJson(const std::string& json_string);
    
    // 保存配置到文件
    bool saveToFile(const std::string& config_file) const;
    
    // 导出配置为JSON字符串
    std::string exportToJson() const;
    
    // 设置工作器配置
    void setWorkerConfig(WorkerType worker_type, WorkerConfigKey key, const ConfigValue& value);
    
    // 获取工作器配置
    ConfigValue getWorkerConfig(WorkerType worker_type, WorkerConfigKey key, 
                              const ConfigValue& default_value = ConfigValue()) const;
    
    // 设置API服务器配置
    void setAPIServerConfig(APIServerConfigKey key, const ConfigValue& value);
    
    // 获取API服务器配置
    ConfigValue getAPIServerConfig(APIServerConfigKey key, 
                                 const ConfigValue& default_value = ConfigValue()) const;
    
    // 设置监控配置
    void setMonitoringConfig(MonitoringConfigKey key, const ConfigValue& value);
    
    // 获取监控配置
    ConfigValue getMonitoringConfig(MonitoringConfigKey key, 
                                  const ConfigValue& default_value = ConfigValue()) const;
    
    // 设置优化配置
    void setOptimizationConfig(OptimizationConfigKey key, const ConfigValue& value);
    
    // 获取优化配置
    ConfigValue getOptimizationConfig(OptimizationConfigKey key, 
                                    const ConfigValue& default_value = ConfigValue()) const;
    
    // 设置全局配置
    void setGlobalConfig(const std::string& key, const ConfigValue& value);
    
    // 获取全局配置
    ConfigValue getGlobalConfig(const std::string& key, 
                              const ConfigValue& default_value = ConfigValue()) const;
    
    // 重置为默认配置
    void resetToDefaults();
    
    // 验证配置有效性
    bool validate() const;
    
    // 检查配置是否已初始化
    bool isInitialized() const;
    
    // 获取所有配置键
    std::vector<std::string> getAllConfigKeys() const;
    
    // 注册配置更改监听器
    using ConfigChangeListener = std::function<void(const std::string&, const ConfigValue&)>;
    void registerConfigChangeListener(ConfigChangeListener listener);
    
    // 通知配置更改
    void notifyConfigChanged(const std::string& key, const ConfigValue& value);
    
private:
    // 私有构造函数
    SystemConfig();
    
    // 初始化默认配置
    void initializeDefaults();
    
    // 配置存储
    std::unordered_map<WorkerType, std::unordered_map<WorkerConfigKey, ConfigValue>> worker_configs_;
    std::unordered_map<APIServerConfigKey, ConfigValue> api_server_configs_;
    std::unordered_map<MonitoringConfigKey, ConfigValue> monitoring_configs_;
    std::unordered_map<OptimizationConfigKey, ConfigValue> optimization_configs_;
    std::unordered_map<std::string, ConfigValue> global_configs_;
    
    // 配置更改监听器
    std::vector<ConfigChangeListener> config_change_listeners_;
    
    // 状态标志
    std::atomic<bool> initialized_;
    
    // 互斥锁
    mutable std::mutex config_mutex_;
    mutable std::mutex listener_mutex_;
    
    // 单例实例
    static std::shared_ptr<SystemConfig> instance_;
    static std::mutex instance_mutex_;
};

// 配置助手类 - 提供便捷的配置访问接口
class ConfigHelper {
public:
    // 获取工作器启用状态
    static bool isWorkerEnabled(WorkerType worker_type);
    
    // 获取工作器最大线程数
    static int getWorkerMaxThreads(WorkerType worker_type);
    
    // 获取工作器最小线程数
    static int getWorkerMinThreads(WorkerType worker_type);
    
    // 获取工作器队列容量
    static int getWorkerQueueCapacity(WorkerType worker_type);
    
    // 获取工作器批处理大小
    static int getWorkerBatchSize(WorkerType worker_type);
    
    // 获取GPU ID
    static int getWorkerGpuId(WorkerType worker_type);
    
    // 获取日志级别
    static LogLevel getLogLevel();
    
    // 设置日志级别
    static void setLogLevel(LogLevel level);
    
    // 获取API服务器端口
    static int getApiServerPort();
    
    // 获取API服务器主机
    static std::string getApiServerHost();
    
    // 检查是否启用监控
    static bool isMonitoringEnabled();
    
    // 获取指标收集间隔
    static int getMetricsCollectionInterval();
    
    // 检查是否启用优化
    static bool isOptimizationEnabled();
    
    // 获取优化策略
    static std::string getOptimizationStrategy();
    
    // 动态调整工作器配置
    static bool adjustWorkerConfig(WorkerType worker_type, 
                                 WorkerConfigKey key, 
                                 const ConfigValue& value);
    
    // 应用性能优化建议
    static bool applyPerformanceSuggestions(const std::vector<std::string>& suggestions);
    
    // 生成默认配置文件
    static bool generateDefaultConfigFile(const std::string& file_path);
};

} // namespace ai_scheduler::config

#endif // SYSTEM_CONFIG_H