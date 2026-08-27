#include "performance_optimizer.h"
#include "../monitoring/resource_monitor.h"
#include <fstream>
#include <thread>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <sstream>

namespace ai_scheduler::optimization {

// PerformanceOptimizationManager 实现
std::shared_ptr<PerformanceOptimizationManager> PerformanceOptimizationManager::create() {
    return std::shared_ptr<PerformanceOptimizationManager>(new PerformanceOptimizationManager());
}

PerformanceOptimizationManager::PerformanceOptimizationManager() 
    : current_strategy_(OptimizationStrategy::BALANCED),
      optimization_interval_ms_(5000),
      last_optimization_time_(std::chrono::steady_clock::now()) {
    
    // 设置默认配置
    thread_pool_config_.min_threads = 4;
    thread_pool_config_.max_threads = 16;
    thread_pool_config_.thread_increment = 2;
    thread_pool_config_.cpu_threshold_high = 0.85f;
    thread_pool_config_.cpu_threshold_low = 0.4f;
    thread_pool_config_.adjustment_interval_ms = 5000;
    thread_pool_config_.enable_hyperthreading = true;
    
    batching_config_.policy = BatchingPolicy::DYNAMIC;
    batching_config_.min_batch_size = 1;
    batching_config_.max_batch_size = 32;
    batching_config_.default_batch_size = 8;
    batching_config_.batch_timeout_ms = 100;
    batching_config_.utilization_threshold = 0.7f;
    
    cache_config_.max_cache_size_mb = 512;
    cache_config_.item_ttl_ms = 30000;
    cache_config_.eviction_threshold = 0.9f;
    cache_config_.enable_compression = false;
    
    // 启用所有优化
    optimizations_enabled_["thread_pool"] = true;
    optimizations_enabled_["batching"] = true;
    optimizations_enabled_["memory"] = true;
    optimizations_enabled_["task_priorities"] = true;
    optimizations_enabled_["load_balancing"] = true;
    
    // 创建默认优化器
    task_scheduler_optimizer_ = std::make_shared<DefaultTaskSchedulerOptimizer>();
    batching_optimizer_ = std::make_shared<AdaptiveBatchingOptimizer>();
    memory_optimizer_ = std::make_shared<MemoryPoolOptimizer>();
}

PerformanceOptimizationManager::~PerformanceOptimizationManager() {
    shutdown();
}

bool PerformanceOptimizationManager::initialize(OptimizationStrategy strategy) {
    try {
        current_strategy_ = strategy;
        adjustParametersForStrategy(strategy);
        
        // 初始化各个优化器
        if (task_scheduler_optimizer_) {
            auto scheduler_optimizer = std::dynamic_pointer_cast<DefaultTaskSchedulerOptimizer>(task_scheduler_optimizer_);
            if (scheduler_optimizer) {
                scheduler_optimizer->setThreadPoolConfig(thread_pool_config_);
            }
        }
        
        if (batching_optimizer_) {
            auto batching = std::dynamic_pointer_cast<AdaptiveBatchingOptimizer>(batching_optimizer_);
            if (batching) {
                batching->updateBatchingPolicy(batching_config_);
            }
        }
        
        if (memory_optimizer_) {
            memory_optimizer_->setMemoryLimits(cache_config_.max_cache_size_mb);
        }
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "PerformanceOptimizationManager initialization failed: " << e.what() << std::endl;
        return false;
    }
}

void PerformanceOptimizationManager::shutdown() {
    // 清理资源
    if (memory_optimizer_) {
        auto memory_pool = std::dynamic_pointer_cast<MemoryPoolOptimizer>(memory_optimizer_);
        if (memory_pool) {
            memory_pool->cleanUnusedMemory();
        }
    }
    
    // 重置优化器指针
    task_scheduler_optimizer_.reset();
    batching_optimizer_.reset();
    memory_optimizer_.reset();
}

void PerformanceOptimizationManager::setOptimizationStrategy(OptimizationStrategy strategy) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    current_strategy_ = strategy;
    adjustParametersForStrategy(strategy);
}

OptimizationStrategy PerformanceOptimizationManager::getOptimizationStrategy() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    return current_strategy_;
}

void PerformanceOptimizationManager::updateThreadPoolConfig(const ThreadPoolConfig& config) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    thread_pool_config_ = config;
    
    if (task_scheduler_optimizer_) {
        auto scheduler_optimizer = std::dynamic_pointer_cast<DefaultTaskSchedulerOptimizer>(task_scheduler_optimizer_);
        if (scheduler_optimizer) {
            scheduler_optimizer->setThreadPoolConfig(config);
        }
    }
}

void PerformanceOptimizationManager::updateBatchingConfig(const BatchingConfig& config) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    batching_config_ = config;
    
    if (batching_optimizer_) {
        batching_optimizer_->updateBatchingPolicy(config);
    }
}

void PerformanceOptimizationManager::updateCacheConfig(const CacheConfig& config) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    cache_config_ = config;
    
    if (memory_optimizer_) {
        memory_optimizer_->setMemoryLimits(config.max_cache_size_mb);
    }
}

void PerformanceOptimizationManager::optimize(const monitoring::PerformanceMetrics& metrics) {
    auto now = std::chrono::steady_clock::now();
    auto time_since_last = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_optimization_time_).count();
    
    // 检查是否需要优化（避免过于频繁）
    if (time_since_last < optimization_interval_ms_) {
        return;
    }
    
    last_optimization_time_ = now;
    
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    // 执行各种优化
    if (optimizations_enabled_.count("thread_pool") && optimizations_enabled_["thread_pool"]) {
        optimizeThreadPool(metrics);
    }
    
    if (optimizations_enabled_.count("batching") && optimizations_enabled_["batching"]) {
        optimizeBatching(metrics);
    }
    
    if (optimizations_enabled_.count("memory") && optimizations_enabled_["memory"]) {
        optimizeMemory(metrics);
    }
    
    if (optimizations_enabled_.count("task_priorities") && optimizations_enabled_["task_priorities"]) {
        optimizeTaskPriorities(metrics);
    }
    
    if (optimizations_enabled_.count("load_balancing") && optimizations_enabled_["load_balancing"]) {
        optimizeLoadBalancing(metrics);
    }
}

