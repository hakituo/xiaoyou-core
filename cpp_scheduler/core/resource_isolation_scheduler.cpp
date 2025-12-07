#include "resource_isolation_scheduler.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <system_error>
#include <algorithm>
#include <execution>

// 实现ResourceIsolationScheduler类
ResourceIsolationScheduler::ResourceIsolationScheduler()
    : running_(false), initialized_(false),
      totalTasks_(0), completedTasks_(0), failedTasks_(0) {
}

ResourceIsolationScheduler::~ResourceIsolationScheduler() {
    shutdown();
}

bool ResourceIsolationScheduler::initialize(size_t cpuThreadCount) {
    if (initialized_) {
        return true;
    }
    
    running_ = true;
    
    // 创建CPU工作线程池
    for (size_t i = 0; i < cpuThreadCount; ++i) {
        workerThreads_.emplace_back([this]() {
            while (running_) {
                processTaskQueues();
            }
        });
    }
    
    // 创建图像生成队列处理线程（单独的异步处理）
    imageQueueThread_ = std::thread([this]() {
        while (running_) {
            processImageGenerationQueue();
        }
    });
    
    initialized_ = true;
    std::cout << "ResourceIsolationScheduler initialized with " 
              << cpuThreadCount << " CPU threads" << std::endl;
    
    return true;
}

void ResourceIsolationScheduler::shutdown() {
    if (!initialized_) {
        return;
    }
    
    running_ = false;
    cv_.notify_all();
    imageCv_.notify_one();
    
    // 等待所有线程结束
    for (auto& thread : workerThreads_) {
        if (thread.joinable()) {
            thread.join();
        }
    }
    
    if (imageQueueThread_.joinable()) {
        imageQueueThread_.join();
    }
    
    // 清理工作器
    for (auto& worker : workers_) {
        worker->shutdown();
    }
    
    workers_.clear();
    gpuWorkers_.clear();
    cpuWorkers_.clear();
    llmWorker_ = nullptr;
    
    // 清空任务队列
    { 
        std::lock_guard<std::mutex> lock(queueMutex_);
        while (!llmTaskQueue_.empty()) llmTaskQueue_.pop();
        while (!ttsTaskQueue_.empty()) ttsTaskQueue_.pop();
        tasks_.clear();
    }
    
    { 
        std::lock_guard<std::mutex> lock(imageQueueMutex_);
        while (!imageTaskQueue_.empty()) imageTaskQueue_.pop();
    }
    
    initialized_ = false;
    std::cout << "ResourceIsolationScheduler shutdown completed" << std::endl;
}

bool ResourceIsolationScheduler::addWorker(std::shared_ptr<IWorker> worker) {
    if (!worker) {
        return false;
    }
    
    try {
        worker->initialize();
        
        { 
            std::lock_guard<std::mutex> lock(queueMutex_);
            workers_.push_back(worker);
            
            // 根据工作器类型分类
            if (worker->canHandle(TaskType::LLM_INFERENCE) || 
                worker->canHandle(TaskType::IMAGE_GENERATION)) {
                gpuWorkers_.push_back(worker);
                
                // 第一个LLM工作器作为专用LLM处理工作器
                if (worker->canHandle(TaskType::LLM_INFERENCE) && !llmWorker_) {
                    llmWorker_ = worker;
                    std::cout << "LLM dedicated worker set: " << worker->getWorkerId() << std::endl;
                }
            } else if (worker->canHandle(TaskType::TTS_SYNTHESIS)) {
                cpuWorkers_.push_back(worker);
            }
        }
        
        std::cout << "Worker added: " << worker->getWorkerId() << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to add worker: " << e.what() << std::endl;
        return false;
    }
}

bool ResourceIsolationScheduler::cancelTask(const std::string& taskId) {
    std::lock_guard<std::mutex> lock(queueMutex_);
    auto it = tasks_.find(taskId);
    if (it != tasks_.end()) {
        if (it->second->getStatus() == TaskStatus::PENDING) {
            it->second->setStatus(TaskStatus::CANCELLED);
            // 从映射中移除，但不从队列中移除（会在处理时检查状态）
            tasks_.erase(it);
            return true;
        }
    }
    return false;
}

