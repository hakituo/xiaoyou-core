#include "resource_monitor.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <thread>
#include <algorithm>
#include <chrono>
#include <ctime>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#else
#include <sys/resource.h>
#include <sys/sysinfo.h>
#include <unistd.h>
#endif

namespace ai_scheduler::monitoring {

// 静态成员初始化
std::shared_ptr<ResourceMonitor> ResourceMonitor::instance_ = nullptr;
std::mutex ResourceMonitor::instance_mutex_;

ResourceMonitor::ResourceMonitor()
    : monitor_level_(MonitorLevel::EXTENDED),
      monitor_interval_ms_(1000),
      running_(false) {
    // 初始化开始时间
    start_time_ = std::chrono::steady_clock::now();
}

ResourceMonitor::~ResourceMonitor() {
    shutdown();
}

std::shared_ptr<ResourceMonitor> ResourceMonitor::getInstance() {
    std::lock_guard<std::mutex> lock(instance_mutex_);
    if (!instance_) {
        instance_ = std::shared_ptr<ResourceMonitor>(new ResourceMonitor());
    }
    return instance_;
}

bool ResourceMonitor::initialize(MonitorLevel level, int interval_ms) {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    
    monitor_level_ = level;
    monitor_interval_ms_ = std::max(interval_ms, 100); // 最小100ms
    
    // 重置指标
    resetMetrics();
    
    std::cout << "[ResourceMonitor] Initialized with level " << static_cast<int>(level) 
              << ", interval " << monitor_interval_ms_ << "ms" << std::endl;
    
    return true;
}

void ResourceMonitor::shutdown() {
    stop();
    
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    resetMetrics();
    
    std::lock_guard<std::mutex> lock_callbacks(callbacks_mutex_);
    callbacks_.clear();
    
    std::lock_guard<std::mutex> lock_history(history_mutex_);
    history_.clear();
    
    std::cout << "[ResourceMonitor] Shutdown completed" << std::endl;
}

bool ResourceMonitor::start() {
    if (running_) {
        std::cout << "[ResourceMonitor] Already running" << std::endl;
        return true;
    }
    
    running_ = true;
    monitor_thread_ = std::make_unique<std::thread>(&ResourceMonitor::monitorThreadFunc, this);
    
    std::cout << "[ResourceMonitor] Monitoring started" << std::endl;
    return true;
}

void ResourceMonitor::stop() {
    if (running_) {
        running_ = false;
        if (monitor_thread_ && monitor_thread_->joinable()) {
            monitor_thread_->join();
            monitor_thread_.reset();
        }
        std::cout << "[ResourceMonitor] Monitoring stopped" << std::endl;
    }
}

PerformanceMetrics ResourceMonitor::getCurrentMetrics() const {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    return metrics_;
}

void ResourceMonitor::resetMetrics() {
    // 重置所有原子指标
    metrics_.cpu_utilization = 0.0f;
    metrics_.gpu_utilization = 0.0f;
    metrics_.memory_usage = 0;
    metrics_.gpu_memory_usage = 0;
    metrics_.active_threads = 0;
    metrics_.llm_request_count = 0;
    metrics_.tts_request_count = 0;
    metrics_.image_request_count = 0;
    metrics_.llm_success_count = 0;
    metrics_.tts_success_count = 0;
    metrics_.image_success_count = 0;
    metrics_.llm_total_time = 0;
    metrics_.tts_total_time = 0;
    metrics_.image_total_time = 0;
    metrics_.llm_queue_size = 0;
    metrics_.tts_queue_size = 0;
    metrics_.image_queue_size = 0;
    metrics_.max_llm_queue_size = 0;
    metrics_.max_tts_queue_size = 0;
    metrics_.max_image_queue_size = 0;
    metrics_.llm_error_count = 0;
    metrics_.tts_error_count = 0;
    metrics_.image_error_count = 0;
    metrics_.timeout_count = 0;
    metrics_.cpu_throttled = false;
    metrics_.gpu_throttled = false;
    metrics_.memory_pressure = false;
}

void ResourceMonitor::registerCallback(const std::string& metric_name, float threshold, 
                                     MonitorCallback callback, bool once) {
    std::lock_guard<std::mutex> lock(callbacks_mutex_);
    
    CallbackInfo info;
    info.callback = callback;
    info.threshold = threshold;
    info.once = once;
    info.triggered = false;
    
    callbacks_[metric_name] = info;
    
    std::cout << "[ResourceMonitor] Registered callback for metric '" << metric_name 
              << "' with threshold " << threshold << std::endl;
}

void ResourceMonitor::unregisterCallback(const std::string& metric_name) {
    std::lock_guard<std::mutex> lock(callbacks_mutex_);
    auto it = callbacks_.find(metric_name);
    if (it != callbacks_.end()) {
        callbacks_.erase(it);
        std::cout << "[ResourceMonitor] Unregistered callback for metric '" << metric_name << "'" << std::endl;
    }
}

void ResourceMonitor::updateTaskMetrics(const std::string& task_type, bool success, uint64_t processing_time) {
    // 更新任务相关指标
    if (task_type == "llm" || task_type == "LLM_GPU") {
        metrics_.llm_request_count++;
        if (success) {
            metrics_.llm_success_count++;
            metrics_.llm_total_time += processing_time;
        } else {
            metrics_.llm_error_count++;
        }
    } else if (task_type == "tts" || task_type == "TTS_CPU") {
        metrics_.tts_request_count++;
        if (success) {
            metrics_.tts_success_count++;
            metrics_.tts_total_time += processing_time;
        } else {
            metrics_.tts_error_count++;
        }
    } else if (task_type == "image" || task_type == "IMAGE_GPU_QUEUE") {
        metrics_.image_request_count++;
        if (success) {
            metrics_.image_success_count++;
            metrics_.image_total_time += processing_time;
        } else {
            metrics_.image_error_count++;
        }
    }
}

void ResourceMonitor::updateQueueMetrics(const std::string& queue_type, int current_size) {
    // 更新队列相关指标
    if (queue_type == "llm" || queue_type == "LLM_GPU") {
        metrics_.llm_queue_size = current_size;
        if (current_size > metrics_.max_llm_queue_size) {
            metrics_.max_llm_queue_size = current_size;
        }
    } else if (queue_type == "tts" || queue_type == "TTS_CPU") {
        metrics_.tts_queue_size = current_size;
        if (current_size > metrics_.max_tts_queue_size) {
            metrics_.max_tts_queue_size = current_size;
        }
    } else if (queue_type == "image" || queue_type == "IMAGE_GPU_QUEUE") {
        metrics_.image_queue_size = current_size;
        if (current_size > metrics_.max_image_queue_size) {
            metrics_.max_image_queue_size = current_size;
        }
    }
}

std::string ResourceMonitor::getPerformanceReport() const {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    
    std::stringstream report;
    auto now = std::chrono::system_clock::now();
    auto time_now = std::chrono::system_clock::to_time_t(now);
    
    report << "========== PERFORMANCE REPORT ==========\n";
    report << "Timestamp: " << std::ctime(&time_now);
    report << "Uptime: " << getUptime() << "ms\n\n";
    
    // 系统资源
    report << "System Resources:\n";
    report << "  CPU Utilization: " << metrics_.cpu_utilization << "%\n";
    report << "  GPU Utilization: " << metrics_.gpu_utilization << "%\n";
    report << "  Memory Usage: " << metrics_.memory_usage << " MB\n";
    report << "  GPU Memory Usage: " << metrics_.gpu_memory_usage << " MB\n";
    report << "  Active Threads: " << metrics_.active_threads << "\n\n";
    
    // 任务统计
    report << "Task Statistics:\n";
    report << "  LLM: " << metrics_.llm_success_count << "/" << metrics_.llm_request_count 
           << " successful (" << (metrics_.llm_request_count > 0 ? 
              (metrics_.llm_success_count * 100.0 / metrics_.llm_request_count) : 0) << "%)\n";
    report << "  TTS: " << metrics_.tts_success_count << "/" << metrics_.tts_request_count 
           << " successful (" << (metrics_.tts_request_count > 0 ? 
              (metrics_.tts_success_count * 100.0 / metrics_.tts_request_count) : 0) << "%)\n";
    report << "  Image: " << metrics_.image_success_count << "/" << metrics_.image_request_count 
           << " successful (" << (metrics_.image_request_count > 0 ? 
              (metrics_.image_success_count * 100.0 / metrics_.image_request_count) : 0) << "%)\n\n";
    
    // 平均响应时间
    report << "Average Response Times:\n";
    report << "  LLM: " << (metrics_.llm_success_count > 0 ? 
              (metrics_.llm_total_time / metrics_.llm_success_count) : 0) << "ms\n";
    report << "  TTS: " << (metrics_.tts_success_count > 0 ? 
              (metrics_.tts_total_time / metrics_.tts_success_count) : 0) << "ms\n";
    report << "  Image: " << (metrics_.image_success_count > 0 ? 
              (metrics_.image_total_time / metrics_.image_success_count) : 0) << "ms\n\n";
    
    // 队列状态
    report << "Queue Status:\n";
    report << "  LLM Queue: " << metrics_.llm_queue_size << " (Max: " << metrics_.max_llm_queue_size << ")\n";
    report << "  TTS Queue: " << metrics_.tts_queue_size << " (Max: " << metrics_.max_tts_queue_size << ")\n";
    report << "  Image Queue: " << metrics_.image_queue_size << " (Max: " << metrics_.max_image_queue_size << ")\n\n";
    
    // 错误统计
    report << "Error Counts:\n";
    report << "  LLM Errors: " << metrics_.llm_error_count << "\n";
    report << "  TTS Errors: " << metrics_.tts_error_count << "\n";
    report << "  Image Errors: " << metrics_.image_error_count << "\n";
    report << "  Timeouts: " << metrics_.timeout_count << "\n\n";
    
    // 资源状态
    report << "Resource Status:\n";
    report << "  CPU Throttled: " << (metrics_.cpu_throttled ? "Yes" : "No") << "\n";
    report << "  GPU Throttled: " << (metrics_.gpu_throttled ? "Yes" : "No") << "\n";
    report << "  Memory Pressure: " << (metrics_.memory_pressure ? "Yes" : "No") << "\n";
    report << "=======================================\n";
    
    return report.str();
}

bool ResourceMonitor::exportMetricsToFile(const std::string& filename) const {
    try {
        std::ofstream file(filename);
        if (!file.is_open()) {
            std::cerr << "[ResourceMonitor] Failed to open file: " << filename << std::endl;
            return false;
        }
        
        file << getPerformanceReport();
        file.close();
        
        std::cout << "[ResourceMonitor] Metrics exported to " << filename << std::endl;
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "[ResourceMonitor] Exception exporting metrics: " << e.what() << std::endl;
        return false;
    }
}

void ResourceMonitor::setMonitorLevel(MonitorLevel level) {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    monitor_level_ = level;
    std::cout << "[ResourceMonitor] Monitor level changed to " << static_cast<int>(level) << std::endl;
}

MonitorLevel ResourceMonitor::getMonitorLevel() const {
    return monitor_level_;
}

bool ResourceMonitor::isRunning() const {
    return running_;
}

uint64_t ResourceMonitor::getUptime() const {
    auto now = std::chrono::steady_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(now - start_time_);
    return duration.count();
}

bool ResourceMonitor::isSystemHealthy() const {
    // 检查关键指标是否正常
    if (metrics_.cpu_utilization > 95.0f) return false;
    if (metrics_.gpu_utilization > 98.0f) return false;
    if (metrics_.memory_pressure) return false;
    if (metrics_.cpu_throttled || metrics_.gpu_throttled) return false;
    
    // 检查错误率是否过高
    float llm_error_rate = metrics_.llm_request_count > 0 ? 
        (metrics_.llm_error_count * 100.0f / metrics_.llm_request_count) : 0;
    if (llm_error_rate > 10.0f) return false;
    
    return true;
}

std::string ResourceMonitor::getHealthReport() const {
    std::stringstream report;
    report << "System Health: " << (isSystemHealthy() ? "HEALTHY" : "UNHEALTHY") << "\n";
    
    if (!isSystemHealthy()) {
        if (metrics_.cpu_utilization > 95.0f) {
            report << "  - CPU utilization too high: " << metrics_.cpu_utilization << "%\n";
        }
        if (metrics_.gpu_utilization > 98.0f) {
            report << "  - GPU utilization too high: " << metrics_.gpu_utilization << "%\n";
        }
        if (metrics_.memory_pressure) {
            report << "  - Memory pressure detected\n";
        }
        if (metrics_.cpu_throttled) {
            report << "  - CPU throttling active\n";
        }
        if (metrics_.gpu_throttled) {
            report << "  - GPU throttling active\n";
        }
        
        float llm_error_rate = metrics_.llm_request_count > 0 ? 
            (metrics_.llm_error_count * 100.0f / metrics_.llm_request_count) : 0;
        if (llm_error_rate > 10.0f) {
            report << "  - High LLM error rate: " << llm_error_rate << "%\n";
        }
    }
    
    return report.str();
}

void ResourceMonitor::monitorThreadFunc() {
    std::cout << "[ResourceMonitor] Monitor thread started" << std::endl;
    
    while (running_) {
        try {
            // 收集系统指标
            collectSystemMetrics();
            
            // 检查阈值
            checkThresholds();
            
            // 保存历史数据
            saveMetricsSnapshot();
            
            // 计算统计信息
            calculateStatistics();
            
            // 每10秒打印一次基本状态
            if (getUptime() % 10000 < monitor_interval_ms_) {
                std::cout << "[ResourceMonitor] Status - CPU: " << metrics_.cpu_utilization << "%, " 
                          << "GPU: " << metrics_.gpu_utilization << "%, "
                          << "Mem: " << metrics_.memory_usage << "MB, "
                          << "Threads: " << metrics_.active_threads << std::endl;
            }
            
        } catch (const std::exception& e) {
            std::cerr << "[ResourceMonitor] Exception in monitor thread: " << e.what() << std::endl;
        }
        
        // 等待下一次监控
        std::this_thread::sleep_for(std::chrono::milliseconds(monitor_interval_ms_));
    }
    
    std::cout << "[ResourceMonitor] Monitor thread stopped" << std::endl;
}

void ResourceMonitor::collectSystemMetrics() {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    
    // 收集CPU使用率
    if (monitor_level_ >= MonitorLevel::BASIC) {
        metrics_.cpu_utilization = collectCPUUtilization();
    }
    
    // 收集GPU使用率
    if (monitor_level_ >= MonitorLevel::BASIC) {
        metrics_.gpu_utilization = collectGPUUtilization();
    }
    
    // 收集内存使用情况
    if (monitor_level_ >= MonitorLevel::EXTENDED) {
        metrics_.memory_usage = collectMemoryUsage();
        metrics_.gpu_memory_usage = collectGPUMemoryUsage();
    }
    
    // 收集活跃线程数
    if (monitor_level_ >= MonitorLevel::EXTENDED) {
        metrics_.active_threads = std::thread::hardware_concurrency();
    }
    
    // 检查资源限制
    if (monitor_level_ >= MonitorLevel::DETAILED) {
        checkResourceLimits();
    }
}

void ResourceMonitor::checkThresholds() {
    std::lock_guard<std::mutex> lock(callbacks_mutex_);
    auto metrics_copy = getCurrentMetrics();
    
    for (auto& [metric_name, callback_info] : callbacks_) {
        // 跳过已触发且只触发一次的回调
        if (callback_info.once && callback_info.triggered) {
            continue;
        }
        
        // 检查不同指标的阈值
        bool threshold_reached = false;
        
        if (metric_name == "cpu_utilization" && metrics_copy.cpu_utilization > callback_info.threshold) {
            threshold_reached = true;
        } else if (metric_name == "gpu_utilization" && metrics_copy.gpu_utilization > callback_info.threshold) {
            threshold_reached = true;
        } else if (metric_name == "memory_usage" && metrics_copy.memory_usage > callback_info.threshold) {
            threshold_reached = true;
        } else if (metric_name == "llm_queue_size" && metrics_copy.llm_queue_size > callback_info.threshold) {
            threshold_reached = true;
        } else if (metric_name == "tts_queue_size" && metrics_copy.tts_queue_size > callback_info.threshold) {
            threshold_reached = true;
        } else if (metric_name == "image_queue_size" && metrics_copy.image_queue_size > callback_info.threshold) {
            threshold_reached = true;
        }
        
        // 触发回调
        if (threshold_reached) {
            try {
                callback_info.callback(metric_name, metrics_copy);
                callback_info.triggered = true;
                std::cout << "[ResourceMonitor] Threshold triggered for metric '" 
                          << metric_name << "': " << callback_info.threshold << std::endl;
            } catch (const std::exception& e) {
                std::cerr << "[ResourceMonitor] Exception in callback for '" 
                          << metric_name << "': " << e.what() << std::endl;
            }
        }
    }
}

float ResourceMonitor::collectCPUUtilization() {
#ifdef _WIN32
    // Windows平台CPU使用率收集
    FILETIME idle_time, kernel_time, user_time;
    if (GetSystemTimes(&idle_time, &kernel_time, &user_time)) {
        // 简化实现，实际需要两次采样计算差值
        return static_cast<float>(rand() % 100); // 模拟值
    }
    return 0.0f;
#else
    // Linux/Unix平台CPU使用率收集
    return static_cast<float>(rand() % 100); // 模拟值
#endif
}

float ResourceMonitor::collectGPUUtilization() {
    // 简化实现，实际应该调用CUDA API或其他GPU监控库
    return static_cast<float>(rand() % 100); // 模拟值
}

size_t ResourceMonitor::collectMemoryUsage() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX pmc;
    if (GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof(pmc))) {
        return pmc.WorkingSetSize / (1024 * 1024); // 转换为MB
    }
    return 0;