std::vector<std::string> PerformanceOptimizationManager::getOptimizationSuggestions(const monitoring::PerformanceMetrics& metrics) {
    std::vector<std::string> suggestions;
    
    // 基于系统指标生成优化建议
    if (metrics.cpu_utilization > 0.9f) {
        suggestions.push_back("警告: CPU使用率过高 (>90%)，建议增加线程池大小或启用任务限流");
    }
    
    if (metrics.gpu_utilization > 0.9f) {
        suggestions.push_back("警告: GPU使用率过高 (>90%)，建议优化GPU任务批处理或减少并发GPU任务");
    }
    
    if (metrics.memory_usage_mb > metrics.memory_limit_mb * 0.9f) {
        suggestions.push_back("警告: 内存使用率过高 (>90%)，建议增加缓存清理频率或调整内存限制");
    }
    
    if (metrics.avg_task_queue_time_ms > 1000) {
        suggestions.push_back("警告: 任务队列平均等待时间过长 (>1000ms)，建议增加工作线程或优化任务处理逻辑");
    }
    
    if (metrics.task_error_rate > 0.05f) {
        suggestions.push_back("警告: 任务错误率过高 (>5%)，建议检查任务处理逻辑和资源分配");
    }
    
    // 针对不同worker的建议
    if (metrics.worker_metrics.count("gpu_llm") && metrics.worker_metrics["gpu_llm"].queue_length > 10) {
        suggestions.push_back("建议: LLM任务队列过长，考虑增加LLM批处理大小或优化模型推理速度");
    }
    
    if (metrics.worker_metrics.count("gpu_image") && metrics.worker_metrics["gpu_image"].queue_length > 5) {
        suggestions.push_back("建议: 图像生成任务队列过长，考虑延长批处理超时时间或增加批处理大小");
    }
    
    if (metrics.worker_metrics.count("cpu_tts") && metrics.worker_metrics["cpu_tts"].queue_length > 20) {
        suggestions.push_back("建议: TTS任务队列过长，考虑增加CPU工作线程数量");
    }
    
    return suggestions;
}

void PerformanceOptimizationManager::registerTaskSchedulerOptimizer(std::shared_ptr<ITaskSchedulerOptimizer> optimizer) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    task_scheduler_optimizer_ = optimizer;
}

void PerformanceOptimizationManager::registerBatchingOptimizer(std::shared_ptr<IBatchingOptimizer> optimizer) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    batching_optimizer_ = optimizer;
}

void PerformanceOptimizationManager::registerMemoryOptimizer(std::shared_ptr<IMemoryOptimizer> optimizer) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    memory_optimizer_ = optimizer;
}

std::shared_ptr<ITaskSchedulerOptimizer> PerformanceOptimizationManager::getTaskSchedulerOptimizer() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    return task_scheduler_optimizer_;
}

std::shared_ptr<IBatchingOptimizer> PerformanceOptimizationManager::getBatchingOptimizer() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    return batching_optimizer_;
}

std::shared_ptr<IMemoryOptimizer> PerformanceOptimizationManager::getMemoryOptimizer() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    return memory_optimizer_;
}

bool PerformanceOptimizationManager::adjustResourceAllocation(const monitoring::PerformanceMetrics& metrics) {
    try {
        if (!task_scheduler_optimizer_) {
            return false;
        }
        
        // 动态调整线程池大小
        int optimal_threads = task_scheduler_optimizer_->getOptimalThreadCount(metrics);
        ThreadPoolConfig new_config = thread_pool_config_;
        
        // 根据最优线程数调整配置
        if (optimal_threads > new_config.max_threads) {
            new_config.max_threads = optimal_threads;
        }
        
        // 如果线程数需要大幅调整，更新配置
        if (std::abs(optimal_threads - new_config.min_threads) > 4) {
            new_config.min_threads = std::max(2, optimal_threads - 2);
            updateThreadPoolConfig(new_config);
        }
        
        // 调整批处理配置
        if (batching_optimizer_ && metrics.system_load > 0.8f) {
            // 高负载时增加批处理大小
            BatchingConfig new_batch_config = batching_config_;
            new_batch_config.default_batch_size = std::min(new_batch_config.max_batch_size, 
                                                          new_batch_config.default_batch_size + 2);
            updateBatchingConfig(new_batch_config);
        } else if (batching_optimizer_ && metrics.system_load < 0.3f) {
            // 低负载时减少批处理大小以提高响应速度
            BatchingConfig new_batch_config = batching_config_;
            new_batch_config.default_batch_size = std::max(new_batch_config.min_batch_size, 
                                                          new_batch_config.default_batch_size - 1);
            updateBatchingConfig(new_batch_config);
        }
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Resource allocation adjustment failed: " << e.what() << std::endl;
        return false;
    }
}

PerformanceOptimizationManager::ResourcePrediction PerformanceOptimizationManager::predictResourceNeeds(int estimated_tasks_per_second) {
    ResourcePrediction prediction;
    
    // 基于任务每秒数量预测资源需求
    int cores = std::thread::hardware_concurrency();
    
    // 预测线程数（考虑任务特性和硬件核心数）
    prediction.optimal_threads = std::min(cores * 2, 
                                         std::max(4, estimated_tasks_per_second / 5 + 2));
    
    // 预测批处理大小
    prediction.optimal_batch_size = std::min(32, std::max(1, estimated_tasks_per_second / 20));
    
    // 预测内存需求（假设每个任务平均需要50MB）
    prediction.memory_requirement_mb = estimated_tasks_per_second * 50;
    
    // CPU和GPU预留百分比
    prediction.cpu_reserve_percent = 0.1f;  // 预留10% CPU
    prediction.gpu_reserve_percent = 0.2f;  // 预留20% GPU用于系统操作
    
    return prediction;
}

