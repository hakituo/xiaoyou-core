#include "gpu_llm_worker.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <stdexcept>
#include <chrono>

GPULLMWorker::GPULLMWorker(const std::string& workerId)
    : workerId_(workerId), 
      running_(false), 
      initialized_(false), 
      busy_(false), 
      currentTasks_(0), 
      completedTasksCount_(0), 
      totalInferenceTime_(0.0f),
      gpu_utilization_(0.0f),
      gpu_memory_usage_(0),
      total_inference_time_(0),
      inference_count_(0),
      temperature_(0.7f),
      max_tokens_(256),
      python_module_(nullptr),
      python_inference_func_(nullptr) {
    // 设置默认模型配置
    modelConfig_.modelPath = "./models/qwen/Qwen2___5-7B-Instruct";
    modelConfig_.modelType = "qwen";
    modelConfig_.quantization = "q4_0";
    modelConfig_.gpuDeviceId = 0;
    modelConfig_.maxContextSize = 4096;
    modelConfig_.maxBatchSize = 1;
    modelConfig_.temperature = 0.7f;
    modelConfig_.topK = 40;
    modelConfig_.topP = 0.9f;
    modelConfig_.repetitionPenalty = 1.05f;
    modelConfig_.enableCache = true;
    modelConfig_.cacheSize = 1024;
    
    // 同步到旧的成员变量
    model_path_ = modelConfig_.modelPath;
    gpu_id_ = modelConfig_.gpuDeviceId;
    max_context_length_ = modelConfig_.maxContextSize;
    
    std::cout << "GPULLMWorker initialized: " << workerId_ 
              << " with default model path: " << modelConfig_.modelPath << std::endl;
}

GPULLMWorker::~GPULLMWorker() {
    if (initialized_) {
        shutdown();
    }
}

bool GPULLMWorker::initialize() {
    if (initialized_) {
        return true;
    }
    
    std::cout << "Initializing GPULLMWorker: " << workerId_ << std::endl;
    
    try {
        // 设置GPU设备ID，确保资源隔离
        std::cout << "Setting GPU device to: " << gpu_id_ << std::endl;
        
        // 初始化Python接口
        if (!initializePythonInterface()) {
            std::cerr << "Failed to initialize Python interface" << std::endl;
            return false;
        }
        
        // 加载模型
        model_ = loadModelImpl(modelConfig_);
        if (!model_ || !model_->isReady()) {
            std::cerr << "Failed to load or initialize model" << std::endl;
            return false;
        }
        
        // 启动任务执行线程
        running_ = true;
        executionThread_ = std::thread(&GPULLMWorker::taskExecutionLoop, this);
        
        // 预热模型
        warmupModel();
        
        initialized_ = true;
        std::cout << "GPULLMWorker initialized successfully" << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Exception during GPULLMWorker initialization: " << e.what() << std::endl;
        return false;
    }
}

void GPULLMWorker::shutdown() {
    std::cout << "Shutting down GPULLMWorker: " << workerId_ << std::endl;
    
    if (running_) {
        // 停止执行线程
        {   
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            running_ = false;
            taskQueueCondition_.notify_one();
        }
        
        // 等待线程结束
        if (executionThread_.joinable()) {
            executionThread_.join();
        }
        
        // 清理模型
        if (model_) {
            model_->shutdown();
            model_.reset();
        }
        
        // 清理Python接口
        cleanupPythonInterface();
        
        // 清空任务队列
        {   
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            std::queue<ITaskPtr> empty;
            std::swap(taskQueue_, empty);
        }
        
        running_ = false;
        initialized_ = false;
    }
    
    std::cout << "GPULLMWorker shut down successfully" << std::endl;
}