#else
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
        return usage.ru_maxrss / 1024; // 转换为MB
    }
    return 0;
#endif
}

size_t ResourceMonitor::collectGPUMemoryUsage() {
    // 简化实现，实际应该调用CUDA API
    return static_cast<size_t>(rand() % 8192); // 模拟0-8GB内存使用
}

void ResourceMonitor::checkResourceLimits() {
    // 检查CPU阈值
    if (metrics_.cpu_utilization > 90.0f) {
        metrics_.cpu_throttled = true;
    } else if (metrics_.cpu_utilization < 50.0f) {
        metrics_.cpu_throttled = false;
    }
    
    // 检查GPU阈值
    if (metrics_.gpu_utilization > 95.0f) {
        metrics_.gpu_throttled = true;
    } else if (metrics_.gpu_utilization < 60.0f) {
        metrics_.gpu_throttled = false;
    }
    
    // 检查内存压力（假设系统有16GB内存）
    if (metrics_.memory_usage > 12000) { // 12GB
        metrics_.memory_pressure = true;
    } else if (metrics_.memory_usage < 8000) { // 8GB
        metrics_.memory_pressure = false;
    }
}

void ResourceMonitor::calculateStatistics() {
    // 可以在这里计算更复杂的统计信息
    // 例如：移动平均值、标准差等
}