std::string PerformanceOptimizationManager::identifyBottleneck(const monitoring::PerformanceMetrics& metrics) {
    // 检查各个资源的瓶颈
    if (metrics.cpu_utilization > 0.9f) {
        return "CPU 是系统瓶颈 (使用率: " + std::to_string(metrics.cpu_utilization * 100) + "%)";
    }
    
    if (metrics.gpu_utilization > 0.9f) {
        return "GPU 是系统瓶颈 (使用率: " + std::to_string(metrics.gpu_utilization * 100) + "%)";
    }
    
    if (metrics.memory_usage_mb > metrics.memory_limit_mb * 0.9f) {
        return "内存是系统瓶颈 (使用率: " + std::to_string(metrics.memory_usage_mb * 100 / metrics.memory_limit_mb) + "%)";
    }
    
    // 检查I/O瓶颈
    if (metrics.disk_io_utilization > 0.8f) {
        return "磁盘I/O是系统瓶颈 (使用率: " + std::to_string(metrics.disk_io_utilization * 100) + "%)";
    }
    
    // 检查网络瓶颈
    if (metrics.network_io_utilization > 0.8f) {
        return "网络I/O是系统瓶颈 (使用率: " + std::to_string(metrics.network_io_utilization * 100) + "%)";
    }
    
    // 检查队列等待时间
    if (metrics.avg_task_queue_time_ms > 2000) {
        return "任务队列等待时间过长是系统瓶颈 (" + std::to_string(metrics.avg_task_queue_time_ms) + "ms)";
    }
    
    return "未检测到明显瓶颈 (系统负载: " + std::to_string(metrics.system_load) + ")";
}

std::unordered_map<std::string, double> PerformanceOptimizationManager::getOptimizationStatistics() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    return optimization_stats_;
}

void PerformanceOptimizationManager::setOptimizationEnabled(const std::string& optimization_name, bool enabled) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    optimizations_enabled_[optimization_name] = enabled;
}

bool PerformanceOptimizationManager::isOptimizationEnabled(const std::string& optimization_name) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    auto it = optimizations_enabled_.find(optimization_name);
    return (it != optimizations_enabled_.end() && it->second);
}

bool PerformanceOptimizationManager::saveConfiguration(const std::string& filename) const {
    try {
        std::ofstream file(filename);
        if (!file.is_open()) {
            return false;
        }
        
        // 保存优化策略
        file << "strategy=" << static_cast<int>(current_strategy_) << std::endl;
        
        // 保存线程池配置
        file << "thread_pool.min_threads=" << thread_pool_config_.min_threads << std::endl;
        file << "thread_pool.max_threads=" << thread_pool_config_.max_threads << std::endl;
        file << "thread_pool.thread_increment=" << thread_pool_config_.thread_increment << std::endl;
        file << "thread_pool.cpu_threshold_high=" << thread_pool_config_.cpu_threshold_high << std::endl;
        file << "thread_pool.cpu_threshold_low=" << thread_pool_config_.cpu_threshold_low << std::endl;
        file << "thread_pool.adjustment_interval_ms=" << thread_pool_config_.adjustment_interval_ms << std::endl;
        file << "thread_pool.enable_hyperthreading=" << (thread_pool_config_.enable_hyperthreading ? "true" : "false") << std::endl;
        
        // 保存批处理配置
        file << "batching.policy=" << static_cast<int>(batching_config_.policy) << std::endl;
        file << "batching.min_batch_size=" << batching_config_.min_batch_size << std::endl;
        file << "batching.max_batch_size=" << batching_config_.max_batch_size << std::endl;
        file << "batching.default_batch_size=" << batching_config_.default_batch_size << std::endl;
        file << "batching.batch_timeout_ms=" << batching_config_.batch_timeout_ms << std::endl;
        file << "batching.utilization_threshold=" << batching_config_.utilization_threshold << std::endl;
        
        // 保存缓存配置
        file << "cache.max_cache_size_mb=" << cache_config_.max_cache_size_mb << std::endl;
        file << "cache.item_ttl_ms=" << cache_config_.item_ttl_ms << std::endl;
        file << "cache.eviction_threshold=" << cache_config_.eviction_threshold << std::endl;
        file << "cache.enable_compression=" << (cache_config_.enable_compression ? "true" : "false") << std::endl;
        
        // 保存优化开关状态
        for (const auto& [name, enabled] : optimizations_enabled_) {
            file << "optimization." << name << ".enabled=" << (enabled ? "true" : "false") << std::endl;
        }
        
        file.close();
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Failed to save configuration: " << e.what() << std::endl;
        return false;
    }
}

