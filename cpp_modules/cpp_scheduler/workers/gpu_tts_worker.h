#pragma once

#include "../core/resource_isolation_scheduler.h"
#include "cpu_tts_worker.h"
#include <mutex>
#include <string>
#include <atomic>
#include <memory>
#include <vector>
#include <thread>
#include <condition_variable>
#include <queue>

namespace ai_scheduler {

// GPU TTS Worker类 - 使用GPU进行语音合成
class GPUTTSWorker : public IWorker {
public:
    GPUTTSWorker(const std::string& workerId = "GPU_TTS_Worker",
                TTSEngineType engineType = TTSEngineType::COQUI_GLOW_TTS,
                int gpuDeviceId = 0);

    ~GPUTTSWorker() override;

    // 实现IWorker接口
    bool initialize() override;
    void shutdown() override;
    void processTask(std::shared_ptr<ITask> task) override;
    bool canHandle(TaskType type) const override;
    std::string getWorkerId() const override;
    bool isBusy() const override;

    // 设置设备ID
    void setGpuDeviceId(int deviceId);
    int getGpuDeviceId() const;

    // 获取GPU显存占用统计
    size_t getGPUMemoryUsage() const;

private:
    void processTaskQueue();
    bool synthesizeInternal(const TTSParams& params, std::string& outputPath,
                           std::vector<uint8_t>& audioData);

    std::string workerId_;
    TTSEngineType engineType_;
    int gpuDeviceId_;

    std::atomic<bool> initialized_;
    std::atomic<bool> running_;
    std::atomic<bool> busy_;

    std::queue<std::shared_ptr<ITask>> taskQueue_;
    mutable std::mutex taskQueueMutex_;
    std::condition_variable taskQueueCondition_;

    std::thread executionThread_;

    std::unique_ptr<ITTSModel> model_;

    std::string outputDir_;
};

} // namespace ai_scheduler
