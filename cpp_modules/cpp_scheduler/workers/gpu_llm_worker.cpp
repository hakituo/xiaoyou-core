#include "gpu_llm_worker.h"
#include "llama_model_impl.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <stdexcept>

namespace ai_scheduler {

// LLMTask implementation
void LLMTask::execute() {
    if (status_ == TaskStatus::CANCELLED) {
        response_.success = false;
        response_.errorMessage = "任务已取消";
        return;
    }

    request_.shouldStop = [this]() {
        return this->status_ == TaskStatus::CANCELLED;
    };

    status_ = TaskStatus::RUNNING;
    try {
        if (!worker_) {
            throw std::runtime_error("Worker not assigned");
        }
        
        // Execute inference using the worker
        response_ = worker_->executeInference(request_);

        if (status_ == TaskStatus::CANCELLED) {
            response_.success = false;
            response_.errorMessage = "任务已取消";
            return;
        }
        
        if (response_.success) {
            status_ = TaskStatus::COMPLETED;
        } else {
            status_ = TaskStatus::FAILED;
            errorMessage_ = response_.errorMessage;
        }
    } catch (const std::exception& e) {
        if (status_ == TaskStatus::CANCELLED) {
            response_.success = false;
            response_.errorMessage = "任务已取消";
        } else {
            status_ = TaskStatus::FAILED;
            errorMessage_ = e.what();
        }
    }
}

// Mock implementation of ILLMModel
class MockLLMModel : public ILLMModel {
public:
    MockLLMModel() : ready_(false) {}
    
    bool initialize(const LLMModelConfig& config) override {
        config_ = config;
        std::cout << "Initializing MockLLMModel with path: " << config.modelPath << std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(500)); // Simulate loading
        ready_ = true;
        return true;
    }

    void shutdown() override {
        ready_ = false;
        std::cout << "MockLLMModel shutdown" << std::endl;
    }

    LLMInferenceResponse generate(const LLMInferenceRequest& request) override {
        if (!ready_) {
            return { "", 0, 0.0f, false, "Model not ready" };
        }

        if (request.shouldStop && request.shouldStop()) {
            return { "", 0, 0.0f, false, "Cancelled" };
        }

        std::cout << "MockLLMModel generating response for: " << request.prompt.substr(0, 50) << "..." << std::endl;

        const size_t max_tokens = request.maxTokens > 0 ? request.maxTokens : 32;
        auto start = std::chrono::high_resolution_clock::now();

        LLMInferenceResponse response;
        response.generatedText.reserve(64 + request.prompt.size());
        response.generatedText = "Mock response to: ";

        for (size_t i = 0; i < max_tokens; i++) {
            if (request.shouldStop && request.shouldStop()) {
                auto end = std::chrono::high_resolution_clock::now();
                std::chrono::duration<float> duration = end - start;
                response.generatedTokens = i;
                response.inferenceTime = duration.count();
                response.success = false;
                response.errorMessage = "Cancelled";
                return response;
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(20));

            if (request.streamOutput && request.onTokenGenerated) {
                request.onTokenGenerated("Mock ");
            }

            response.generatedText.append("Mock ");
        }

        response.generatedText.append("prompt: ");
        response.generatedText.append(request.prompt);
        response.generatedTokens = max_tokens;
        auto end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<float> duration = end - start;
        response.inferenceTime = duration.count();
        response.success = true;

        return response;
    }

    std::string getModelInfo() const override {
        return "MockLLMModel/v1.0";
    }

    size_t getMemoryUsage() const override {
        return 1024 * 1024 * 1024; // 1GB
    }

    bool isReady() const override {
        return ready_;
    }

private:
    bool ready_;
    LLMModelConfig config_;
};

GPULLMWorker::GPULLMWorker(const std::string& workerId)
    : workerId_(workerId), 
      running_(false), 
      initialized_(false), 
      busy_(false), 
      currentTasks_(0), 
      completedTasksCount_(0), 
      totalInferenceTime_(0.0f),
      gpu_utilization_(0.0f) {
    
    // Default config
    modelConfig_.modelPath = "models/mock-llm";
    modelConfig_.modelType = "mock";
    modelConfig_.gpuDeviceId = 0;
}