bool PerformanceOptimizationManager::loadConfiguration(const std::string& filename) {
    try {
        std::ifstream file(filename);
        if (!file.is_open()) {
            return false;
        }
        
        std::string line;
        while (std::getline(file, line)) {
            if (line.empty() || line[0] == '#') {
                continue; // 跳过空行和注释
            }
            
            size_t eq_pos = line.find('=');
            if (eq_pos == std::string::npos) {
                continue;
            }
            
            std::string key = line.substr(0, eq_pos);
            std::string value = line.substr(eq_pos + 1);
            
            // 解析配置项
            if (key == "strategy") {
                current_strategy_ = static_cast<OptimizationStrategy>(std::stoi(value));
            }
            // 解析线程池配置
            else if (key == "thread_pool.min_threads") thread_pool_config_.min_threads = std::stoi(value);
            else if (key == "thread_pool.max_threads") thread_pool_config_.max_threads = std::stoi(value);
            else if (key == "thread_pool.thread_increment") thread_pool_config_.thread_increment = std::stoi(value);
            else if (key == "thread_pool.cpu_threshold_high") thread_pool_config_.cpu_threshold_high = std::stof(value);
            else if (key == "thread_pool.cpu_threshold_low") thread_pool_config_.cpu_threshold_low = std::stof(value);
            else if (key == "thread_pool.adjustment_interval_ms") thread_pool_config_.adjustment_interval_ms = std::stoi(value);
            else if (key == "thread_pool.enable_hyperthreading") thread_pool_config_.enable_hyperthreading = (value == "true");
            
            // 解析批处理配置
            else if (key == "batching.policy") batching_config_.policy = static_cast<BatchingPolicy>(std::stoi(value));
            else if (key == "batching.min_batch_size") batching_config_.min_batch_size = std::stoi(value);
            else if (key == "batching.max_batch_size") batching_config_.max_batch_size = std::stoi(value);
            else if (key == "batching.default_batch_size") batching_config_.default_batch_size = std::stoi(value);
            else if (key == "batching.batch_timeout_ms") batching_config_.batch_timeout_ms = std::stoi(value);
            else if (key == "batching.utilization_threshold") batching_config_.utilization_threshold = std::stof(value);
            
            // 解析缓存配置
            else if (key == "cache.max_cache_size_mb") cache_config_.max_cache_size_mb = std::stoi(value);
            else if (key == "cache.item_ttl_ms") cache_config_.item_ttl_ms = std::stoi(value);
            else if (key == "cache.eviction_threshold") cache_config_.eviction_threshold = std::stof(value);
            else if (key == "cache.enable_compression") cache_config_.enable_compression = (value == "true");
            
            // 解析优化开关状态
            else if (key.substr(0, 13) == "optimization.") {
                size_t dot_pos = key.rfind('.');
                if (dot_pos != std::string::npos && key.substr(dot_pos + 1) == "enabled") {
                    std::string opt_name = key.substr(13, dot_pos - 13);
                    optimizations_enabled_[opt_name] = (value == "true");
                }
            }
        }
        
        file.close();
        
        // 应用新配置
        adjustParametersForStrategy(current_strategy_);
        
        if (task_scheduler_optimizer_) {
            auto scheduler_optimizer = std::dynamic_pointer_cast<DefaultTaskSchedulerOptimizer>(task_scheduler_optimizer_);
            if (scheduler_optimizer) {
                scheduler_optimizer->setThreadPoolConfig(thread_pool_config_);
            }
        }
        
        if (batching_optimizer_) {
            batching_optimizer_->updateBatchingPolicy(batching_config_);
        }
        
        if (memory_optimizer_) {
            memory_optimizer_->setMemoryLimits(cache_config_.max_cache_size_mb);
        }
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Failed to load configuration: " << e.what() << std::endl;
        return false;
    }
}

void PerformanceOptimizationManager::adjustParametersForStrategy(OptimizationStrategy strategy) {
    switch (strategy) {
        case OptimizationStrategy::PERFORMANCE_FIRST:
            // 性能优先策略：更多线程，更大批处理
            thread_pool_config_.min_threads = std::thread::hardware_concurrency();
            thread_pool_config_.max_threads = std::thread::hardware_concurrency() * 2;
            thread_pool_config_.cpu_threshold_high = 0.9f;
            batching_config_.default_batch_size = 16;
            batching_config_.batch_timeout_ms = 50;
            break;
            
        case OptimizationStrategy::ENERGY_SAVING:
            // 节能策略：更少线程，更小批处理
            thread_pool_config_.min_threads = 2;
            thread_pool_config_.max_threads = std::thread::hardware_concurrency() / 2;
            thread_pool_config_.cpu_threshold_high = 0.7f;
            batching_config_.default_batch_size = 4;
            batching_config_.batch_timeout_ms = 200;
            break;
            
        case OptimizationStrategy::RESPONSE_TIME:
            // 响应时间优先：小批处理，更多线程
            thread_pool_config_.min_threads = std::thread::hardware_concurrency();
            thread_pool_config_.max_threads = std::thread::hardware_concurrency() * 2;
            batching_config_.default_batch_size = 1;
            batching_config_.batch_timeout_ms = 10;
            break;
            
        case OptimizationStrategy::THROUGHPUT:
            // 吞吐量优先：大批量处理，更多线程
            thread_pool_config_.min_threads = std::thread::hardware_concurrency();
            thread_pool_config_.max_threads = std::thread::hardware_concurrency() * 2;
            batching_config_.default_batch_size = 32;
            batching_config_.batch_timeout_ms = 200;
            batching_config_.policy = BatchingPolicy::ADAPTIVE;
            break;
            
        case OptimizationStrategy::BALANCED:
        default:
            // 平衡策略
            thread_pool_config_.min_threads = std::thread::hardware_concurrency() / 2;
            thread_pool_config_.max_threads = std::thread::hardware_concurrency() * 1.5;
            thread_pool_config_.cpu_threshold_high = 0.85f;
            thread_pool_config_.cpu_threshold_low = 0.4f;
            batching_config_.default_batch_size = 8;
            batching_config_.batch_timeout_ms = 100;
            break;
    }
}

void PerformanceOptimizationManager::optimizeThreadPool(const monitoring::PerformanceMetrics& metrics) {
    if (!task_scheduler_optimizer_) {
        return;
    }
    
    task_scheduler_optimizer_->optimizeScheduling(metrics);
    
    // 更新统计信息
    optimization_stats_["thread_pool.optimization_count"]++;
    optimization_stats_["thread_pool.last_cpu_util"] = metrics.cpu_utilization;
}

void PerformanceOptimizationManager::optimizeBatching(const monitoring::PerformanceMetrics& metrics) {
    if (!batching_optimizer_) {
        return;
    }
    
    // 为不同类型的任务优化批处理
    std::vector<std::string> task_types = {"gpu_llm", "gpu_image", "cpu_tts"};
    
    for (const auto& task_type : task_types) {
        int optimal_batch = batching_optimizer_->getOptimalBatchSize(task_type, metrics);
        optimization_stats_["batching." + task_type + ".optimal_size"] = optimal_batch;
    }
    
    optimization_stats_["batching.optimization_count"]++;
}