TaskStatus ResourceIsolationScheduler::getTaskStatus(const std::string& taskId) {
    std::lock_guard<std::mutex> lock(queueMutex_);
    auto it = tasks_.find(taskId);
    if (it != tasks_.end()) {
        return it->second->getStatus();
    }
    return TaskStatus::CANCELLED; // 任务不存在视为已取消
}

ResourceIsolationScheduler::SystemStatus ResourceIsolationScheduler::getSystemStatus() {
    SystemStatus status;
    
    std::lock_guard<std::mutex> lock(queueMutex_);
    status.totalTasks = totalTasks_;
    status.completedTasks = completedTasks_;
    status.failedTasks = failedTasks_;
    
    // 计算等待和运行中的任务数
    status.pendingTasks = 0;
    status.runningTasks = 0;
    
    for (const auto& [id, task] : tasks_) {
        if (task->getStatus() == TaskStatus::PENDING) {
            status.pendingTasks++;
        } else if (task->getStatus() == TaskStatus::RUNNING) {
            status.runningTasks++;
        }
    }
    
    // 获取工作器状态
    for (const auto& worker : workers_) {
        status.workerStatus[worker->getWorkerId()] = worker->isBusy();
    }
    
    return status;
}

void ResourceIsolationScheduler::waitForAllTasks() {
    while (true) {
        { 
            std::lock_guard<std::mutex> lock(queueMutex_);
            if (tasks_.empty() && llmTaskQueue_.empty() && ttsTaskQueue_.empty()) {
                break;
            }
        }
        
        { 
            std::lock_guard<std::mutex> lock(imageQueueMutex_);
            if (imageTaskQueue_.empty()) {
                break;
            }
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}

ResourceIsolationScheduler::ResourceUsage ResourceIsolationScheduler::getResourceUsage() {
    ResourceUsage usage;
    // 这里可以实现实际的资源监控逻辑
    // 目前返回默认值
    usage.cpuUsage = 0.0f;
    usage.gpuUsage = 0.0f;
    usage.memoryUsage = 0;
    usage.gpuMemoryUsage = 0;
    return usage;
}

void ResourceIsolationScheduler::processTaskQueues() {
    std::shared_ptr<ITask> task = nullptr;
    TaskType taskType = TaskType::TTS_SYNTHESIS; // 默认CPU任务
    
    // 尝试获取任务
    { 
        std::unique_lock<std::mutex> lock(queueMutex_);
        
        // 首先检查是否有LLM任务（最高优先级）
        if (!llmTaskQueue_.empty()) {
            task = llmTaskQueue_.front();
            llmTaskQueue_.pop();
            taskType = TaskType::LLM_INFERENCE;
        } 
        // 然后检查TTS任务
        else if (!ttsTaskQueue_.empty()) {
            task = ttsTaskQueue_.front();
            ttsTaskQueue_.pop();
            taskType = TaskType::TTS_SYNTHESIS;
        }
        
        // 如果没有任务，等待
        if (!task) {
            cv_.wait_for(lock, std::chrono::milliseconds(100));
            return;
        }
        
        // 检查任务是否已取消
        if (task->getStatus() == TaskStatus::CANCELLED) {
            tasks_.erase(task->getTaskId());
            return;
        }
    }
    
    // 选择合适的工作器处理任务
    std::shared_ptr<IWorker> worker = selectWorker(taskType);
    if (worker) {
        try {
            // 处理任务
            worker->processTask(task);
            
            // 更新统计信息
            if (task->getStatus() == TaskStatus::COMPLETED) {
                completedTasks_++;
            } else if (task->getStatus() == TaskStatus::FAILED) {
                failedTasks_++;
            }
        } catch (const std::exception& e) {
            std::cerr << "Error processing task " << task->getTaskId() << ": " << e.what() << std::endl;
            task->setStatus(TaskStatus::FAILED);
            failedTasks_++;
        }
    } else {
        // 如果没有合适的工作器，将任务放回队列
        std::lock_guard<std::mutex> lock(queueMutex_);
        switch (taskType) {
            case TaskType::LLM_INFERENCE:
                llmTaskQueue_.push(task);
                break;
            case TaskType::TTS_SYNTHESIS:
                ttsTaskQueue_.push(task);
                break;
            default:
                break;
        }
        
        // 短暂休眠避免忙等待
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    
    // 从任务映射中移除完成的任务
    if (task->getStatus() == TaskStatus::COMPLETED || 
        task->getStatus() == TaskStatus::FAILED ||
        task->getStatus() == TaskStatus::CANCELLED) {
        std::lock_guard<std::mutex> lock(queueMutex_);
        tasks_.erase(task->getTaskId());
    }
}

std::shared_ptr<IWorker> ResourceIsolationScheduler::selectWorker(TaskType type) {
    std::lock_guard<std::mutex> lock(queueMutex_);
    
    // LLM任务使用专用工作器
    if (type == TaskType::LLM_INFERENCE && llmWorker_ && !llmWorker_->isBusy()) {
        return llmWorker_;
    }
    
    // 根据任务类型选择工作器
    if (type == TaskType::TTS_SYNTHESIS) {
        // 查找空闲的CPU工作器
        for (const auto& worker : cpuWorkers_) {
            if (worker->canHandle(type) && !worker->isBusy()) {
                return worker;
            }
        }
    } else {
        // 查找空闲的GPU工作器（不包括LLM专用工作器）
        for (const auto& worker : gpuWorkers_) {
            if (worker != llmWorker_ && worker->canHandle(type) && !worker->isBusy()) {
                return worker;
            }
        }
    }
    
    return nullptr; // 没有找到合适的工作器
}

void ResourceIsolationScheduler::processImageGenerationQueue() {
    std::shared_ptr<ITask> task = nullptr;
    
    // 尝试获取图像生成任务
    { 
        std::unique_lock<std::mutex> lock(imageQueueMutex_);
        
        if (imageTaskQueue_.empty()) {
            imageCv_.wait_for(lock, std::chrono::milliseconds(100));
            return;
        }
        
        task = imageTaskQueue_.front();
        imageTaskQueue_.pop();
    }
    
    // 选择图像生成工作器（非LLM专用）
    { 
        std::lock_guard<std::mutex> lock(queueMutex_);
        
        // 检查任务是否已取消
        auto it = tasks_.find(task->getTaskId());
        if (it == tasks_.end() || task->getStatus() == TaskStatus::CANCELLED) {
            return;
        }
        
        // 选择合适的GPU工作器
        std::shared_ptr<IWorker> worker = nullptr;
        for (const auto& w : gpuWorkers_) {
            if (w != llmWorker_ && w->canHandle(TaskType::IMAGE_GENERATION) && !w->isBusy()) {
                worker = w;
                break;
            }
        }
        
        if (worker) {
            try {
                std::cout << "Processing image generation task on worker: " << worker->getWorkerId() << std::endl;
                worker->processTask(task);
                
                // 更新统计信息
                if (task->getStatus() == TaskStatus::COMPLETED) {
                    completedTasks_++;
                } else if (task->getStatus() == TaskStatus::FAILED) {
                    failedTasks_++;
                }
            } catch (const std::exception& e) {
                std::cerr << "Error processing image task " << task->getTaskId() << ": " << e.what() << std::endl;
                task->setStatus(TaskStatus::FAILED);
                failedTasks_++;
            }
        } else {
            // 如果没有可用的工作器，将任务放回队列（实现异步队列效果）
            std::unique_lock<std::mutex> lock(imageQueueMutex_);
            imageTaskQueue_.push(task);
            std::cout << "No available GPU worker for image generation, task queued" << std::endl;
            
            // 短暂休眠避免频繁尝试
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
    
    // 从任务映射中移除完成的任务
    if (task->getStatus() == TaskStatus::COMPLETED || 
        task->getStatus() == TaskStatus::FAILED ||
        task->getStatus() == TaskStatus::CANCELLED) {
        std::lock_guard<std::mutex> lock(queueMutex_);
        tasks_.erase(task->getTaskId());
    }
}