void ResourceMonitor::saveMetricsSnapshot() {
    std::lock_guard<std::mutex> lock(history_mutex_);
    
    MetricsSnapshot snapshot;
    snapshot.metrics = getCurrentMetrics();
    snapshot.timestamp = std::chrono::steady_clock::now();
    
    history_.push_back(snapshot);
    
    // 限制历史记录大小
    if (history_.size() > max_history_size_) {
        history_.erase(history_.begin());
    }
}

// PerformanceOptimizer实现

std::shared_ptr<PerformanceOptimizer> PerformanceOptimizer::create() {
    return std::make_shared<PerformanceOptimizer>();
}

PerformanceOptimizer::PerformanceOptimizer() {
    // 初始化历史数据
    cpu_usage_history_.reserve(100);
    gpu_usage_history_.reserve(100);
}

PerformanceOptimizer::~PerformanceOptimizer() {
}

int PerformanceOptimizer::optimizeThreadPoolSize(int current_size, const PerformanceMetrics& metrics) {
    std::lock_guard<std::mutex> lock(history_mutex_);
    
    // 添加当前CPU使用率到历史记录
    cpu_usage_history_.push_back(metrics.cpu_utilization);
    if (cpu_usage_history_.size() > 100) {
        cpu_usage_history_.erase(cpu_usage_history_.begin());
    }
    
    // 计算平均CPU使用率
    float avg_cpu = 0.0f;
    for (float usage : cpu_usage_history_) {
        avg_cpu += usage;
    }
    avg_cpu /= cpu_usage_history_.size();
    
    // 根据CPU使用率调整线程池大小
    int new_size = current_size;
    
    if (avg_cpu > cpu_threshold_high_ && current_size < max_threads_) {
        // CPU使用率高，增加线程数
        new_size = std::min(current_size + 2, max_threads_);
    } else if (avg_cpu < cpu_threshold_low_ && current_size > min_threads_) {
        // CPU使用率低，减少线程数
        new_size = std::max(current_size - 1, min_threads_);
    }
    
    // 考虑队列状态进行微调
    if (metrics.llm_queue_size > 10 || metrics.tts_queue_size > 20) {
        new_size = std::min(new_size + 1, max_threads_);
    }
    
    return new_size;
}