void PerformanceOptimizationManager::optimizeMemory(const monitoring::PerformanceMetrics& metrics) {
    if (!memory_optimizer_) {
        return;
    }
    
    // 获取内存统计信息
    auto mem_stats = memory_optimizer_->getMemoryStatistics();
    
    // 如果内存使用过高，清理未使用的内存
    if (mem_stats.memory_usage_mb > cache_config_.max_cache_size_mb * 0.8f) {
        auto mem_pool = std::dynamic_pointer_cast<MemoryPoolOptimizer>(memory_optimizer_);
        if (mem_pool) {
            mem_pool->cleanUnusedMemory();
        }
    }
    
    optimization_stats_["memory.optimization_count"]++;
    optimization_stats_["memory.usage_mb"] = mem_stats.memory_usage_mb;
}

void PerformanceOptimizationManager::optimizeTaskPriorities(const monitoring::PerformanceMetrics& metrics) {
    // 这个方法主要依赖任务调度优化器来实现
    if (!task_scheduler_optimizer_) {
        return;
    }
    
    // 记录优先级调整次数
    optimization_stats_["task_priority.adjustment_count"]++;
}

void PerformanceOptimizationManager::optimizeLoadBalancing(const monitoring::PerformanceMetrics& metrics) {
    // 这个方法主要依赖任务调度优化器来实现
    if (!task_scheduler_optimizer_) {
        return;
    }
    
    // 获取负载平衡权重
    auto weights = task_scheduler_optimizer_->getLoadBalancingWeights();
    
    // 记录负载平衡统计信息
    for (const auto& [worker, weight] : weights) {
        optimization_stats_["load_balancing." + worker + ".weight"] = weight;
    }
    
    optimization_stats_["load_balancing.adjustment_count"]++;
}

// DefaultTaskSchedulerOptimizer 实现
DefaultTaskSchedulerOptimizer::DefaultTaskSchedulerOptimizer() {
    // 设置默认任务优先级权重
    task_priority_weights_["gpu_llm"] = 1.0f;     // LLM任务优先级最高
    task_priority_weights_["cpu_tts"] = 0.8f;     // TTS任务次之
    task_priority_weights_["gpu_image"] = 0.5f;   // 图像生成任务优先级较低
    
    last_adjustment_time_ = std::chrono::steady_clock::now();
}

DefaultTaskSchedulerOptimizer::~DefaultTaskSchedulerOptimizer() {
}

void DefaultTaskSchedulerOptimizer::optimizeScheduling(const monitoring::PerformanceMetrics& metrics) {
    // 检查是否需要调整线程数
    auto now = std::chrono::steady_clock::now();
    auto time_since_last = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_adjustment_time_).count();
    
    if (time_since_last >= config_.adjustment_interval_ms) {
        last_adjustment_time_ = now;
        
        // 更新队列大小历史记录
        for (const auto& [worker_name, worker_metrics] : metrics.worker_metrics) {
            previous_queue_sizes_[worker_name] = worker_metrics.queue_length;
        }
    }
}

int DefaultTaskSchedulerOptimizer::getOptimalThreadCount(const monitoring::PerformanceMetrics& metrics) {
    int cores = std::thread::hardware_concurrency();
    int optimal_threads = config_.min_threads;
    
    // 根据CPU使用率调整线程数
    if (metrics.cpu_utilization > config_.cpu_threshold_high) {
        // CPU使用率高，增加线程数
        optimal_threads = std::min(config_.max_threads, optimal_threads + config_.thread_increment);
    } else if (metrics.cpu_utilization < config_.cpu_threshold_low) {
        // CPU使用率低，减少线程数
        optimal_threads = std::max(config_.min_threads, optimal_threads - config_.thread_increment);
    }
    
    // 根据任务队列长度调整
    int total_queue_length = 0;
    for (const auto& [worker_name, worker_metrics] : metrics.worker_metrics) {
        total_queue_length += worker_metrics.queue_length;
    }
    
    // 如果队列长度超过线程数的3倍，考虑增加线程
    if (total_queue_length > optimal_threads * 3) {
        optimal_threads = std::min(config_.max_threads, optimal_threads + config_.thread_increment);
    }
    
    // 考虑超线程
    if (config_.enable_hyperthreading) {
        optimal_threads = std::min(optimal_threads, cores * 2);
    } else {
        optimal_threads = std::min(optimal_threads, cores);
    }
    
    return optimal_threads;
}

TaskPriority DefaultTaskSchedulerOptimizer::getTaskPriority(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) {
    // 基于任务类型和系统负载确定优先级
    float base_priority = task_priority_weights_[task_type];
    
    // 高负载时提高关键任务优先级
    if (metrics.system_load > 0.8f) {
        if (task_type == "gpu_llm") {
            return TaskPriority::CRITICAL;
        } else if (task_type == "cpu_tts") {
            return TaskPriority::HIGH;
        } else {
            return TaskPriority::MEDIUM;
        }
    }
    
    // 正常负载时的优先级
    if (base_priority >= 1.0f) {
        return TaskPriority::CRITICAL;
    } else if (base_priority >= 0.8f) {
        return TaskPriority::HIGH;
    } else if (base_priority >= 0.5f) {
        return TaskPriority::MEDIUM;
    } else {
        return TaskPriority::LOW;
    }
}

bool DefaultTaskSchedulerOptimizer::shouldThrottleRequests(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) {
    // 基于系统负载和队列长度决定是否限流
    
    // 高系统负载时考虑限流
    if (metrics.system_load > 0.9f) {
        // 只对非关键任务限流
        if (task_type != "gpu_llm") {
            return true;
        }
    }
    
    // 检查特定worker的队列长度
    if (metrics.worker_metrics.count(task_type)) {
        const auto& worker_metrics = metrics.worker_metrics.at(task_type);
        
        // 队列过长时限流
        if (worker_metrics.queue_length > 50) { // 队列超过50个任务时限流
            return true;
        }
        
        // 错误率过高时限流
        if (worker_metrics.error_rate > 0.1f) { // 错误率超过10%时限流
            return true;
        }
    }
    
    // 内存压力大时限流
    if (metrics.memory_usage_mb > metrics.memory_limit_mb * 0.9f) {
        return true;
    }
    
    return false;
}

