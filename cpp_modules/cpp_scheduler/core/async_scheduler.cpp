#include "async_scheduler.h"
#include <iostream>
#include <chrono>
#include <algorithm>

namespace ai_scheduler {

// 静态成员初始化
std::atomic<uint64_t> Task::next_id_(0);

Task::Task(TaskType type, TaskPriority priority)
    : type_(type), priority_(priority), id_(next_id_++) {
}

void Task::notifyComplete(bool success, const std::string& result) {
    if (callback_) {
        callback_(success, result);
    }
}

AsyncScheduler::AsyncScheduler() 
    : loop_(nullptr), async_handle_(nullptr), running_(false),
      num_gpu_workers_(2), num_cpu_workers_(4) {
}

AsyncScheduler::~AsyncScheduler() {
    stop();
    if (async_handle_) {
        uv_close(reinterpret_cast<uv_handle_t*>(async_handle_), nullptr);
    }
    if (loop_) {
        uv_loop_close(loop_);
        delete loop_;
    }
}

bool AsyncScheduler::initialize(int num_gpu_workers, int num_cpu_workers) {
    num_gpu_workers_ = num_gpu_workers;
    num_cpu_workers_ = num_cpu_workers;
    
    // 初始化libuv循环
    loop_ = new uv_loop_t();
    int ret = uv_loop_init(loop_);
    if (ret != 0) {
        std::cerr << "Failed to initialize uv loop: " << uv_strerror(ret) << std::endl;
        return false;
    }
    
    // 创建异步句柄用于线程间通信
    async_handle_ = new uv_async_t();
    async_handle_->data = this;
    ret = uv_async_init(loop_, async_handle_, [](uv_async_t* handle) {
        AsyncScheduler* scheduler = static_cast<AsyncScheduler*>(handle->data);
        scheduler->processTaskQueue();
    });
    
    if (ret != 0) {
        std::cerr << "Failed to initialize async handle: " << uv_strerror(ret) << std::endl;
        return false;
    }
    
    return true;
}

void AsyncScheduler::start() {
    if (running_) {
        return;
    }
    
    running_ = true;
    
    // 创建工作线程
    for (int i = 0; i < num_gpu_workers_; ++i) {
        // GPU worker 0 用于LLM
        // GPU worker 1 用于图像生成
        TaskType worker_type = (i == 0) ? TaskType::LLM_GPU : TaskType::IMAGE_GPU_QUEUE;
        gpu_workers_.emplace_back(&AsyncScheduler::workerThreadFunction, this, worker_type);
    }
    
    for (int i = 0; i < num_cpu_workers_; ++i) {
        cpu_workers_.emplace_back(&AsyncScheduler::workerThreadFunction, this, TaskType::TTS_CPU);
    }
    
    // 启动libuv事件循环（阻塞）
    std::cout << "Async scheduler started with " << num_gpu_workers_ << " GPU workers and " 
              << num_cpu_workers_ << " CPU workers" << std::endl;
    
    uv_run(loop_, UV_RUN_DEFAULT);
}

void AsyncScheduler::stop() {
    if (!running_) {
        return;
    }
    
    running_ = false;
    
    // 唤醒所有工作线程
    uv_async_send(async_handle_);
    
    // 等待工作线程结束
    for (auto& worker : gpu_workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
    
    for (auto& worker : cpu_workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
    
    // 清空队列
    std::lock_guard<std::mutex> lock(task_mutex_);
    tasks_.clear();
    llm_queue_.clear();
    tts_queue_.clear();
    image_queue_.clear();
    
    gpu_workers_.clear();
    cpu_workers_.clear();
    
    // 停止事件循环
    if (loop_) {
        uv_stop(loop_);
    }
    
    std::cout << "Async scheduler stopped" << std::endl;
}

uint64_t AsyncScheduler::submitTask(std::shared_ptr<Task> task) {
    if (!task) {
        return 0;
    }
    
    uint64_t task_id = task->getId();
    
    {  // 加锁保护
        std::lock_guard<std::mutex> lock(task_mutex_);
        tasks_[task_id] = task;
        
        // 根据任务类型放入不同队列
        switch (task->getType()) {
            case TaskType::LLM_GPU:
                llm_queue_.push_back(task);
                break;
            case TaskType::TTS_CPU:
                tts_queue_.push_back(task);
                break;
            case TaskType::IMAGE_GPU_QUEUE:
                image_queue_.push_back(task);
                break;
        }
    }
    
    // 通知调度器有新任务
    uv_async_send(async_handle_);
    
    return task_id;
}

bool AsyncScheduler::cancelTask(uint64_t task_id) {
    std::lock_guard<std::mutex> lock(task_mutex_);
    auto it = tasks_.find(task_id);
    if (it != tasks_.end()) {
        // 从对应队列中移除
        auto& queue = [&]() -> std::vector<std::shared_ptr<Task>>& {
            switch (it->second->getType()) {
                case TaskType::LLM_GPU: return llm_queue_;
                case TaskType::TTS_CPU: return tts_queue_;
                case TaskType::IMAGE_GPU_QUEUE: return image_queue_;
                default: return llm_queue_;
            }
        }();
        
        queue.erase(std::remove_if(queue.begin(), queue.end(),
            [task_id](const std::shared_ptr<Task>& t) { return t->getId() == task_id; }),
            queue.end());
        
        tasks_.erase(it);
        return true;
    }
    return false;
}

void AsyncScheduler::workerThreadFunction(TaskType worker_type) {
    std::cout << "Worker thread started for type " << static_cast<int>(worker_type) << std::endl;
    
    while (running_) {
        std::shared_ptr<Task> task = nullptr;
        
        {  // 加锁获取任务
            std::lock_guard<std::mutex> lock(task_mutex_);
            std::vector<std::shared_ptr<Task>>* target_queue = nullptr;
            
            switch (worker_type) {
                case TaskType::LLM_GPU:
                    target_queue = &llm_queue_;
                    break;
                case TaskType::TTS_CPU:
                    target_queue = &tts_queue_;
                    break;
                case TaskType::IMAGE_GPU_QUEUE:
                    target_queue = &image_queue_;
                    break;
            }
            
            if (target_queue && !target_queue->empty()) {
                // 优先处理高优先级任务
                auto it = std::find_if(target_queue->begin(), target_queue->end(),
                    [](const std::shared_ptr<Task>& t) {
                        return t->getPriority() == TaskPriority::HIGH;
                    });
                
                if (it != target_queue->end()) {
                    task = *it;
                    target_queue->erase(it);
                } else {
                    // 没有高优先级任务，取第一个
                    task = target_queue->front();
                    target_queue->erase(target_queue->begin());
                }
            }
        }
        
        if (task) {
            try {
                std::cout << "Executing task " << task->getId() << " of type " 
                          << static_cast<int>(task->getType()) << std::endl;
                
                // 执行任务
                task->execute();
                
                // 从任务映射中移除
                {  
                    std::lock_guard<std::mutex> lock(task_mutex_);
                    tasks_.erase(task->getId());
                }
                
            } catch (const std::exception& e) {
                std::cerr << "Exception in task " << task->getId() << ": " << e.what() << std::endl;
                task->notifyComplete(false, "Exception: " + std::string(e.what()));
                
                // 从任务映射中移除
                {  
                    std::lock_guard<std::mutex> lock(task_mutex_);
                    tasks_.erase(task->getId());
                }
            }
        } else {
            // 没有任务，短暂休眠
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
    
    std::cout << "Worker thread stopped for type " << static_cast<int>(worker_type) << std::endl;
}

void AsyncScheduler::processTaskQueue() {
    // 此方法在libuv事件循环线程中执行
    // 主要用于任务状态更新和回调通知
    std::cout << "Processing task queue" << std::endl;
}

} // namespace ai_scheduler