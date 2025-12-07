#ifndef TASK_QUEUE_H
#define TASK_QUEUE_H

#include <queue>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <memory>
#include <atomic>
#include <optional>

namespace ai_scheduler {

// 任务队列项
struct QueueItem {
    using TaskFunc = std::function<void()>;
    
    uint64_t id;
    TaskFunc task;
    int priority;
    
    QueueItem(uint64_t _id, TaskFunc _task, int _priority = 0)
        : id(_id), task(std::move(_task)), priority(_priority) {
    }
    
    // 优先级比较
    bool operator<(const QueueItem& other) const {
        // 优先级高的排在前面
        return priority < other.priority;
    }
};

// 任务队列管理类
class TaskQueue {
public:
    TaskQueue(size_t max_concurrent = 1);
    ~TaskQueue();
    
    // 初始化队列
    void initialize();
    
    // 关闭队列
    void shutdown();
    
    // 添加任务
    uint64_t enqueue(QueueItem::TaskFunc task, int priority = 0);
    
    // 取消任务
    bool cancel(uint64_t task_id);
    
    // 获取队列大小
    size_t size() const;
    
    // 获取当前运行中的任务数
    size_t runningCount() const;
    
    // 是否为空
    bool empty() const;
    
private:
    // 工作线程函数
    void workerThread();
    
    // 内部任务队列（优先级队列）
    std::priority_queue<QueueItem> queue_;
    
    // 互斥锁和条件变量
    mutable std::mutex mutex_;
    std::condition_variable condition_;
    
    // 状态控制
    std::atomic<bool> running_;
    size_t max_concurrent_;
    std::atomic<size_t> running_count_;
    std::atomic<uint64_t> next_task_id_;
    
    // 工作线程
    std::vector<std::thread> workers_;
};

} // namespace ai_scheduler

#endif // TASK_QUEUE_H