std::unordered_map<std::string, float> DefaultTaskSchedulerOptimizer::getLoadBalancingWeights() {
    std::unordered_map<std::string, float> weights;
    
    // 基于任务类型设置负载均衡权重
    weights["gpu_llm"] = 0.5f;     // LLM任务获得50%的处理资源
    weights["cpu_tts"] = 0.3f;     // TTS任务获得30%的处理资源
    weights["gpu_image"] = 0.2f;   // 图像生成任务获得20%的处理资源
    
    return weights;
}

void DefaultTaskSchedulerOptimizer::setThreadPoolConfig(const ThreadPoolConfig& config) {
    config_ = config;
}

void DefaultTaskSchedulerOptimizer::setPriorityWeights(const std::unordered_map<std::string, float>& weights) {
    task_priority_weights_ = weights;
}

// AdaptiveBatchingOptimizer 实现
AdaptiveBatchingOptimizer::AdaptiveBatchingOptimizer() {
    // 初始化批处理历史记录
    batch_histories_["gpu_llm"] = {0, 0.0, 1, 32, {}};
    batch_histories_["cpu_tts"] = {0, 0.0, 1, 16, {}};
    batch_histories_["gpu_image"] = {0, 0.0, 1, 8, {}};
    
    // 设置默认批处理大小
    current_batch_sizes_["gpu_llm"] = 8;
    current_batch_sizes_["cpu_tts"] = 4;
    current_batch_sizes_["gpu_image"] = 2;
}

AdaptiveBatchingOptimizer::~AdaptiveBatchingOptimizer() {
}

int AdaptiveBatchingOptimizer::getOptimalBatchSize(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) {
    // 确保任务类型存在
    if (batch_histories_.find(task_type) == batch_histories_.end()) {
        batch_histories_[task_type] = {0, 0.0, 1, 16, {}};
    }
    
    // 计算最佳批处理大小
    int optimal_size = calculateOptimalBatchSize(task_type, metrics);
    
    // 更新当前批处理大小
    current_batch_sizes_[task_type] = optimal_size;
    
    return optimal_size;
}

bool AdaptiveBatchingOptimizer::shouldMergeTasks(const std::vector<std::string>& task_types, const monitoring::PerformanceMetrics& metrics) {
    // 只有当系统负载适中，且所有任务类型都兼容合并时，才考虑合并任务
    if (metrics.system_load < 0.3f || metrics.system_load > 0.8f) {
        return false; // 负载过低或过高时不合并
    }
    
    // 检查是否所有任务类型都是相同的
    if (task_types.size() < 2) {
        return false;
    }
    
    // 只合并相同类型的任务
    const std::string& first_type = task_types[0];
    for (const auto& type : task_types) {
        if (type != first_type) {
            return false;
        }
    }
    
    // 根据任务类型决定是否合并
    if (first_type == "gpu_llm" && metrics.gpu_utilization < 0.7f) {
        return true;
    } else if (first_type == "cpu_tts") {
        return true; // TTS任务总是可以合并
    } else if (first_type == "gpu_image" && metrics.gpu_utilization < 0.6f) {
        return true;
    }
    
    return false;
}

void AdaptiveBatchingOptimizer::updateBatchingPolicy(const BatchingConfig& config) {
    config_ = config;
    
    // 根据新配置更新批处理大小
    for (auto& [task_type, batch_size] : current_batch_sizes_) {
        batch_size = std::max(config.min_batch_size, 
                            std::min(config.max_batch_size, config.default_batch_size));
    }
}

std::unordered_map<std::string, int> AdaptiveBatchingOptimizer::getBatchingStatistics() {
    std::unordered_map<std::string, int> stats;
    
    // 返回当前批处理大小
    for (const auto& [task_type, batch_size] : current_batch_sizes_) {
        stats[task_type + ".current_batch_size"] = batch_size;
    }
    
    // 返回批处理执行次数
    for (const auto& [task_type, history] : batch_histories_) {
        stats[task_type + ".batch_count"] = history.count;
    }
    
    return stats;
}

void AdaptiveBatchingOptimizer::recordBatchExecution(const std::string& task_type, int batch_size, double execution_time) {
    // 确保任务类型存在
    if (batch_histories_.find(task_type) == batch_histories_.end()) {
        batch_histories_[task_type] = {0, 0.0, batch_size, batch_size, {}};
    }
    
    auto& history = batch_histories_[task_type];
    
    // 更新历史记录
    history.count++;
    history.total_time += execution_time;
    history.min_batch_size = std::min(history.min_batch_size, batch_size);
    history.max_batch_size = std::max(history.max_batch_size, batch_size);
    
    // 保存最近的执行记录（最多保存100条）
    history.history.push_back({batch_size, execution_time});
    if (history.history.size() > 100) {
        history.history.erase(history.history.begin());
    }
}