bool PerformanceOptimizer::optimizeGPUMemory(size_t current_usage, size_t max_usage) {
    float usage_percent = (static_cast<float>(current_usage) / max_usage) * 100.0f;
    
    if (usage_percent > 90.0f) {
        // 内存使用率过高，可能需要释放缓存或限制批处理大小
        return true; // 需要优化
    }
    
    return false;
}

void PerformanceOptimizer::adjustTaskPriorities(const PerformanceMetrics& metrics) {
    // 这里可以实现动态调整任务优先级的逻辑
    // 例如：当LLM队列过长时降低低优先级任务的处理速度
}

PerformanceOptimizer::ResourcePrediction PerformanceOptimizer::predictResourceNeeds(int estimated_tasks_per_second) {
    ResourcePrediction prediction;
    
    // 基于历史数据进行简单预测
    float avg_cpu = 0.0f;
    float avg_gpu = 0.0f;
    
    {   
        std::lock_guard<std::mutex> lock(history_mutex_);
        if (!cpu_usage_history_.empty()) {
            for (float usage : cpu_usage_history_) {
                avg_cpu += usage;
            }
            avg_cpu /= cpu_usage_history_.size();
        }
        if (!gpu_usage_history_.empty()) {
            for (float usage : gpu_usage_history_) {
                avg_gpu += usage;
            }
            avg_gpu /= gpu_usage_history_.size();
        }
    }
    
    // 线性预测
    prediction.predicted_cpu_usage = avg_cpu * (estimated_tasks_per_second / 10.0f);
    prediction.predicted_gpu_usage = avg_gpu * (estimated_tasks_per_second / 5.0f);
    prediction.predicted_memory_usage = estimated_tasks_per_second * 50; // 假设每个任务50MB
    prediction.recommended_threads = std::min(std::max(4, estimated_tasks_per_second / 10), 32);
    
    return prediction;
}

