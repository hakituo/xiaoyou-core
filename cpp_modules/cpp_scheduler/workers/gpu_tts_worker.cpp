#include "gpu_tts_worker.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <random>
#include <filesystem>
#include <fstream>
#include <cmath>

namespace ai_scheduler {

GPUTTSWorker::GPUTTSWorker(const std::string& workerId, TTSEngineType engineType, int gpuDeviceId)
    : workerId_(workerId), engineType_(engineType), gpuDeviceId_(gpuDeviceId),
      initialized_(false), running_(false), busy_(false) {
    outputDir_ = "audio_gpu";
}

GPUTTSWorker::~GPUTTSWorker() {
    shutdown();
}

bool GPUTTSWorker::initialize() {
    if (initialized_) return true;

    std::cout << "Initializing GPUTTSWorker: " << workerId_ << " on GPU:" << gpuDeviceId_ << std::endl;

    // 这里在真实实现中会初始化 GPU 版的 TTS 模型
    // 目前使用 Mock 实现
    // model_ = createModel(engineType_); 
    // 为了简单，我们直接在这里模拟
    
    running_ = true;
    executionThread_ = std::thread(&GPUTTSWorker::processTaskQueue, this);

    initialized_ = true;
    return true;
}

void GPUTTSWorker::shutdown() {
    if (!running_) return;

    running_ = false;
    taskQueueCondition_.notify_all();

    if (executionThread_.joinable()) {
        executionThread_.join();
    }

    initialized_ = false;
}

void GPUTTSWorker::processTask(std::shared_ptr<ITask> task) {
    if (!task) return;
    
    {
        std::lock_guard<std::mutex> lock(taskQueueMutex_);
        taskQueue_.push(task);
    }
    taskQueueCondition_.notify_one();
}

bool GPUTTSWorker::canHandle(TaskType type) const {
    return type == TaskType::TTS_SYNTHESIS;
}

std::string GPUTTSWorker::getWorkerId() const {
    return workerId_;
}

bool GPUTTSWorker::isBusy() const {
    return busy_ || !taskQueue_.empty();
}

void GPUTTSWorker::setGpuDeviceId(int deviceId) {
    gpuDeviceId_ = deviceId;
}

int GPUTTSWorker::getGpuDeviceId() const {
    return gpuDeviceId_;
}

size_t GPUTTSWorker::getGPUMemoryUsage() const {
    // 模拟 GPU 显存占用（例如 1GB）
    return 1024 * 1024 * 1024;
}

void GPUTTSWorker::processTaskQueue() {
    while (running_) {
        std::shared_ptr<ITask> task;
        
        {
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            taskQueueCondition_.wait(lock, [this] {
                return !running_ || !taskQueue_.empty();
            });
            
            if (!running_) break;
            
            task = taskQueue_.front();
            taskQueue_.pop();
        }
        
        if (task) {
            busy_ = true;
            task->setStatus(TaskStatus::RUNNING);
            
            auto ttsTask = std::dynamic_pointer_cast<TTSTask>(task);
            if (ttsTask) {
                std::string outputPath;
                std::vector<uint8_t> audioData;
                
                auto start = std::chrono::steady_clock::now();
                bool success = synthesizeInternal(ttsTask->getParams(), outputPath, audioData);
                auto end = std::chrono::steady_clock::now();
                
                if (success) {
                    ttsTask->setAudioOutput(outputPath, audioData);
                    ttsTask->setSynthesisTime(std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count());
                    ttsTask->setStatus(TaskStatus::COMPLETED);
                    std::cout << "[GPUTTSWorker] Task completed: " << ttsTask->getTaskId() << " in " << ttsTask->getSynthesisTime() << "ms" << std::endl;
                } else {
                    ttsTask->setStatus(TaskStatus::FAILED);
                }
            } else {
                task->setStatus(TaskStatus::FAILED);
            }
            
            busy_ = false;
        }
    }
}

bool GPUTTSWorker::synthesizeInternal(const TTSParams& params, std::string& outputPath, 
                                     std::vector<uint8_t>& audioData) {
    // 模拟 GPU 合成耗时（通常比 CPU 快）
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    
    outputPath = outputDir_ + "/gpu_audio.wav";
    audioData.resize(1024); // Dummy data
    return true;
}

} // namespace ai_scheduler