int AdaptiveBatchingOptimizer::calculateOptimalBatchSize(const std::string& task_type, const monitoring::PerformanceMetrics& metrics) {
    auto& history = batch_histories_[task_type];
    int optimal_size = config_.default_batch_size;
    
    switch (config_.policy) {
        case BatchingPolicy::FIXED:
            // 固定批处理大小
            optimal_size = config_.default_batch_size;
            break;
            
        case BatchingPolicy::ADAPTIVE:
            // 自适应批处理大小
            if (history.count > 0) {
                // 计算平均每个任务的执行时间
                double avg_time_per_task = history.total_time / (history.count * 
                                                             (history.total_time > 0 ? 
                                                              static_cast<double>(history.count) / history.total_time : 1.0));
                
                // 根据系统负载和执行时间调整批处理大小
                if (metrics.system_load > config_.utilization_threshold) {
                    // 高负载时增加批处理大小以提高吞吐量
                    optimal_size = std::min(config_.max_batch_size, 
                                          static_cast<int>(optimal_size * 1.2f));
                } else if (metrics.system_load < config_.utilization_threshold * 0.5f) {
                    // 低负载时减少批处理大小以提高响应速度
                    optimal_size = std::max(config_.min_batch_size, 
                                          static_cast<int>(optimal_size * 0.8f));
                }
                
                // 根据历史数据优化批处理大小
                if (!history.history.empty()) {
                    // 找出最高效的批处理大小（每个任务的平均执行时间最短）
                    double best_efficiency = std::numeric_limits<double>::max();
                    int best_batch_size = config_.default_batch_size;
                    
                    for (const auto& [size, time] : history.history) {
                        double efficiency = time / size; // 每个任务的执行时间
                        if (efficiency < best_efficiency) {
                            best_efficiency = efficiency;
                            best_batch_size = size;
                        }
                    }
                    
                    // 使用找出的最佳批处理大小，但保持在限制范围内
                    optimal_size = std::max(config_.min_batch_size, 
                                          std::min(config_.max_batch_size, best_batch_size));
                }
            }
            break;
            
        case BatchingPolicy::DYNAMIC:
        default:
            // 动态批处理大小（根据队列长度和系统负载）
            int queue_length = 0;
            if (metrics.worker_metrics.count(task_type)) {
                queue_length = metrics.worker_metrics.at(task_type).queue_length;
            }
            
            // 根据队列长度调整批处理大小
            if (queue_length > 20) {
                optimal_size = config_.max_batch_size;
            } else if (queue_length > 10) {
                optimal_size = static_cast<int>(config_.max_batch_size * 0.75f);
            } else if (queue_length > 5) {
                optimal_size = static_cast<int>(config_.max_batch_size * 0.5f);
            } else {
                optimal_size = config_.min_batch_size;
            }
            
            // 根据GPU/CPU使用情况进一步调整
            if (task_type == "gpu_llm" || task_type == "gpu_image") {
                if (metrics.gpu_utilization > 0.8f) {
                    optimal_size = std::min(optimal_size, config_.default_batch_size);
                }
            } else if (task_type == "cpu_tts") {
                if (metrics.cpu_utilization > 0.8f) {
                    optimal_size = std::min(optimal_size, config_.default_batch_size);
                }
            }
            break;
    }
    
    // 确保批处理大小在配置的范围内
    optimal_size = std::max(config_.min_batch_size, 
                          std::min(config_.max_batch_size, optimal_size));
    
    return optimal_size;
}

// MemoryPoolOptimizer 实现
MemoryPoolOptimizer::MemoryPoolOptimizer() 
    : total_allocated_(0),
      peak_usage_(0),
      allocation_count_(0),
      free_count_(0),
      pool_hit_count_(0),
      pool_miss_count_(0) {
    
    // 设置默认配置
    config_.max_cache_size_mb = 512;
    config_.item_ttl_ms = 30000;
    config_.eviction_threshold = 0.9f;
    config_.enable_compression = false;
}

MemoryPoolOptimizer::~MemoryPoolOptimizer() {
    // 释放所有内存块
    cleanUnusedMemory();
    for (auto& block : memory_pool_) {
        if (block.ptr) {
            free(block.ptr);
        }
    }
    memory_pool_.clear();
    free_blocks_.clear();
}

void MemoryPoolOptimizer::optimizeMemoryAllocation(size_t requested_size, void** ptr) {
    std::lock_guard<std::mutex> lock(pool_mutex_);
    
    // 确保指针为空
    if (*ptr) {
        free(*ptr);
        *ptr = nullptr;
    }
    
    allocation_count_++;
    
    // 查找合适的空闲块
    MemoryBlock* block = findFreeBlock(requested_size);
    
    if (block) {
        // 找到合适的块
        block->in_use = true;
        block->allocation_time = std::chrono::steady_clock::now();
        *ptr = block->ptr;
        pool_hit_count_++;
        
        // 从空闲块映射中移除
        if (free_blocks_.count(block->size)) {
            auto& blocks = free_blocks_[block->size];
            auto it = std::find(blocks.begin(), blocks.end(), block);
            if (it != blocks.end()) {
                blocks.erase(it);
            }
        }
    } else {
        // 没有找到合适的块，创建新块
        block = createNewBlock(requested_size);
        if (block) {
            *ptr = block->ptr;
            pool_miss_count_++;
        }
    }
    
    // 更新统计信息
    peak_usage_ = std::max(peak_usage_, total_allocated_);
}

void MemoryPoolOptimizer::freeOptimizedMemory(void* ptr) {
    if (!ptr) {
        return;
    }
    
    std::lock_guard<std::mutex> lock(pool_mutex_);
    
    // 查找对应的内存块
    auto it = std::find_if(memory_pool_.begin(), memory_pool_.end(),
                          [ptr](const MemoryBlock& block) { 
                              return block.ptr == ptr && block.in_use; 
                          });
    
    if (it != memory_pool_.end()) {
        // 标记为空闲
        it->in_use = false;
        free_count_++;
        
        // 添加到空闲块映射
        free_blocks_[it->size].push_back(&(*it));
    } else {
        // 不是通过内存池分配的，直接释放
        free(ptr);
    }
}