std::vector<std::string> PerformanceOptimizer::getOptimizationSuggestions(const PerformanceMetrics& metrics) {
    std::vector<std::string> suggestions;
    
    // CPU优化建议
    if (metrics.cpu_utilization > 85.0f) {
        suggestions.push_back("High CPU utilization detected. Consider increasing thread pool size or optimizing CPU-bound tasks.");
    }
    
    // GPU优化建议
    if (metrics.gpu_utilization > 90.0f) {
        suggestions.push_back("High GPU utilization detected. Consider reducing batch size or implementing GPU memory optimization.");
    }
    
    // 内存优化建议
    if (metrics.memory_usage > 12000) { // 12GB
        suggestions.push_back("High memory usage detected. Consider implementing memory pooling or reducing cache size.");
    }
    
    // 队列优化建议
    if (metrics.llm_queue_size > 20) {
        suggestions.push_back("LLM queue is growing large. Consider optimizing LLM inference speed or implementing request throttling.");
    }
    
    // 错误率优化建议
    float llm_error_rate = metrics.llm_request_count > 0 ? 
        (metrics.llm_error_count * 100.0f / metrics.llm_request_count) : 0;
    if (llm_error_rate > 5.0f) {
        suggestions.push_back("LLM error rate is high. Check LLM worker health and logs.");
    }
    
    // 线程优化建议
    int optimal_threads = std::thread::hardware_concurrency();
    if (metrics.active_threads > optimal_threads * 2) {
        suggestions.push_back("Excessive threads detected. Consider reducing thread count to match hardware concurrency.");
    }
    
    return suggestions;
}

