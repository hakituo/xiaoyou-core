#pragma once
#include "../core/resource_isolation_scheduler.h"
#include "../core/biological_system.h"
#include <memory>
#include <string>
#include <atomic>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <chrono>
#include <queue>
#include <thread>
#include <vector>

namespace ai_scheduler {

// Forward declaration
class BiologicalSystem;

// LLM模型配置
struct LLMModelConfig {
    std::string modelPath{};         
    std::string modelType{"mock"}; 
    std::string quantization{};      
    int gpuDeviceId{0};              
    int nGpuLayers{-1};              
    size_t maxContextSize{4096};     
    size_t maxBatchSize{512};        
    float temperature{0.7f};         
    int topK{40};                    
    float topP{0.95f};               
    float repetitionPenalty{1.1f};   
    bool enableCache{true};          
    size_t cacheSize{16};
    std::string draftModelPath{};    // Speculative Decoding Draft Model
    int draftGpuDeviceId{-1};        // -1 for CPU, >=0 for GPU
    int draftContextSize{512};

    bool enableKvSwap{false};
    std::string kvSwapDir{};
    size_t kvSwapTriggerTokens{2048};
};

// LLM推理请求
struct LLMInferenceRequest {
    std::string prompt{};
    std::string conversationId{};
    size_t maxTokens{0};
    float temperature{0.0f};
    int topK{0};
    float topP{0.0f};
    float repetitionPenalty{0.0f};
    bool streamOutput{false};
    std::function<void(const std::string&)> onTokenGenerated{};
    std::function<bool()> shouldStop{};
};

// LLM推理响应
struct LLMInferenceResponse {
    std::string generatedText;     // 生成的文本
    size_t generatedTokens;        // 生成的token数
    float inferenceTime;           // 推理时间（秒）
    bool success;                  // 是否成功
    std::string errorMessage;      // 错误信息
};

// LLM模型接口
class ILLMModel {
public:
    virtual ~ILLMModel() = default;
    virtual bool initialize(const LLMModelConfig& config) = 0;
    virtual void shutdown() = 0;
    virtual LLMInferenceResponse generate(const LLMInferenceRequest& request) = 0;
    virtual std::string getModelInfo() const = 0;
    virtual size_t getMemoryUsage() const = 0;
    virtual bool isReady() const = 0;

    // 清除指定会话的运行时推理缓存。无会话缓存的模型保持幂等成功。
    virtual bool clearConversationCache(const std::string& conversationId) {
        (void)conversationId;
        return true;
    }

    // 批量生成支持：默认顺序执行，子类可覆盖为真实批处理
    virtual std::vector<LLMInferenceResponse> batchGenerate(const std::vector<LLMInferenceRequest>& requests) {
        std::vector<LLMInferenceResponse> responses;
        responses.reserve(requests.size());
        for (const auto& req : requests) {
            responses.push_back(generate(req));
        }
        return responses;
    }
};

// Forward declaration
class GPULLMWorker;

// LLM任务实现
class LLMTask : public ITask {
public:
    LLMTask(const LLMInferenceRequest& request, GPULLMWorker* worker = nullptr)
        : ITask("llm_task_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count()), TaskType::LLM_INFERENCE, TaskPriority::HIGH),
          request_(request), worker_(worker) {
    }
    
    void setWorker(GPULLMWorker* worker) {
        worker_ = worker;
    }

    const LLMInferenceRequest& getRequest() const { return request_; }
    void setResponse(const LLMInferenceResponse& response) { response_ = response; }
    void setErrorMessage(const std::string& msg) { errorMessage_ = msg; }

    // Declared only, defined after GPULLMWorker definition
    void execute() override;
    
    std::shared_ptr<void> getResult() const override {
        if (status_ == TaskStatus::FAILED) {
            throw std::runtime_error(errorMessage_);
        }
        return std::make_shared<LLMInferenceResponse>(response_);
    }
    
    const LLMInferenceResponse& getResponse() const {
        if (status_ == TaskStatus::FAILED) {
            throw std::runtime_error(errorMessage_);
        }
        return response_;
    }

private:
    LLMInferenceRequest request_;
    LLMInferenceResponse response_;
    GPULLMWorker* worker_;
    std::string errorMessage_;
};

// GPU LLM工作器 - 专门处理LLM推理任务，独占GPU pipeline以确保实时响应
class GPULLMWorker : public IWorker {
public:
    GPULLMWorker(const std::string& workerId = "gpu_llm_worker");
    ~GPULLMWorker() override;
    
    // 初始化工作器
    bool initialize() override;
    
    // 关闭工作器
    void shutdown() override;
    
    // 检查是否能处理指定类型的任务
    bool canHandle(TaskType type) const override;
    
    // 处理任务
    void processTask(std::shared_ptr<ITask> task) override;
    
    // 获取工作器ID
    std::string getWorkerId() const override;
    
    // 检查工作器是否忙碌
    bool isBusy() const override;
    
    // 设置模型配置
    void setModelConfig(const LLMModelConfig& config);
    
    // 获取模型配置
    LLMModelConfig getModelConfig() const;
    
    // 执行LLM推理（直接调用接口）
    LLMInferenceResponse executeInference(const LLMInferenceRequest& request);
    
    // 获取GPU使用情况
    float getGpuUtilization() const;
    
    // 获取模型信息
    std::string getModelInfo() const;
    
    // 预热模型
    bool warmupModel(size_t warmupRounds = 3);

    // 清除指定会话的 KV Cache；与推理共用模型锁，避免并发修改上下文。
    bool clearConversationCache(const std::string& conversationId);

    // 设置生物系统
    void setBiologicalSystem(std::shared_ptr<BiologicalSystem> bioSystem) {
        bioSystem_ = bioSystem;
    }
    
private:
    // 加载模型实现
    std::shared_ptr<ILLMModel> loadModelImpl(const LLMModelConfig& config);
    
    // 任务执行循环
    void taskExecutionLoop();
    
    // 处理LLM推理任务
    void processLLMInferenceTask(std::shared_ptr<ITask> task);
    
    // 执行实际的LLM推理
    std::string inferenceInternal(const std::string& prompt);
    
    // Python接口交互函数
    bool initializePythonInterface();
    bool callPythonInference(const std::string& prompt, std::string& result);
    
    // 内部数据
    std::string workerId_;
    std::shared_ptr<ILLMModel> model_;
    LLMModelConfig modelConfig_;
    std::shared_ptr<BiologicalSystem> bioSystem_;
    
    // 任务队列和同步
    std::queue<std::shared_ptr<ITask>> taskQueue_;
    mutable std::mutex queueMutex_;
    mutable std::mutex modelMutex_;
    std::condition_variable cv_;
    
    // 状态标志
    std::atomic<bool> running_;
    std::atomic<bool> initialized_;
    std::atomic<bool> busy_;
    std::atomic<size_t> currentTasks_;
    
    // 性能统计
    std::atomic<size_t> completedTasksCount_;
    std::atomic<float> totalInferenceTime_;
    std::atomic<float> gpu_utilization_;
    
    // 执行线程
    std::thread executionThread_;
    
    // 保留原有成员变量以确保兼容性
    std::string model_path_;
    int gpu_id_;
    size_t max_context_length_;
    float temperature_;
    int max_tokens_;
    
    // Python接口相关
    void* python_module_;  // Python模块指针
    void* python_inference_func_;  // 推理函数指针
};

} // namespace ai_scheduler