monitoring::PerformanceMetrics MemoryPoolOptimizer::getMemoryStatistics() {
    monitoring::PerformanceMetrics metrics;
    
    std::lock_guard<std::mutex> lock(pool_mutex_);
    
    metrics.memory_usage_mb = total_allocated_ / (1024 * 1024);
    metrics.memory_limit_mb = config_.max_cache_size_mb;
    
    // 添加自定义统计信息
    metrics.custom_metrics["memory_pool.allocation_count"] = allocation_count_;
    metrics.custom_metrics["memory_pool.free_count"] = free_count_;
    metrics.custom_metrics["memory_pool.hit_rate"] = pool_hit_count_ / 
                                                    std::max(1.0, pool_hit_count_ + pool_miss_count_);
    metrics.custom_metrics["memory_pool.peak_usage_mb"] = peak_usage_ / (1024 * 1024);
    metrics.custom_metrics["memory_pool.block_count"] = memory_pool_.size();
    
    int free_blocks_count = 0;
    for (const auto& [size, blocks] : free_blocks_) {
        free_blocks_count += blocks.size();
    }
    metrics.custom_metrics["memory_pool.free_blocks"] = free_blocks_count;
    
    return metrics;
}

void MemoryPoolOptimizer::setMemoryLimits(size_t max_usage_mb) {
    std::lock_guard<std::mutex> lock(pool_mutex_);
    config_.max_cache_size_mb = max_usage_mb;
    
    // 如果当前使用超过限制，尝试清理
    if (total_allocated_ > max_usage_mb * 1024 * 1024) {
        evictOldBlocks();
    }
}

bool MemoryPoolOptimizer::preallocateMemory(size_t size_mb) {
    try {
        std::lock_guard<std::mutex> lock(pool_mutex_);
        
        size_t size_bytes = size_mb * 1024 * 1024;
        
        // 预分配一系列不同大小的内存块
        std::vector<size_t> block_sizes = {64, 256, 1024, 4096, 16384, 65536, 262144, 1048576};
        
        for (size_t block_size : block_sizes) {
            // 计算可以分配的块数量
            int blocks_to_allocate = std::min(10, static_cast<int>(size_bytes / block_size / 8));
            
            for (int i = 0; i < blocks_to_allocate; i++) {
                createNewBlock(block_size);
            }
        }
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Failed to preallocate memory: " << e.what() << std::endl;
        return false;
    }
}

void MemoryPoolOptimizer::cleanUnusedMemory() {
    std::lock_guard<std::mutex> lock(pool_mutex_);
    
    // 清理所有未使用的内存块
    auto it = memory_pool_.begin();
    while (it != memory_pool_.end()) {
        if (!it->in_use) {
            free(it->ptr);
            total_allocated_ -= it->size;
            
            // 从空闲块映射中移除
            if (free_blocks_.count(it->size)) {
                auto& blocks = free_blocks_[it->size];
                blocks.erase(std::remove(blocks.begin(), blocks.end(), &(*it)), blocks.end());
            }
            
            it = memory_pool_.erase(it);
        } else {
            ++it;
        }
    }
}

MemoryPoolOptimizer::MemoryBlock* MemoryPoolOptimizer::findFreeBlock(size_t size) {
    // 首先查找精确匹配
    if (free_blocks_.count(size) && !free_blocks_[size].empty()) {
        return free_blocks_[size].back();
    }
    
    // 查找更大的块（首次适应算法）
    for (auto& [block_size, blocks] : free_blocks_) {
        if (block_size >= size && !blocks.empty()) {
            return blocks.back();
        }
    }
    
    return nullptr;
}

MemoryPoolOptimizer::MemoryBlock* MemoryPoolOptimizer::createNewBlock(size_t size) {
    // 检查内存限制
    size_t max_size_bytes = config_.max_cache_size_mb * 1024 * 1024;
    if (total_allocated_ + size > max_size_bytes) {
        // 尝试驱逐旧的内存块
        evictOldBlocks();
        
        // 再次检查
        if (total_allocated_ + size > max_size_bytes) {
            // 仍然超过限制，返回nullptr
            return nullptr;
        }
    }
    
    // 分配内存
    void* ptr = malloc(size);
    if (!ptr) {
        return nullptr;
    }
    
    // 创建新的内存块
    MemoryBlock block;
    block.ptr = ptr;
    block.size = size;
    block.in_use = true;
    block.allocation_time = std::chrono::steady_clock::now();
    
    // 添加到内存池
    memory_pool_.push_back(block);
    total_allocated_ += size;
    
    return &memory_pool_.back();
}

void MemoryPoolOptimizer::evictOldBlocks() {
    auto now = std::chrono::steady_clock::now();
    
    // 收集所有可以驱逐的块
    std::vector<MemoryBlock*> evict_candidates;
    
    for (auto& [size, blocks] : free_blocks_) {
        for (auto block : blocks) {
            auto age = std::chrono::duration_cast<std::chrono::milliseconds>(
                now - block->allocation_time).count();
            
            // 如果块的年龄超过TTL，可以驱逐
            if (age > config_.item_ttl_ms) {
                evict_candidates.push_back(block);
            }
        }
    }
    
    // 按照年龄排序（最老的先驱逐）
    std::sort(evict_candidates.begin(), evict_candidates.end(),
              [](MemoryBlock* a, MemoryBlock* b) {
                  return a->allocation_time < b->allocation_time;
              });
    
    // 驱逐块，直到内存使用降到阈值以下
    size_t target_usage = static_cast<size_t>(max_size_bytes * config_.eviction_threshold);
    for (auto block : evict_candidates) {
        if (total_allocated_ <= target_usage) {
            break;
        }
        
        // 从内存池和空闲块映射中移除
        free(block->ptr);
        total_allocated_ -= block->size;
        
        // 从空闲块映射中移除
        if (free_blocks_.count(block->size)) {
            auto& blocks = free_blocks_[block->size];
            blocks.erase(std::remove(blocks.begin(), blocks.end(), block), blocks.end());
        }
        
        // 从内存池中移除
        auto it = std::find_if(memory_pool_.begin(), memory_pool_.end(),
                              [block](const MemoryBlock& mb) { return &mb == block; });
        if (it != memory_pool_.end()) {
            memory_pool_.erase(it);
        }
    }
}

} // namespace ai_scheduler::optimization