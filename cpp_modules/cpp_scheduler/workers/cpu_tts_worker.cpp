#include "cpu_tts_worker.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <random>
#include <filesystem>
#include <fstream>
#include <cmath>

namespace ai_scheduler {

// Mock TTS Model Implementation
class MockTTSModel : public ITTSModel {
public:
    MockTTSModel(TTSEngineType type) : type_(type), ready_(false) {}

    bool initialize() override {
        std::cout << "Initializing MockTTSModel (" << static_cast<int>(type_) << ")..." << std::endl;
        ready_ = true;
        return true;
    }

    void shutdown() override {
        ready_ = false;
        std::cout << "MockTTSModel shutdown" << std::endl;
    }

    bool isReady() const override { return ready_; }

    bool synthesize(const TTSParams& params, std::string& outputPath, 
                   std::vector<uint8_t>& audioData) override {
        if (!ready_) return false;

        std::cout << "MockTTSModel synthesizing: " << params.text.substr(0, 50) << "..." << std::endl;
        
        // Simulate processing time
        std::this_thread::sleep_for(std::chrono::milliseconds(200));

        // Generate dummy audio data
        outputPath = "mock_audio.wav";
        audioData.resize(44100 * 2); // 2 seconds of dummy data
        for (size_t i = 0; i < audioData.size(); ++i) {
            audioData[i] = static_cast<uint8_t>(std::sin(i * 0.1) * 127 + 128);
        }
        return true;
    }

    std::vector<std::string> getAvailableVoices() const override {
        return {"mock-voice-1", "mock-voice-2"};
    }

    void setNumThreads(int numThreads) override {
        // Do nothing
    }

    int getNumThreads() const override { return 1; }

private:
    TTSEngineType type_;
    bool ready_;
};

// CPUTTSWorker Implementation
CPUTTSWorker::CPUTTSWorker(const std::string& workerId, TTSEngineType engineType, int numThreads)
    : workerId_(workerId), engineType_(engineType), numThreads_(numThreads),
      initialized_(false), running_(false), busy_(false),
      activeTasksCount_(0), completedTasksCount_(0),
      totalSynthesisTime_(0), synthesisCount_(0), cpuUtilization_(0.0f) {
    outputDir_ = "audio";
}

CPUTTSWorker::~CPUTTSWorker() {
    shutdown();
}

bool CPUTTSWorker::initialize() {
    if (initialized_) return true;

    std::cout << "Initializing CPUTTSWorker: " << workerId_ << std::endl;

    model_ = createModel(engineType_);
    if (!model_ || !model_->initialize()) {
        std::cerr << "Failed to initialize TTS model" << std::endl;
        return false;
    }

    running_ = true;
    executionThread_ = std::thread(&CPUTTSWorker::processTaskQueue, this);

    initialized_ = true;
    return true;
}

void CPUTTSWorker::shutdown() {
    if (!running_) return;

    running_ = false;
    taskQueueCondition_.notify_all();

    if (executionThread_.joinable()) {
        executionThread_.join();
    }

    if (model_) {
        model_->shutdown();
    }

    initialized_ = false;
}

void CPUTTSWorker::processTask(std::shared_ptr<ITask> task) {
    if (!task) return;
    
    {
        std::lock_guard<std::mutex> lock(taskQueueMutex_);
        taskQueue_.push(task);
    }
    taskQueueCondition_.notify_one();
}

bool CPUTTSWorker::canHandle(TaskType type) const {
    return type == TaskType::TTS_SYNTHESIS;
}

std::string CPUTTSWorker::getWorkerId() const {
    return workerId_;
}

bool CPUTTSWorker::isBusy() const {
    return busy_ || !taskQueue_.empty();
}

void CPUTTSWorker::setTaskCompletedCallback(TaskCompletedCallback callback) {
    taskCompletedCallback_ = callback;
}

void CPUTTSWorker::synthesize(const TTSParams& params, TaskPriority priority, 
                             std::function<void(std::shared_ptr<TTSTask>)> callback) {
    if (!initialized_) return;

    auto task = std::make_shared<TTSTask>(
        "tts_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count()),
        priority,
        params
    );
    
    if (callback) {
        task->setCallback(callback);
    }
    
    processTask(task);
}

std::vector<std::string> CPUTTSWorker::getAvailableVoices() const {
    if (model_) return model_->getAvailableVoices();
    return {};
}

void CPUTTSWorker::setEngineType(TTSEngineType engineType) {
    engineType_ = engineType;
    if (initialized_) {
        // Re-init model
        model_->shutdown();
        model_ = createModel(engineType_);
        model_->initialize();
    }
}

void CPUTTSWorker::setNumThreads(int numThreads) {
    numThreads_ = numThreads;
    if (model_) model_->setNumThreads(numThreads);
}

float CPUTTSWorker::getAverageSynthesisTime() const {
    if (synthesisCount_ == 0) return 0.0f;
    return static_cast<float>(totalSynthesisTime_) / synthesisCount_;
}

float CPUTTSWorker::getCPUUtilization() const {
    return cpuUtilization_;
}

size_t CPUTTSWorker::getActiveTasksCount() const {
    return activeTasksCount_;
}

size_t CPUTTSWorker::getCompletedTasksCount() const {
    return completedTasksCount_;
}

std::unique_ptr<ITTSModel> CPUTTSWorker::createModel(TTSEngineType engineType) {
    return std::make_unique<MockTTSModel>(engineType);
}

void CPUTTSWorker::processTaskQueue() {
    while (running_) {
        std::shared_ptr<ITask> task;

        {
            std::unique_lock<std::mutex> lock(taskQueueMutex_);
            taskQueueCondition_.wait(lock, [this] { return !taskQueue_.empty() || !running_; });

            if (!running_) break;

            if (!taskQueue_.empty()) {
                task = taskQueue_.front();
                taskQueue_.pop();
            }
        }

        if (task) {
            auto ttsTask = std::dynamic_pointer_cast<TTSTask>(task);
            if (ttsTask) {
                busy_ = true;
                activeTasksCount_++;
                ttsTask->setStatus(TaskStatus::RUNNING);

                std::string outputPath;
                std::vector<uint8_t> audioData;
                
                bool success = synthesizeInternal(ttsTask->getParams(), outputPath, audioData);

                if (success) {
                    ttsTask->setAudioOutput(outputPath, audioData);
                    ttsTask->setStatus(TaskStatus::COMPLETED);
                } else {
                    ttsTask->setStatus(TaskStatus::FAILED);
                }

                activeTasksCount_--;
                completedTasksCount_++;
                busy_ = false;

                // Run per-task callback
                ttsTask->runCallback(ttsTask);

                if (taskCompletedCallback_) {
                    taskCompletedCallback_(task);
                }
            }
        }
    }
}

bool CPUTTSWorker::synthesizeInternal(const TTSParams& params, std::string& outputPath, 
                                     std::vector<uint8_t>& audioData) {
    if (!model_) return false;

    auto start = std::chrono::high_resolution_clock::now();
    bool result = model_->synthesize(params, outputPath, audioData);
    auto end = std::chrono::high_resolution_clock::now();

    std::chrono::duration<float> duration = end - start;
    
    totalSynthesisTime_ += static_cast<uint64_t>(duration.count() * 1000);
    synthesisCount_++;
    updateCPUUtilization();

    return result;
}

std::string CPUTTSWorker::generateOutputFilename(const std::string& prefix) {
    return outputDir_ + "/" + prefix + ".wav";
}

void CPUTTSWorker::updateCPUUtilization() {
    cpuUtilization_ = 0.3f; // Mock
}

} // namespace ai_scheduler