void GPULLMWorker::taskExecutionLoop() {
    std::cout << "GPULLMWorker task execution loop started" << std::endl;
    
    while (running_) {
        ITaskPtr task = nullptr;
        
        // 获取任务
        {
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            // 等待任务或停止信号
            taskQueueCondition_.wait(lock, [this] { 
                return !running_ || !taskQueue_.empty(); 
            });
            
            if (!running_) break;
            
            if (!taskQueue_.empty()) {
                task = taskQueue_.front();
                taskQueue_.pop();
                busy_ = true;
                currentTasks_++;
            } else {
                continue;
            }
        }
        
        if (task && task->getStatus() != TaskStatus::CANCELLED) {
            try {
                // 执行任务
                auto startTime = std::chrono::high_resolution_clock::now();
                
                // 转换为LLMTask
                auto llmTask = std::dynamic_pointer_cast<LLMTask>(task);
                if (llmTask && model_) {
                    // 设置任务状态为执行中
                    llmTask->setStatus(TaskStatus::EXECUTING);
                    
                    // 执行推理
                    LLMInferenceRequest request = llmTask->getRequest();
                    LLMInferenceResponse response = model_->inference(request);
                    
                    // 设置结果
                    llmTask->setResponse(response);
                    llmTask->setStatus(TaskStatus::COMPLETED);
                } else {
                    task->setStatus(TaskStatus::FAILED);
                    std::cerr << "Invalid task type or model not available" << std::endl;
                }
                
                auto endTime = std::chrono::high_resolution_clock::now();
                std::chrono::duration<double> elapsed = endTime - startTime;
                totalInferenceTime_ += elapsed.count();
                completedTasksCount_++;
                
                // 更新性能指标
                updateResourceMetrics();
                
            } catch (const std::exception& e) {
                std::cerr << "Error executing LLM task: " << e.what() << std::endl;
                task->setStatus(TaskStatus::FAILED);
            }
        }
        
        // 任务完成
        {
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            currentTasks_--;
            busy_ = taskQueue_.size() > 0;
        }
        
        // 通知任务完成
        taskCompletedCallback_(task);
    }
    
    std::cout << "GPULLMWorker task execution loop stopped" << std::endl;
}

void GPULLMWorker::executeTask(const std::string& prompt, Callback callback) {
    if (!isReady()) {
        if (callback) {
            callback(false, "LLM worker not ready");
        }
        return;
    }
    
    // 创建任务并添加到队列
    TaskItem task;
    task.prompt = prompt;
    task.callback = callback;
    task.id = inference_count_ + 1;
    
    {  
        std::lock_guard<std::mutex> lock(queue_mutex_);
        task_queue_.push(task);
    }
    
    // 通知工作线程
    condition_.notify_one();
}

bool GPULLMWorker::isReady() const {
    return initialized_ && !stop_thread_ && python_inference_func_ != nullptr;
}

void GPULLMWorker::setTemperature(float temperature) {
    temperature_ = std::max(0.0f, std::min(2.0f, temperature));
}

void GPULLMWorker::setMaxTokens(int max_tokens) {
    max_tokens_ = std::max(1, std::min(2048, max_tokens));
}

float GPULLMWorker::getGPUUtilization() {
    return gpu_utilization_;
}

size_t GPULLMWorker::getGPUMemoryUsage() {
    return gpu_memory_usage_;
}

