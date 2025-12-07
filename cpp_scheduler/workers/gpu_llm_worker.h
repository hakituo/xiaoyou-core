#pragma once
#include "../core/resource_isolation_scheduler.h"
#include <memory>
#include <string>
#include <atomic>
#include <mutex>
#include <condition_variable>
#include <functional>

// LLM模型配置
struct LLMModelConfig {
    std::string modelPath;         // 模型路径
    std::string modelType;         // 模型类型 (e.g., "qwen", "llama")
    std::string quantization;      // 量化级别 (e.g., "q4_0", "q8_0")
    int gpuDeviceId;               // GPU设备ID
    size_t maxContextSize;         // 最大上下文长度
    size_t maxBatchSize;           // 最大批处理大小
    float temperature;             // 默认温度
    int topK;                      // top-k参数
    float topP;                    // top-p参数
    float repetitionPenalty;       // 重复惩罚
    bool enableCache;              // 是否启用缓存
    size_t cacheSize;              // 缓存大小
};

// LLM推理请求
struct LLMInferenceRequest {
    std::string prompt;            // 提示文本
    size_t maxTokens;              // 最大生成token数
    float temperature;             // 温度
    int topK;                      // top-k参数
    float topP;                    // top-p参数
    float repetitionPenalty;       // 重复惩罚
    bool streamOutput;             // 是否流式输出
    std::function<void(const std::string&)> onTokenGenerated;  // token生成回调
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
};

// LLM任务实现
class LLMTask : public ITask {
public:
    LLMTask(const LLMInferenceRequest& request, GPULLMWorker* worker)
        : request_(request), worker_(worker), status_(TaskStatus::PENDING), 
          priority_(TaskPriority::HIGH), type_(TaskType::LLM_INFERENCE) {
        // 生成唯一任务ID
        taskId_ = "llm_task_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
    }
    
    void execute() override {
        if (worker_) {
            try {
                setStatus(TaskStatus::RUNNING);
                response_ = worker_->executeInference(request_);
                
                if (response_.success) {
                    setStatus(TaskStatus::COMPLETED);
                } else {
                    setStatus(TaskStatus::FAILED);
                    errorMessage_ = response_.errorMessage;
                }
            } catch (const std::exception& e) {
                setStatus(TaskStatus::FAILED);
                errorMessage_ = e.what();
            }
        } else {
            setStatus(TaskStatus::FAILED);
            errorMessage_ = "Worker not available";
        }
    }
    
    TaskType getType() const override { return type_; }
    TaskPriority getPriority() const override { return priority_; }
    TaskStatus getStatus() const override { return status_; }
    void setStatus(TaskStatus status) override { status_ = status; }
    std::string getTaskId() const override { return taskId_; }
    
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
    TaskStatus status_;
    TaskPriority priority_;
    TaskType type_;
    std::string taskId_;
    std::string errorMessage_;
};

namespace ai_scheduler {

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
    
    // 资源监控
    std::atomic<float> gpu_utilization_;
    std::atomic<size_t> gpu_memory_usage_;
    
    // 性能统计
    std::atomic<uint64_t> total_inference_time_;
    std::atomic<uint64_t> inference_count_;
};

} // namespace ai_scheduler

#endif // GPU_LLM_WORKER_H