GPULLMWorker::~GPULLMWorker() {
    shutdown();
}

bool GPULLMWorker::initialize() {
    if (initialized_) return true;
    
    std::cout << "Initializing GPULLMWorker: " << workerId_ << std::endl;
    
    if (!initializePythonInterface()) {
        std::cerr << "Warning: Python interface init failed, using mock" << std::endl;
    }

    model_ = loadModelImpl(modelConfig_);
    if (!model_) {
        std::cerr << "Failed to load model" << std::endl;
        return false;
    }

    running_ = true;
    executionThread_ = std::thread(&GPULLMWorker::taskExecutionLoop, this);
    
    initialized_ = true;
    return true;
}

void GPULLMWorker::shutdown() {
    if (!running_) return;
    
    running_ = false;
    cv_.notify_all();
    
    if (executionThread_.joinable()) {
        executionThread_.join();
    }
    
    if (model_) {
        model_->shutdown();
    }
    
    initialized_ = false;
}

bool GPULLMWorker::canHandle(TaskType type) const {
    return type == TaskType::LLM_INFERENCE;
}

void GPULLMWorker::processTask(std::shared_ptr<ITask> task) {
    if (!task) return;
    
    // Set worker if it's an LLMTask
    if (task->getType() == TaskType::LLM_INFERENCE) {
        auto llmTask = std::dynamic_pointer_cast<LLMTask>(task);
        if (llmTask) {
            llmTask->setWorker(this);
        }
    }
    
    {
        std::lock_guard<std::mutex> lock(queueMutex_);
        taskQueue_.push(task);
    }
    cv_.notify_one();
}

std::string GPULLMWorker::getWorkerId() const {
    return workerId_;
}

bool GPULLMWorker::isBusy() const {
    return busy_ || !taskQueue_.empty(); // Simple heuristic
}

void GPULLMWorker::setModelConfig(const LLMModelConfig& config) {
    modelConfig_ = config;
}

LLMModelConfig GPULLMWorker::getModelConfig() const {
    return modelConfig_;
}

LLMInferenceResponse GPULLMWorker::executeInference(const LLMInferenceRequest& request) {
    std::lock_guard<std::mutex> lock(modelMutex_);
    if (!model_ || !model_->isReady()) {
        return { "", 0, 0.0f, false, "Model not ready" };
    }

    busy_ = true;
    auto start = std::chrono::high_resolution_clock::now();
    
    LLMInferenceResponse response = model_->generate(request);
    
    auto end = std::chrono::high_resolution_clock::now();
    std::chrono::duration<float> duration = end - start;
    
    totalInferenceTime_ = totalInferenceTime_ + duration.count();
    completedTasksCount_++;
    busy_ = false;
    
    return response;
}

float GPULLMWorker::getGpuUtilization() const {
    return gpu_utilization_;
}

std::string GPULLMWorker::getModelInfo() const {
    return model_ ? model_->getModelInfo() : "No model loaded";
}

bool GPULLMWorker::warmupModel(size_t warmupRounds) {
    if (!model_) return false;
    // Mock warmup
    return true;
}

bool GPULLMWorker::clearConversationCache(const std::string& conversationId) {
    std::lock_guard<std::mutex> lock(modelMutex_);
    if (!model_ || !model_->isReady()) {
        return false;
    }
    return model_->clearConversationCache(conversationId);
}

std::shared_ptr<ILLMModel> GPULLMWorker::loadModelImpl(const LLMModelConfig& config) {
    std::shared_ptr<ILLMModel> model;

    if (config.modelType == "mock") {
        std::cout << "Loading Mock LLM Model..." << std::endl;
        model = std::make_shared<MockLLMModel>();
        model->initialize(config);
        return model;
    }

    std::cout << "Loading LlamaCpp Model..." << std::endl;
    model = std::make_shared<LlamaCppModel>();
    if (model->initialize(config)) {
        return model;
    }

    // 真实模型加载失败时回退到 mock，避免整个 worker 不可用
    std::cerr << "Failed to initialize LlamaCppModel, falling back to Mock" << std::endl;
    auto mock = std::make_shared<MockLLMModel>();
    mock->initialize(config);
    return mock;
}

