#include "task_queue.h"
#include <iostream>
#include <unordered_set>

namespace ai_scheduler {

TaskQueue::TaskQueue(size_t max_concurrent) 
    : running_(false), max_concurrent_(max_concurrent), running_count_(0), next_task_id_(1) {
}

TaskQueue::~TaskQueue() {
    shutdown();
}

void TaskQueue::initialize() {
    if (running_) {
        return;
    }
    
    running_ = true;
    
    // 创建工作线程（对于GPU任务队列，我们只使用一个工作线程）
    workers_.emplace_back(&TaskQueue::workerThread, this);
    
    std::cout << "TaskQueue initialized with max concurrent: " << max_concurrent_ << std::endl;
}

void TaskQueue::shutdown() {
    if (!running_) {
        return;
    }
    
    running_ = false;
    condition_.notify_all();
    
    // 等待所有工作线程结束
    for (auto& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
    
    workers_.clear();
    
    // 清空队列
    std::lock_guard<std::mutex> lock(mutex_);
    std::priority_queue<QueueItem> empty;
    std::swap(queue_, empty);
    
    running_count_ = 0;
    
    std::cout << "TaskQueue shutdown" << std::endl;
}

uint64_t TaskQueue::enqueue(QueueItem::TaskFunc task, int priority) {
    if (!running_ || !task) {
        return 0;
    }
    
    uint64_t task_id = next_task_id_++;
    
    {  
        std::lock_guard<std::mutex> lock(mutex_);
        queue_.emplace(task_id, std::move(task), priority);
    }
    
    // 通知工作线程有新任务
    condition_.notify_one();
    
    return task_id;
}

bool TaskQueue::cancel(uint64_t task_id) {
    if (!running_ || task_id == 0) {
        return false;
    }
    
    // 注意：在这个简化实现中，我们不支持取消正在执行的任务
    // 只能取消还在队列中的任务
    // 完整实现需要使用一个额外的数据结构来跟踪已取消的任务ID
    
    std::cout << "Cancel task " << task_id << " (not fully implemented)" << std::endl;
    return false;
}

size_t TaskQueue::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
}

size_t TaskQueue::runningCount() const {
    return running_count_;
}

bool TaskQueue::empty() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.empty() && running_count_ == 0;
}

void TaskQueue::workerThread() {
    std::cout << "TaskQueue worker thread started" << std::endl;
    
    while (running_) {
        QueueItem::TaskFunc task;
        
        {  
            std::unique_lock<std::mutex> lock(mutex_);
            
            // 等待直到有任务或关闭信号
            condition_.wait(lock, [this] {
                return !running_ || !queue_.empty();
            });
            
            // 如果关闭且队列为空，退出
            if (!running_ && queue_.empty()) {
                break;
            }
            
            // 如果队列有任务且未达到最大并发数
            if (!queue_.empty() && running_count_ < max_concurrent_) {
                // 获取任务
                auto queue_item = queue_.top();
                queue_.pop();
                task = std::move(queue_item.task);
                
                // 增加运行计数
                running_count_++;
            }
        }
        
        // 执行任务（在锁外执行）
        if (task) {
            try {
                task();
            } catch (const std::exception& e) {
                std::cerr << "Exception in task queue worker: " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "Unknown exception in task queue worker" << std::endl;
            }
            
            // 减少运行计数
            running_count_--;
            
            // 通知其他可能在等待的工作线程
            condition_.notify_one();
        } else {
            // 短暂休眠避免忙等待
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
    
    std::cout << "TaskQueue worker thread stopped" << std::endl;
}

} // namespace ai_scheduler