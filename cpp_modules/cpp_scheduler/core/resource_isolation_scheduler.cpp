#include "resource_isolation_scheduler.h"
#include "task_result_cache.h"
#include "../workers/gpu_llm_worker.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <system_error>
#include <algorithm>

// 实现ResourceIsolationScheduler类
ResourceIsolationScheduler::ResourceIsolationScheduler()
    : running_(false), initialized_(false),
      totalTasks_(0), completedTasks_(0), failedTasks_(0) {
    biologicalSystem_ = std::make_shared<ai_scheduler::BiologicalSystem>();
    nativeExecutor_ = std::make_shared<ai_scheduler::NativeExecutor>();
    native_executor_enabled_ = true;
    biological_update_interval_ms_ = 100;
    biological_update_count_ = 0;
    taskResultCache_ = std::make_unique<ai_scheduler::TaskResultCache>(300); // 5分钟缓存
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

    if (biologicalSystem_) {
        biologicalSystem_->initialize();
    }

    if (native_executor_enabled_ && nativeExecutor_ && biologicalSystem_) {
        nativeExecutor_->start();
        auto lastTime = std::make_shared<std::chrono::steady_clock::time_point>(std::chrono::steady_clock::now());
        nativeExecutor_->addTimer(
            biological_update_interval_ms_,
            biological_update_interval_ms_,
            [this, lastTime]() {
                auto now = std::chrono::steady_clock::now();
                std::chrono::duration<float> diff = now - *lastTime;
                biologicalSystem_->update(diff.count());
                *lastTime = now;
                biological_update_count_.fetch_add(1, std::memory_order_relaxed);
            }
        );
    } else if (biologicalSystem_) {
        biologicalUpdateThread_ = std::thread([this]() {
            auto lastTime = std::chrono::steady_clock::now();
            while (running_) {
                std::this_thread::sleep_for(std::chrono::milliseconds(biological_update_interval_ms_));
                if (!running_) {
                    break;
                }
                auto now = std::chrono::steady_clock::now();
                std::chrono::duration<float> diff = now - lastTime;
                biologicalSystem_->update(diff.count());
                lastTime = now;
                biological_update_count_.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }

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

    if (nativeExecutor_) {
        nativeExecutor_->stop();
    }
    
    // 等待所有线程结束
    for (auto& thread : workerThreads_) {
        if (thread.joinable()) {
            thread.join();
        }
    }
    
    if (imageQueueThread_.joinable()) {
        imageQueueThread_.join();
    }

    if (biologicalUpdateThread_.joinable()) {
        biologicalUpdateThread_.join();
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

void ResourceIsolationScheduler::setNativeExecutorEnabled(bool enabled) {
    if (initialized_) {
        return;
    }
    native_executor_enabled_ = enabled;
}

void ResourceIsolationScheduler::setBiologicalUpdateIntervalMs(uint64_t interval_ms) {
    if (initialized_) {
        return;
    }
    if (interval_ms == 0) {
        return;
    }
    biological_update_interval_ms_ = interval_ms;
}

uint64_t ResourceIsolationScheduler::getBiologicalUpdateCount() const {
    return biological_update_count_.load(std::memory_order_relaxed);
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
                if (worker->canHandle(TaskType::LLM_INFERENCE)) {
                    // 尝试注入生物系统
                    auto llmWorker = std::dynamic_pointer_cast<ai_scheduler::GPULLMWorker>(worker);
                    if (llmWorker && biologicalSystem_) {
                        llmWorker->setBiologicalSystem(biologicalSystem_);
                    }

                    if (!llmWorker_) {
                        llmWorker_ = worker;
                        std::cout << "LLM dedicated worker set: " << worker->getWorkerId() << std::endl;
                    }
                }
            } else if (worker->canHandle(TaskType::TTS_SYNTHESIS)) {
                // 如果工作器显式表示支持 GPU（通过 ID 识别或以后通过接口识别）
                if (worker->getWorkerId().find("GPU") != std::string::npos) {
                    gpuWorkers_.push_back(worker);
                    std::cout << "TTS GPU worker added: " << worker->getWorkerId() << std::endl;
                } else {
                    cpuWorkers_.push_back(worker);
                }
            }
        }
        
        std::cout << "Worker added: " << worker->getWorkerId() << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to add worker: " << e.what() << std::endl;
        return false;
    }
}

void ResourceIsolationScheduler::submitTask(std::shared_ptr<ITask> task) {
    if (!task) return;

    const auto taskType = task->getType();
    {
        std::lock_guard<std::mutex> lock(queueMutex_);
        tasks_[task->getTaskId()] = task;
        totalTasks_++;

        if (taskType == TaskType::LLM_INFERENCE) {
            llmTaskQueue_.push(task);
        } else if (taskType == TaskType::TTS_SYNTHESIS) {
            ttsTaskQueue_.push(task);
        }
    }

    if (taskType == TaskType::IMAGE_GENERATION) {
        {
            std::lock_guard<std::mutex> imgLock(imageQueueMutex_);
            imageTaskQueue_.push(task);
        }
        imageCv_.notify_one();
        return;
    }

    cv_.notify_one();
}

bool ResourceIsolationScheduler::cancelTask(const std::string& taskId) {
    std::lock_guard<std::mutex> lock(queueMutex_);
    auto it = tasks_.find(taskId);
    if (it != tasks_.end()) {
        auto status = it->second->getStatus();
        if (status == TaskStatus::PENDING) {
            it->second->setStatus(TaskStatus::CANCELLED);
            tasks_.erase(it);
            return true;
        }
        if (status == TaskStatus::RUNNING) {
            it->second->setStatus(TaskStatus::CANCELLED);
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

std::shared_ptr<ITask> ResourceIsolationScheduler::getTask(const std::string& taskId) {
    // 首先检查活跃任务
    {
        std::lock_guard<std::mutex> lock(queueMutex_);
        auto it = tasks_.find(taskId);
        if (it != tasks_.end()) {
            return it->second;
        }
    }
    
    // 然后检查结果缓存
    if (taskResultCache_) {
        return taskResultCache_->get(taskId);
    }
    
    return nullptr;
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
        bool has_queued = false;
        bool has_pending_or_running = false;
        {
            std::scoped_lock lock(queueMutex_, imageQueueMutex_);
            has_queued = !llmTaskQueue_.empty() || !ttsTaskQueue_.empty() || !imageTaskQueue_.empty();
            for (const auto& kv : tasks_) {
                const auto st = kv.second ? kv.second->getStatus() : TaskStatus::FAILED;
                if (st == TaskStatus::PENDING || st == TaskStatus::RUNNING) {
                    has_pending_or_running = true;
                    break;
                }
            }
        }

        if (!has_queued && !has_pending_or_running) {
            break;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
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

        cv_.wait(lock, [this]() {
            return !running_ || !llmTaskQueue_.empty() || !ttsTaskQueue_.empty();
        });

        if (!running_) {
            return;
        }

        if (!llmTaskQueue_.empty()) {
            task = llmTaskQueue_.front();
            llmTaskQueue_.pop();
            taskType = TaskType::LLM_INFERENCE;
        } else if (!ttsTaskQueue_.empty()) {
            task = ttsTaskQueue_.front();
            ttsTaskQueue_.pop();
            taskType = TaskType::TTS_SYNTHESIS;
        }

        if (!task) {
            return;
        }

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
    if (task->getStatus() == TaskStatus::CANCELLED) {
        std::lock_guard<std::mutex> lock(queueMutex_);
        tasks_.erase(task->getTaskId());
    } else if (task->getStatus() == TaskStatus::COMPLETED || 
               task->getStatus() == TaskStatus::FAILED) {
        // 将完成的任务移到结果缓存
        std::string taskId = task->getTaskId();
        std::shared_ptr<ITask> taskCopy = task;
        
        // 从活跃任务映射中移除
        {
            std::lock_guard<std::mutex> lock(queueMutex_);
            tasks_.erase(taskId);
        }
        
        // 存储到结果缓存
        if (taskResultCache_) {
            taskResultCache_->store(taskId, taskCopy);
        }
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
        // 优先查找空闲的GPU工作器（支持TTS的）
        for (const auto& worker : gpuWorkers_) {
            if (worker->canHandle(type) && !worker->isBusy()) {
                return worker;
            }
        }
        // 如果没有GPU工作器，查找空闲的CPU工作器
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
        imageCv_.wait(lock, [this]() { return !running_ || !imageTaskQueue_.empty(); });

        if (!running_) {
            return;
        }

        task = imageTaskQueue_.front();
        imageTaskQueue_.pop();
    }

    std::shared_ptr<IWorker> worker = nullptr;
    {
        std::lock_guard<std::mutex> lock(queueMutex_);

        auto it = tasks_.find(task->getTaskId());
        if (it == tasks_.end() || task->getStatus() == TaskStatus::CANCELLED) {
            return;
        }

        for (const auto& w : gpuWorkers_) {
            if (w != llmWorker_ && w->canHandle(TaskType::IMAGE_GENERATION) && !w->isBusy()) {
                worker = w;
                break;
            }
        }
    }

    if (worker) {
        try {
            std::cout << "Processing image generation task on worker: " << worker->getWorkerId() << std::endl;
            worker->processTask(task);

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
        {
            std::lock_guard<std::mutex> imgLock(imageQueueMutex_);
            imageTaskQueue_.push(task);
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    
    // 从任务映射中移除完成的任务
    if (task->getStatus() == TaskStatus::CANCELLED) {
        std::lock_guard<std::mutex> lock(queueMutex_);
        tasks_.erase(task->getTaskId());
    } else if (task->getStatus() == TaskStatus::COMPLETED ||
               task->getStatus() == TaskStatus::FAILED) {
        std::string taskId = task->getTaskId();
        std::shared_ptr<ITask> taskCopy = task;
        {
            std::lock_guard<std::mutex> lock(queueMutex_);
            tasks_.erase(taskId);
        }
        if (taskResultCache_) {
            taskResultCache_->store(taskId, taskCopy);
        }
    }
}

// ============================================================
// Phase-Aware 调度方法
// ============================================================

void ResourceIsolationScheduler::setPhaseStrategy(std::shared_ptr<IPhaseAwareStrategy> strategy) {
    std::lock_guard<std::mutex> lock(phaseMutex_);
    phaseStrategy_ = std::move(strategy);
    if (phaseStrategy_ && migrateLLMFn_ && restoreLLMFn_) {
        phaseStrategy_->setMigrationCallbacks(migrateLLMFn_, restoreLLMFn_);
    }
}

void ResourceIsolationScheduler::submitPhaseTask(
    const std::string& phase_name,
    const PhaseAttributes& attrs,
    std::shared_ptr<ITask> task)
{
    std::lock_guard<std::mutex> lock(phaseMutex_);
    phaseAttributesMap_[phase_name] = attrs;

    if (!phaseStrategy_) {
        submitTask(std::move(task));
        return;
    }

    auto route = phaseStrategy_->routeTask(
        attrs,
        phaseStrategy_->getLLMState(),
        SchedulerPolicy::V2_PHASE_AWARE);

    if (route == "cpu_backfill") {
        std::lock_guard<std::mutex> qLock(queueMutex_);
        ttsTaskQueue_.push(std::move(task));
        cv_.notify_one();
    } else {
        submitTask(std::move(task));
    }
}

LLMState ResourceIsolationScheduler::getLLMState() const {
    if (phaseStrategy_) {
        return phaseStrategy_->getLLMState();
    }
    return LLMState{};
}

bool ResourceIsolationScheduler::migrateLLMToCPU(bool urgent) {
    if (phaseStrategy_) {
        return phaseStrategy_->migrateLLMToCPU(urgent);
    }
    if (migrateLLMFn_) {
        return migrateLLMFn_(urgent);
    }
    return false;
}

bool ResourceIsolationScheduler::restoreLLMToGPU() {
    if (phaseStrategy_) {
        return phaseStrategy_->restoreLLMToGPU();
    }
    if (restoreLLMFn_) {
        return restoreLLMFn_();
    }
    return false;
}

void ResourceIsolationScheduler::setMigrationCallbacks(
    std::function<bool(bool urgent)> migrate_fn,
    std::function<bool()> restore_fn)
{
    migrateLLMFn_ = std::move(migrate_fn);
    restoreLLMFn_ = std::move(restore_fn);
    if (phaseStrategy_) {
        phaseStrategy_->setMigrationCallbacks(migrateLLMFn_, restoreLLMFn_);
    }
}
