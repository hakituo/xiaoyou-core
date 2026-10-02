#include "task_result_cache.h"
#include "resource_isolation_scheduler.h"
#include <algorithm>

namespace ai_scheduler {

TaskResultCache::TaskResultCache(int max_age_seconds)
    : max_age_seconds_(max_age_seconds), max_cache_size_(1000) {
}

void TaskResultCache::store(const std::string& taskId, std::shared_ptr<ITask> task) {
    if (!task) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    
    results_[taskId] = {task, std::chrono::steady_clock::now()};
    
    if (results_.size() > max_cache_size_) {
        cleanupExpired();
    }
}

std::shared_ptr<ITask> TaskResultCache::get(const std::string& taskId) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    auto it = results_.find(taskId);
    if (it != results_.end()) {
        auto age = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::steady_clock::now() - it->second.timestamp).count();
        
        if (age <= max_age_seconds_) {
            return it->second.task;
        } else {
            results_.erase(it);
        }
    }
    
    return nullptr;
}

void TaskResultCache::erase(const std::string& taskId) {
    std::lock_guard<std::mutex> lock(mutex_);
    results_.erase(taskId);
}

void TaskResultCache::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    results_.clear();
}

size_t TaskResultCache::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return results_.size();
}

void TaskResultCache::cleanupExpired() {
    auto now = std::chrono::steady_clock::now();
    
    for (auto it = results_.begin(); it != results_.end(); ) {
        auto age = std::chrono::duration_cast<std::chrono::seconds>(
            now - it->second.timestamp).count();
        
        if (age > max_age_seconds_) {
            it = results_.erase(it);
        } else {
            ++it;
        }
    }
}

} // namespace ai_scheduler
