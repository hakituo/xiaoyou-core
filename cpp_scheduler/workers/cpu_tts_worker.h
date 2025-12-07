#pragma once

#include "../core/resource_isolation_scheduler.h"
#include <mutex>
#include <string>
#include <atomic>
#include <memory>
#include <vector>
#include <thread>
#include <condition_variable>
#include <queue>

namespace ai_scheduler {

// TTS引擎类型
enum class TTSEngineType {
    COQUI_GLOW_TTS,
    MELOTTS,
    PYTTSX3,
    MOCK
};

// TTS参数结构
struct TTSParams {
    std::string text;
    std::string voice_id;
    float speed;
    float pitch;
    float volume;
    std::string output_format;
    
    // 默认构造函数
    TTSParams()
        : speed(1.0f), pitch(1.0f), volume(1.0f), output_format("wav") {
    }
};

// TTS任务定义
class TTSTask : public ITask {
public:
    TTSTask(const std::string& taskId, TaskPriority priority, const TTSParams& params)
        : ITask(taskId, TaskType::TTS_SYNTHESIS, priority),
          params_(params) {
    }
    
    const TTSParams& getParams() const {
        return params_;
    }
    
    void setAudioOutput(const std::string& outputPath, const std::vector<uint8_t>& audioData) {
        outputPath_ = outputPath;
        audioData_ = audioData;
    }
    
    const std::string& getOutputPath() const {
        return outputPath_;
    }
    
    const std::vector<uint8_t>& getAudioData() const {
        return audioData_;
    }
    
    void setSynthesisTime(uint64_t timeMs) {
        synthesisTimeMs_ = timeMs;
    }
    
    uint64_t getSynthesisTime() const {
        return synthesisTimeMs_;
    }
    
private:
    TTSParams params_;
    std::string outputPath_;
    std::vector<uint8_t> audioData_;
    uint64_t synthesisTimeMs_ = 0;
};

// TTS模型接口
class ITTSModel {
public:
    virtual ~ITTSModel() = default;
    
    virtual bool initialize() = 0;
    virtual void shutdown() = 0;
    virtual bool isReady() const = 0;
    
    virtual bool synthesize(const TTSParams& params, std::string& outputPath, 
                           std::vector<uint8_t>& audioData) = 0;
    
    virtual std::vector<std::string> getAvailableVoices() const = 0;
    
    virtual void setNumThreads(int numThreads) = 0;
    virtual int getNumThreads() const = 0;
};

// CPU TTS Worker类 - 使用CPU进行语音合成，不占用GPU资源
class CPUTTSWorker : public IWorker {
public:
    CPUTTSWorker(const std::string& workerId = "CPU_TTS_Worker", 
                TTSEngineType engineType = TTSEngineType::COQUI_GLOW_TTS,
                int numThreads = 2);
    
    ~CPUTTSWorker() override;
    
    // 实现IWorker接口
    bool initialize() override;
    void shutdown() override;
    void processTask(std::shared_ptr<ITask> task) override;
    bool canHandle(TaskType type) const override;
    std::string getWorkerId() const override;
    bool isBusy() const override;
    
    // 增强的TTS接口
    void synthesize(const TTSParams& params, TaskPriority priority, 
                   std::function<void(std::shared_ptr<TTSTask>)> callback);
    
    // 获取支持的语音列表
    std::vector<std::string> getAvailableVoices() const;
    
    // 设置引擎参数
    void setEngineType(TTSEngineType engineType);
    void setNumThreads(int numThreads);
    
    // 获取性能统计
    float getAverageSynthesisTime() const;
    float getCPUUtilization() const;
    size_t getActiveTasksCount() const;
    size_t getCompletedTasksCount() const;
    
private:
    // 任务执行相关方法
    std::unique_ptr<ITTSModel> createModel(TTSEngineType engineType);
    void processTaskQueue();
    bool synthesizeInternal(const TTSParams& params, std::string& outputPath, 
                           std::vector<uint8_t>& audioData);
    
    // 生成输出文件名
    std::string generateOutputFilename(const std::string& prefix);
    
    // 更新CPU使用率统计
    void updateCPUUtilization();
    
    // 成员变量
    std::string workerId_;
    TTSEngineType engineType_;
    int numThreads_;  // CPU线程数
    
    // 状态管理
    std::atomic<bool> initialized_;
    std::atomic<bool> running_;
    std::atomic<bool> busy_;
    
    // 任务队列
    std::queue<std::shared_ptr<ITask>> taskQueue_;
    mutable std::mutex taskQueueMutex_;
    std::condition_variable taskQueueCondition_;
    
    // 任务执行线程
    std::thread executionThread_;
    
    // 任务计数
    std::atomic<size_t> activeTasksCount_;
    std::atomic<size_t> completedTasksCount_;
    
    // 模型实例
    std::unique_ptr<ITTSModel> model_;
    
    // 性能统计
    std::atomic<uint64_t> totalSynthesisTime_;
    std::atomic<uint64_t> synthesisCount_;
    std::atomic<float> cpuUtilization_;
    
    // 输出目录
    std::string outputDir_;
    
    // 任务完成回调
    std::function<void(std::shared_ptr<ITask>)> taskCompletedCallback_;
};

} // namespace ai_scheduler

#endif // CPU_TTS_WORKER_H