MonitorLevel PerformanceOptimizer::suggestMonitorLevel(const PerformanceMetrics& metrics) {
    // 基于系统负载动态调整监控级别
    if (metrics.cpu_utilization > 80.0f || metrics.gpu_utilization > 80.0f) {
        return MonitorLevel::DETAILED; // 高负载时使用详细监控
    } else if (metrics.cpu_utilization > 50.0f || metrics.gpu_utilization > 50.0f) {
        return MonitorLevel::EXTENDED; // 中等负载时使用扩展监控
    } else {
        return MonitorLevel::BASIC; // 低负载时使用基本监控
    }
}

bool PerformanceOptimizer::shouldScaleResources(const PerformanceMetrics& metrics) {
    // 检查是否需要扩展资源
    if (metrics.cpu_utilization > 90.0f && metrics.llm_queue_size > 10) {
        return true; // 需要扩展CPU资源
    }
    
    if (metrics.gpu_utilization > 95.0f && metrics.image_queue_size > 5) {
        return true; // 需要扩展GPU资源
    }
    
    return false;
}

uint64_t PerformanceOptimizer::estimateTaskCompletionTime(const std::string& task_type, const PerformanceMetrics& metrics) {
    // 基于历史性能估算任务完成时间
    if (task_type == "llm" || task_type == "LLM_GPU") {
        if (metrics.llm_success_count > 0) {
            uint64_t avg_time = metrics.llm_total_time / metrics.llm_success_count;
            // 考虑队列等待时间
            return avg_time * (1 + metrics.llm_queue_size * 0.1);
        }
    } else if (task_type == "tts" || task_type == "TTS_CPU") {
        if (metrics.tts_success_count > 0) {
            uint64_t avg_time = metrics.tts_total_time / metrics.tts_success_count;
            return avg_time * (1 + metrics.tts_queue_size * 0.05);
        }
    } else if (task_type == "image" || task_type == "IMAGE_GPU_QUEUE") {
        if (metrics.image_success_count > 0) {
            uint64_t avg_time = metrics.image_total_time / metrics.image_success_count;
            // 图像生成通常需要更长的队列等待时间
            return avg_time * (1 + metrics.image_queue_size * 0.5);
        }
    }
    
    // 默认估算值
    return 1000; // 1秒
}

} // namespace ai_scheduler::monitoring