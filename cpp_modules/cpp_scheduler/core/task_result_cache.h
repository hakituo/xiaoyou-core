#pragma once

#include <unordered_map>
#include <memory>
#include <mutex>
#include <chrono>
#include <string>

// ITask 定义在 ai_scheduler 命名空间（resource_isolation_scheduler.h）
namespace ai_scheduler {

class ITask;

class TaskResultCache {
public:
    TaskResultCache(int max_age_seconds = 300);
    ~TaskResultCache() = default;

    void store(const std::string& taskId, std::shared_ptr<ITask> task);
    std::shared_ptr<ITask> get(const std::string& taskId);
    void erase(const std::string& taskId);
    void clear();
    size_t size() const;

private:
    void cleanupExpired();

    struct CachedResult {
        std::shared_ptr<ITask> task;
        std::chrono::steady_clock::time_point timestamp;
    };

    std::unordered_map<std::string, CachedResult> results_;
    mutable std::mutex mutex_;
    int max_age_seconds_;
    size_t max_cache_size_;
};

} // namespace ai_scheduler