void GPULLMWorker::workerThread() {
    std::cout << "LLM worker thread started" << std::endl;
    
    while (!stop_thread_) {
        TaskItem task;
        bool has_task = false;
        
        {  
            std::unique_lock<std::mutex> lock(queue_mutex_);
            
            // 等待任务或停止信号
            condition_.wait(lock, [this] {
                return stop_thread_ || !task_queue_.empty();
            });
            
            if (stop_thread_) {
                break;
            }
            
            if (!task_queue_.empty()) {
                task = task_queue_.front();
                task_queue_.pop();
                has_task = true;
            }
        }
        
        if (has_task) {
            try {
                std::cout << "Processing LLM task #" << task.id << std::endl;
                
                // 记录开始时间
                auto start_time = std::chrono::high_resolution_clock::now();
                
                // 执行推理
                std::string result;
                if (callPythonInference(task.prompt, result)) {
                    // 记录结束时间
                    auto end_time = std::chrono::high_resolution_clock::now();
                    uint64_t inference_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
                    
                    // 更新统计信息
                    total_inference_time_ += inference_time;
                    inference_count_++;
                    
                    std::cout << "LLM task #" << task.id << " completed in " 
                              << inference_time << "ms" << std::endl;
                    
                    // 回调通知成功
                    if (task.callback) {
                        task.callback(true, result);
                    }
                } else {
                    // 回调通知失败
                    if (task.callback) {
                        task.callback(false, "Inference failed");
                    }
                }
                
            } catch (const std::exception& e) {
                std::cerr << "Exception in LLM worker: " << e.what() << std::endl;
                if (task.callback) {
                    task.callback(false, "Exception: " + std::string(e.what()));
                }
            }
        } else {
            // 短暂休眠避免忙等待
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
    
    std::cout << "LLM worker thread stopped" << std::endl;
}

std::string GPULLMWorker::inferenceInternal(const std::string& prompt) {
    // 这个方法在实际集成时会调用真正的LLM模型
    // 现在返回模拟结果
    std::string result = "This is a simulated LLM response for prompt: " + prompt;
    
    // 模拟GPU推理延迟
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    
    return result;
}

bool GPULLMWorker::initializePythonInterface() {
    std::cout << "Initializing Python interface for worker: " << workerId_ << std::endl;
    try {
        // 这里应该实现Python接口的初始化逻辑
        // 例如: Py_Initialize(), 加载Python模块等
        
        // 示例实现 (实际应用中需要真正调用Python API)
        std::cout << "Setting up Python environment for model: " << modelConfig_.modelPath << std::endl;
        
        // 模拟Python模块加载
        std::cout << "Loading LLM inference module..." << std::endl;
        
        // 设置CUDA设备可见性，确保GPU资源隔离
        std::cout << "Setting CUDA_VISIBLE_DEVICES to: " << modelConfig_.gpuDeviceId << std::endl;
        
        // 设置模拟的函数指针
        python_module_ = reinterpret_cast<void*>(1);  // 非空表示初始化成功
        python_inference_func_ = reinterpret_cast<void*>(2);
        
        std::cout << "Python interface initialized successfully" << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to initialize Python interface: " << e.what() << std::endl;
        return false;
    }
}

void GPULLMWorker::cleanupPythonInterface() {
    std::cout << "Cleaning up Python interface for worker: " << workerId_ << std::endl;
    // 这里应该实现Python接口的清理逻辑
    // 例如: 释放Python对象, Py_Finalize()等
    
    if (python_module_) {
        // 模拟Python模块资源释放
        std::cout << "Releasing Python module resources..." << std::endl;
        python_module_ = nullptr;
        python_inference_func_ = nullptr;
    }
    
    std::cout << "Python interface cleaned up" << std::endl;
}

std::unique_ptr<ILLMModel> GPULLMWorker::loadModelImpl(const LLMModelConfig& config) {
    std::cout << "Loading model: " << config.modelPath << std::endl;
    
    // 创建并初始化模型实例
    class LLMPythonModel : public ILLMModel {
    private:
        LLMModelConfig config_;
        bool ready_ = false;
        
    public:
        explicit LLMPythonModel(const LLMModelConfig& config) : config_(config) {}
        
        ~LLMPythonModel() override {
            if (ready_) {
                shutdown();
            }
        }
        
        bool initialize() override {
            std::cout << "Initializing model with config:" << std::endl;
            std::cout << "  - Model Path: " << config_.modelPath << std::endl;
            std::cout << "  - Model Type: " << config_.modelType << std::endl;
            std::cout << "  - Quantization: " << config_.quantization << std::endl;
            std::cout << "  - GPU Device: " << config_.gpuDeviceId << std::endl;
            std::cout << "  - Max Context: " << config_.maxContextSize << std::endl;
            
            // 模拟模型加载
            std::cout << "Loading model to GPU memory..." << std::endl;
            std::this_thread::sleep_for(std::chrono::seconds(2)); // 模拟加载时间
            
            ready_ = true;
            std::cout << "Model initialized successfully" << std::endl;
            return true;
        }
        
        void shutdown() override {
            if (ready_) {
                std::cout << "Unloading model from GPU memory..." << std::endl;
                std::this_thread::sleep_for(std::chrono::seconds(1)); // 模拟卸载时间
                ready_ = false;
            }
        }
        
        bool isReady() const override {
            return ready_;
        }
        
        LLMInferenceResponse inference(const LLMInferenceRequest& request) override {
            if (!ready_) {
                throw std::runtime_error("Model not ready for inference");
            }
            
            std::cout << "Performing LLM inference:" << std::endl;
            std::cout << "  - Prompt: " << (request.prompt.length() > 50 ? request.prompt.substr(0, 50) + "..." : request.prompt) << std::endl;
            std::cout << "  - Max Tokens: " << request.maxTokens << std::endl;
            std::cout << "  - Temperature: " << request.temperature << std::endl;
            
            // 模拟推理过程
            std::this_thread::sleep_for(std::chrono::milliseconds(500)); // 模拟推理延迟
            
            LLMInferenceResponse response;
            response.text = "This is a simulated response from the LLM model. In a real implementation, this would contain the actual generated text.";
            response.tokensGenerated = 35;
            response.inferenceTimeMs = 500;
            response.error = "";
            response.success = true;
            
            return response;
        }
        
        const LLMModelConfig& getConfig() const override {
            return config_;
        }
    };
    
    auto model = std::make_unique<LLMPythonModel>(config);
    if (!model->initialize()) {
        return nullptr;
    }
    
    return model;
}

bool GPULLMWorker::callPythonInference(const std::string& prompt, std::string& result) {
    try {
        std::cout << "Calling Python inference with prompt:" << std::endl;
        std::cout << "  " << (prompt.length() > 100 ? prompt.substr(0, 100) + "..." : prompt) << std::endl;
        
        // 模拟推理延迟
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        
        // 模拟推理结果
        result = "This is a simulated inference result. In a real implementation, this would contain the actual model output.";
        std::cout << "Inference completed" << std::endl;
        
        // 更新性能指标
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        inference_count_++;
        total_inference_time_ += 0.3f; // 模拟300ms的推理时间
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Error in Python inference: " << e.what() << std::endl;
        return false;
    }
}

// 实现IWorker接口的submitTask方法
bool GPULLMWorker::submitTask(ITaskPtr task) {
    if (!initialized_ || !running_) {
        std::cerr << "Cannot submit task: worker not initialized or stopped" << std::endl;
        return false;
    }
    
    // 验证任务类型
    auto llmTask = std::dynamic_pointer_cast<LLMTask>(task);
    if (!llmTask) {
        std::cerr << "Invalid task type submitted to GPULLMWorker" << std::endl;
        return false;
    }
    
    // 设置任务状态并提交到队列
    llmTask->setStatus(TaskStatus::PENDING);
    llmTask->setWorkerId(workerId_);
    
    {
        std::unique_lock<std::mutex> lock(taskQueueMutex_);
        
        // 检查队列大小限制
        if (taskQueue_.size() >= modelConfig_.maxBatchSize * 2) { // 允许队列中有批处理大小的2倍任务
            std::cerr << "Task queue is full" << std::endl;
            return false;
        }
        
        taskQueue_.push(task);
        std::cout << "Task submitted to GPULLMWorker: " << workerId_ << ", queue size: " << taskQueue_.size() << std::endl;
    }
    
    // 通知执行线程有新任务
    taskQueueCondition_.notify_one();
    
    return true;
}

// 实现IWorker接口的cancelTask方法
bool GPULLMWorker::cancelTask(const std::string& taskId) {
    std::unique_lock<std::mutex> lock(taskQueueMutex_);
    
    // 由于标准queue不支持直接删除中间元素，我们需要重建队列
    std::queue<ITaskPtr> newQueue;
    bool found = false;
    
    while (!taskQueue_.empty()) {
        ITaskPtr task = taskQueue_.front();
        taskQueue_.pop();
        
        if (task->getId() == taskId && task->getStatus() == TaskStatus::PENDING) {
            // 找到任务并取消
            task->setStatus(TaskStatus::CANCELLED);
            found = true;
            std::cout << "Task cancelled: " << taskId << std::endl;
        } else {
            // 保留其他任务
            newQueue.push(task);
        }
    }
    
    // 替换队列
    taskQueue_.swap(newQueue);
    
    return found;
}

// 实现IWorker接口的getWorkerStatus方法
WorkerStatus GPULLMWorker::getWorkerStatus() const {
    std::unique_lock<std::mutex> lock(taskQueueMutex_);
    
    if (!initialized_) {
        return WorkerStatus::UNINITIALIZED;
    }
    
    if (!running_) {
        return WorkerStatus::STOPPED;
    }
    
    if (busy_ || !taskQueue_.empty()) {
        return WorkerStatus::BUSY;
    }
    
    return WorkerStatus::IDLE;
}

// 实现IWorker接口的getWorkerStats方法
WorkerStats GPULLMWorker::getWorkerStats() const {
    std::unique_lock<std::mutex> lock(metrics_mutex_);
    
    WorkerStats stats;
    stats.workerId = workerId_;
    stats.initialized = initialized_;
    stats.running = running_;
    stats.busy = busy_;
    stats.completedTasks = completedTasksCount_;
    stats.currentTasks = currentTasks_;
    stats.totalInferenceTimeMs = totalInferenceTime_ * 1000; // 转换为毫秒
    
    if (completedTasksCount_ > 0) {
        stats.averageInferenceTimeMs = (totalInferenceTime_ / completedTasksCount_) * 1000;
    }
    
    // 获取队列大小
    {
        std::unique_lock<std::mutex> queueLock(taskQueueMutex_);
        stats.queueSize = taskQueue_.size();
    }
    
    // GPU资源使用情况
    stats.gpuUtilization = gpu_utilization_;
    stats.gpuMemoryUsage = gpu_memory_usage_;
    
    return stats;
}

// 预热模型
void GPULLMWorker::warmupModel() {
    if (!model_ || !model_->isReady()) {
        return;
    }
    
    std::cout << "Warming up model..." << std::endl;
    
    // 执行简单的预热推理
    LLMInferenceRequest warmupRequest;
    warmupRequest.prompt = "Hello, this is a warmup prompt.";
    warmupRequest.maxTokens = 10;
    warmupRequest.temperature = 0.0f;
    
    try {
        model_->inference(warmupRequest);
        std::cout << "Model warmup completed" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Error during model warmup: " << e.what() << std::endl;
    }
}

// 更新资源指标
void GPULLMWorker::updateResourceMetrics() {
    // 模拟GPU使用率和内存使用情况
    // 在实际应用中，这里应该调用CUDA API或NVIDIA管理库获取真实数据
    
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    
    // 随机生成模拟数据（实际应用中替换为真实数据）
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_real_distribution<> dist(30.0, 85.0);
    static std::uniform_int_distribution<> memDist(2000, 6000); // MB
    
    gpu_utilization_ = dist(gen);
    gpu_memory_usage_ = memDist(gen);
    
    // 记录最后一次更新时间
    lastMetricsUpdateTime_ = std::chrono::steady_clock::now();
}

// 设置任务完成回调
void GPULLMWorker::setTaskCompletedCallback(const TaskCompletedCallback& callback) {
    taskCompletedCallback_ = callback;
}

// 获取和设置模型配置
const LLMModelConfig& GPULLMWorker::getModelConfig() const {
    return modelConfig_;
}

bool GPULLMWorker::setModelConfig(const LLMModelConfig& config) {
    if (running_) {
        std::cerr << "Cannot change model config while worker is running" << std::endl;
        return false;
    }
    
    modelConfig_ = config;
    
    // 同步到旧的成员变量
    model_path_ = config.modelPath;
    gpu_id_ = config.gpuDeviceId;
    max_context_length_ = config.maxContextSize;
    
    return true;
}

// 创建LLMTask的工厂方法
std::shared_ptr<LLMTask> createLLMTask(const std::string& taskId, const LLMInferenceRequest& request) {
    return std::make_shared<LLMTask>(taskId, request);
}

} // namespace ai_scheduler