void GPULLMWorker::taskExecutionLoop() {
    const size_t maxBatchSize = 4; // 动态批处理上限

    while (running_) {
        std::vector<std::shared_ptr<ITask>> batchTasks;

        {
            std::unique_lock<std::mutex> lock(queueMutex_);
            cv_.wait(lock, [this] { return !taskQueue_.empty() || !running_; });

            if (!running_) break;

            // 动态批处理：一次最多取 maxBatchSize 个任务
            size_t batchSize = 0;
            while (!taskQueue_.empty() && batchSize < maxBatchSize) {
                batchTasks.push_back(taskQueue_.front());
                taskQueue_.pop();
                batchSize++;
            }
        }

        if (batchTasks.empty()) continue;

        // 分离 LLM 任务和其他任务
        std::vector<LLMInferenceRequest> llmRequests;
        std::vector<std::shared_ptr<LLMTask>> llmTaskPtrs;
        std::vector<std::shared_ptr<ITask>> otherTasks;

        for (auto& t : batchTasks) {
            auto llmTask = std::dynamic_pointer_cast<LLMTask>(t);
            if (llmTask) {
                llmTask->setStatus(TaskStatus::RUNNING);
                llmTaskPtrs.push_back(llmTask);
                llmRequests.push_back(llmTask->getRequest());
            } else {
                otherTasks.push_back(t);
            }
        }

        // 批处理 LLM 推理
        if (!llmRequests.empty() && model_) {
            std::lock_guard<std::mutex> lock(modelMutex_);
            busy_ = true;
            auto responses = model_->batchGenerate(llmRequests);
            busy_ = false;

            for (size_t i = 0; i < responses.size() && i < llmTaskPtrs.size(); ++i) {
                llmTaskPtrs[i]->setResponse(responses[i]);
                if (responses[i].success) {
                    llmTaskPtrs[i]->setStatus(TaskStatus::COMPLETED);
                    completedTasksCount_++;
                } else {
                    llmTaskPtrs[i]->setErrorMessage(responses[i].errorMessage);
                    llmTaskPtrs[i]->setStatus(TaskStatus::FAILED);
                }
            }
        } else if (!llmRequests.empty() && !model_) {
            // 模型未加载，全部失败
            for (auto& task : llmTaskPtrs) {
                task->setErrorMessage("Model not initialized");
                task->setStatus(TaskStatus::FAILED);
            }
        }

        // 非 LLM 任务走原有路径
        for (auto& t : otherTasks) {
            currentTasks_++;
            processLLMInferenceTask(t);
            currentTasks_--;
        }
    }
}

void GPULLMWorker::processLLMInferenceTask(std::shared_ptr<ITask> task) {
    // Cast to LLMTask is done in LLMTask::execute, but here we invoke execute()
    // Wait, ITask::execute() is virtual.
    try {
        if (task->getStatus() == TaskStatus::CANCELLED) {
            return;
        }
        task->execute();
    } catch (const std::exception& e) {
        std::cerr << "Task execution failed: " << e.what() << std::endl;
        task->setStatus(TaskStatus::FAILED);
    }
}

std::string GPULLMWorker::inferenceInternal(const std::string& prompt) {
    // Legacy helper
    LLMInferenceRequest req;
    req.prompt = prompt;
    LLMInferenceResponse resp = executeInference(req);
    return resp.generatedText;
}

bool GPULLMWorker::initializePythonInterface() {
    // Mock
    return true;
}

bool GPULLMWorker::callPythonInference(const std::string& prompt, std::string& result) {
    // Mock
    result = inferenceInternal(prompt);
    return true;
}

} // namespace ai_scheduler
