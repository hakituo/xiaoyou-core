#include "gpu_img_worker.h"
#include <iostream>
#include <fstream>
#include <chrono>
#include <random>
#include <filesystem>
#include <sstream>
#include <thread>
#include <stdexcept>
#include <cstring>

namespace ai_scheduler {

// GPUImgWorker构造函数
GPUImgWorker::GPUImgWorker(const std::string& workerId, ImgEngineType engineType, int gpuDeviceId)
    : workerId_(workerId.empty() ? "GPU_IMG_Worker" : workerId),
      engineType_(engineType),
      gpuDeviceId_(gpuDeviceId),
      initialized_(false),
      running_(false),
      busy_(false),
      activeTasksCount_(0),
      completedTasksCount_(0),
      failedTasksCount_(0),
      totalGenerationTime_(0),
      generationCount_(0),
      gpuUtilization_(0.0f),
      avgInferenceSteps_(0.0f) {
    // 创建输出目录
    outputDir_ = std::filesystem::temp_directory_path().string() + "/img_output";
    std::filesystem::create_directories(outputDir_);
    
    // 设置默认的任务完成回调
    taskCompletedCallback_ = [](std::shared_ptr<ITask>) {
        // 默认不做任何处理
    };
    
    // 设置默认的进度回调
    progressCallback_ = [](const std::string&, float) {
        // 默认不做任何处理
    };
}

// GPUImgWorker析构函数
GPUImgWorker::~GPUImgWorker() {
    if (initialized_) {
        shutdown();
    }
}

// 初始化方法
bool GPUImgWorker::initialize() {
    if (initialized_) {
        return true;
    }
    
    std::cout << "[GPU_IMG_Worker] " << workerId_ << " Initializing with engine: " 
              << static_cast<int>(engineType_) << " on GPU: " << gpuDeviceId_ << std::endl;
    
    try {
        // 创建并初始化图像生成模型
        model_ = createModel(engineType_);
        if (!model_) {
            std::cerr << "[GPU_IMG_Worker] Failed to create model" << std::endl;
            return false;
        }
        
        // 设置GPU设备ID
        model_->setGpuDeviceId(gpuDeviceId_);
        
        // 初始化模型
        if (!model_->initialize()) {
            std::cerr << "[GPU_IMG_Worker] Failed to initialize model" << std::endl;
            return false;
        }
        
        // 启动任务执行线程
        running_ = true;
        executionThread_ = std::thread(&GPUImgWorker::processTaskQueue, this);
        
        initialized_ = true;
        std::cout << "[GPU_IMG_Worker] " << workerId_ << " Initialized successfully" << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "[GPU_IMG_Worker] Exception during initialization: " << e.what() << std::endl;
        return false;
    }
}

// 关闭方法
void GPUImgWorker::shutdown() {
    if (!initialized_ || !running_) {
        return;
    }
    
    std::cout << "[GPU_IMG_Worker] " << workerId_ << " Shutting down..." << std::endl;
    
    // 设置停止标志
    { 
        std::lock_guard<std::mutex> lock(taskMutex_);
        running_ = false;
        // 通知所有等待的线程
        taskCondition_.notify_all();
    }
    
    // 等待任务执行线程结束
    if (executionThread_.joinable()) {
        executionThread_.join();
    }
    
    // 清理模型资源
    if (model_) {
        model_->cleanup();
        model_ = nullptr;
    }
    
    // 清理任务队列
    { 
        std::lock_guard<std::mutex> lock(taskMutex_);
        taskQueue_.clear();
    }
    
    initialized_ = false;
    std::cout << "[GPU_IMG_Worker] " << workerId_ << " Shutdown completed" << std::endl;
}

// 提交任务方法
std::string GPUImgWorker::submitTask(const std::shared_ptr<ITask>& task) {
    if (!initialized_ || !running_) {
        std::cerr << "[GPU_IMG_Worker] Cannot submit task: worker not initialized" << std::endl;
        return "";
    }
    
    auto imgTask = std::dynamic_pointer_cast<ImgTask>(task);
    if (!imgTask) {
        std::cerr << "[GPU_IMG_Worker] Invalid task type: must be ImgTask" << std::endl;
        return "";
    }
    
    // 设置任务初始状态
    imgTask->setStatus(TaskStatus::QUEUED);
    imgTask->setProgress(0.0f);
    
    // 将任务加入队列
    { 
        std::lock_guard<std::mutex> lock(taskMutex_);
        taskQueue_.push(task);
    }
    
    // 通知处理线程
    taskCondition_.notify_one();
    
    std::cout << "[GPU_IMG_Worker] Task " << imgTask->getTaskId() 
              << " submitted with prompt: " << imgTask->getPrompt() << std::endl;
    return imgTask->getTaskId();
}

// 取消任务方法
bool GPUImgWorker::cancelTask(const std::string& taskId) {
    bool found = false;
    
    { 
        std::lock_guard<std::mutex> lock(taskMutex_);
        // 创建新队列，排除要取消的任务
        std::queue<std::shared_ptr<ITask>> newQueue;
        
        while (!taskQueue_.empty()) {
            auto task = taskQueue_.front();
            taskQueue_.pop();
            
            if (task->getTaskId() == taskId) {
                task->setStatus(TaskStatus::CANCELLED);
                found = true;
                std::cout << "[GPU_IMG_Worker] Task " << taskId << " cancelled" << std::endl;
            } else {
                newQueue.push(task);
            }
        }
        
        // 替换原队列
        taskQueue_ = std::move(newQueue);
    }
    
    return found;
}

// 获取worker状态
WorkerStatus GPUImgWorker::getWorkerStatus() const {
    if (!initialized_) {
        return WorkerStatus::UNINITIALIZED;
    }
    
    if (!running_) {
        return WorkerStatus::STOPPED;
    }
    
    return busy_ ? WorkerStatus::BUSY : WorkerStatus::READY;
}

// 获取worker统计信息
std::map<std::string, std::string> GPUImgWorker::getWorkerStats() const {
    std::map<std::string, std::string> stats;
    stats["worker_id"] = workerId_;
    stats["engine_type"] = std::to_string(static_cast<int>(engineType_));
    stats["gpu_device_id"] = std::to_string(gpuDeviceId_);
    stats["active_tasks"] = std::to_string(activeTasksCount_);
    stats["completed_tasks"] = std::to_string(completedTasksCount_);
    stats["failed_tasks"] = std::to_string(failedTasksCount_);
    stats["gpu_utilization"] = std::to_string(gpuUtilization_);
    
    // 计算平均生成时间
    if (generationCount_ > 0) {
        float avg_time = static_cast<float>(totalGenerationTime_) / generationCount_;
        stats["avg_generation_time_ms"] = std::to_string(avg_time);
        stats["avg_inference_steps"] = std::to_string(avgInferenceSteps_);
    } else {
        stats["avg_generation_time_ms"] = "0";
        stats["avg_inference_steps"] = "0";
    }
    
    return stats;
}

// 设置任务完成回调
void GPUImgWorker::setTaskCompletedCallback(TaskCompletedCallback callback) {
    std::lock_guard<std::mutex> lock(callbackMutex_);
    taskCompletedCallback_ = callback;
}

// 任务队列处理函数
void GPUImgWorker::processTaskQueue() {
    while (running_) {
        std::shared_ptr<ITask> task;
        
        // 等待任务
        { 
            std::unique_lock<std::mutex> lock(taskMutex_);
            taskCondition_.wait(lock, [this] { 
                return !running_ || !taskQueue_.empty(); 
            });
            
            if (!running_ && taskQueue_.empty()) {
                break;
            }
            
            if (taskQueue_.empty()) {
                continue;
            }
            
            task = std::move(taskQueue_.front());
            taskQueue_.pop();
        }
        
        // 处理任务
        try {
            busy_ = true;
            activeTasksCount_++;
            
            // 执行图像生成
            auto imgTask = std::dynamic_pointer_cast<ImgTask>(task);
            if (imgTask) {
                imgTask->setStatus(TaskStatus::PROCESSING);
                bool success = processTask(imgTask);
                
                if (success) {
                    imgTask->setStatus(TaskStatus::COMPLETED);
                    completedTasksCount_++;
                    
                    // 调用完成回调
                    if (taskCompletedCallback_) {
                        taskCompletedCallback_(task);
                    }
                } else {
                    imgTask->setStatus(TaskStatus::FAILED);
                    failedTasksCount_++;
                    std::cerr << "[GPU_IMG_Worker] Task " << imgTask->getTaskId() << " failed" << std::endl;
                }
            }
            
            updateResourceMetrics();
        } catch (const std::exception& e) {
            std::cerr << "[GPU_IMG_Worker] Exception processing task: " << e.what() << std::endl;
            if (task) {
                task->setStatus(TaskStatus::FAILED);
                failedTasksCount_++;
            }
        } finally {
            activeTasksCount_--;
            busy_ = false;
        }
    }
}

// 处理单个任务
bool GPUImgWorker::processTask(const std::shared_ptr<ImgTask>& task) {
    if (!model_) {
        std::cerr << "[GPU_IMG_Worker] No image model initialized" << std::endl;
        return false;
    }
    
    // 记录开始时间
    auto startTime = std::chrono::high_resolution_clock::now();
    
    try {
        // 生成输出文件名
        std::string outputPath = generateOutputFilename();
        
        // 创建进度回调
        auto progressCallback = [this, &task](float progress) {
            task->setProgress(progress);
            if (progressCallback_) {
                progressCallback_(task->getTaskId(), progress);
            }
        };
        
        // 执行图像生成
        bool success = model_->generate(
            task->getPrompt(), 
            task->getParams(), 
            outputPath,
            progressCallback
        );
        
        // 设置输出路径和图像数据
        if (success) {
            task->setOutputPath(outputPath);
            
            // 读取图像文件数据
            std::ifstream imgFile(outputPath, std::ios::binary);
            if (imgFile) {
                imgFile.seekg(0, std::ios::end);
                size_t size = imgFile.tellg();
                imgFile.seekg(0, std::ios::beg);
                
                std::vector<uint8_t> imgData(size);
                imgFile.read(reinterpret_cast<char*>(imgData.data()), size);
                
                task->setImageData(imgData.data(), size);
            }
            
            // 更新统计信息
            { 
                std::lock_guard<std::mutex> lock(statsMutex_);
                // 更新平均推理步数
                float currentSteps = static_cast<float>(task->getParams().num_inference_steps);
                if (generationCount_ == 0) {
                    avgInferenceSteps_ = currentSteps;
                } else {
                    avgInferenceSteps_ = (avgInferenceSteps_ * generationCount_ + currentSteps) / (generationCount_ + 1);
                }
            }
        }
        
        // 记录结束时间
        auto endTime = std::chrono::high_resolution_clock::now();
        auto generationTime = std::chrono::duration_cast<std::chrono::milliseconds>(endTime - startTime).count();
        
        // 更新统计信息
        { 
            std::lock_guard<std::mutex> lock(statsMutex_);
            totalGenerationTime_ += generationTime;
            generationCount_++;
        }
        
        std::cout << "[GPU_IMG_Worker] Task " << task->getTaskId() << " completed in " 
                  << generationTime << "ms" << std::endl;
        
        return success;
    } catch (const std::exception& e) {
        std::cerr << "[GPU_IMG_Worker] Exception during image generation: " << e.what() << std::endl;
        return false;
    }
}

// 创建模型实例
std::shared_ptr<IImgModel> GPUImgWorker::createModel(ImgEngineType engineType) {
    switch (engineType) {
        case ImgEngineType::STABLE_DIFFUSION_1_5_TURBO:
            return std::make_shared<StableDiffusion15TurboModel>(outputDir_);
        case ImgEngineType::SDXL_TURBO:
            return std::make_shared<SDXLTurboModel>(outputDir_);
        case ImgEngineType::MOBILE_DIFFUSION:
            return std::make_shared<MobileDiffusionModel>(outputDir_);
        case ImgEngineType::MOCK:
        default:
            return std::make_shared<MockImgModel>(outputDir_);
    }
}

// 更新资源指标
void GPUImgWorker::updateResourceMetrics() {
    // 在实际应用中，可以使用系统API获取GPU利用率
    // 这里使用简化的估算
    if (generationCount_ > 0) {
        // 简单的GPU利用率估算（图像生成通常接近100% GPU利用率）
        gpuUtilization_ = 0.8f * gpuUtilization_ + 0.2f * 95.0f; // 假设平均95%的GPU利用率
        
        // 确保GPU利用率在合理范围内
        gpuUtilization_ = std::min(100.0f, std::max(0.0f, gpuUtilization_));
    }
}

// 生成输出文件名
std::string GPUImgWorker::generateOutputFilename() {
    auto now = std::chrono::system_clock::now();
    auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> distrib(1000, 9999);
    
    std::stringstream ss;
    ss << outputDir_ << "/img_" 
       << timestamp << "_" << distrib(gen) << ".png";
    
    return ss.str();
}

// 模型实现类 - Stable Diffusion 1.5 Turbo
class StableDiffusion15TurboModel : public IImgModel {
public:
    StableDiffusion15TurboModel(const std::string& outputDir) 
        : outputDir_(outputDir), gpuDeviceId_(0) {}
    
    bool initialize() override {
        std::cout << "[StableDiffusion15TurboModel] Initializing..." << std::endl;
        std::cout << "[StableDiffusion15TurboModel] Loading model from: stabilityai/stable-diffusion-1.5-turbo" << std::endl;
        // 模拟模型加载延迟
        std::this_thread::sleep_for(std::chrono::seconds(2));
        return true;
    }
    
    bool generate(const std::string& prompt, 
                 const ImgGenerationParams& params,
                 const std::string& outputPath,
                 std::function<void(float)> progressCallback = nullptr) override {
        std::cout << "[StableDiffusion15TurboModel] Generating image with prompt: " << prompt << std::endl;
        
        // 模拟生成过程
        int steps = params.use_turbo_mode ? 4 : params.num_inference_steps;
        for (int i = 0; i < steps; ++i) {
            float progress = static_cast<float>(i + 1) / steps;
            
            if (progressCallback) {
                progressCallback(progress);
            }
            
            // 模拟每步推理延迟（turbo模式更快）
            std::this_thread::sleep_for(std::chrono::milliseconds(params.use_turbo_mode ? 150 : 300));
        }
        
        // 创建模拟的图像文件
        createMockImageFile(outputPath, params.width, params.height);
        return true;
    }
    
    void setGpuDeviceId(int gpuId) override {
        gpuDeviceId_ = gpuId;
        std::cout << "[StableDiffusion15TurboModel] Set GPU device ID: " << gpuId << std::endl;
    }
    
    void cleanup() override {
        std::cout << "[StableDiffusion15TurboModel] Cleaning up..." << std::endl;
    }
    
private:
    std::string outputDir_;
    int gpuDeviceId_;
    
    void createMockImageFile(const std::string& filePath, int width, int height) {
        // 创建一个简单的PNG文件（仅作为模拟）
        std::ofstream file(filePath, std::ios::binary);
        if (!file) {
            std::cerr << "Failed to create mock image file: " << filePath << std::endl;
            return;
        }
        
        // 简单的PNG文件头部（不完全符合标准，仅作为模拟）
        const char header[] = {
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, // PNG签名
            // 其他模拟数据...
        };
        
        file.write(header, sizeof(header));
        
        // 写入一些模拟数据
        char data[1024] = {0};
        for (int i = 0; i < 10; ++i) {
            file.write(data, sizeof(data));
        }
        
        file.close();
    }
};

// 模型实现类 - SDXL Turbo
class SDXLTurboModel : public IImgModel {
public:
    SDXLTurboModel(const std::string& outputDir) 
        : outputDir_(outputDir), gpuDeviceId_(0) {}
    
    bool initialize() override {
        std::cout << "[SDXLTurboModel] Initializing..." << std::endl;
        std::cout << "[SDXLTurboModel] Loading model from: stabilityai/sdxl-turbo" << std::endl;
        // 模拟模型加载延迟
        std::this_thread::sleep_for(std::chrono::seconds(3));
        return true;
    }
    
    bool generate(const std::string& prompt, 
                 const ImgGenerationParams& params,
                 const std::string& outputPath,
                 std::function<void(float)> progressCallback = nullptr) override {
        std::cout << "[SDXLTurboModel] Generating image with prompt: " << prompt << std::endl;
        
        // 模拟生成过程
        int steps = params.use_turbo_mode ? 2 : params.num_inference_steps;
        for (int i = 0; i < steps; ++i) {
            float progress = static_cast<float>(i + 1) / steps;
            
            if (progressCallback) {
                progressCallback(progress);
            }
            
            // SDXL Turbo更快
            std::this_thread::sleep_for(std::chrono::milliseconds(params.use_turbo_mode ? 100 : 400));
        }
        
        // 创建模拟的图像文件
        createMockImageFile(outputPath, params.width, params.height);
        return true;
    }
    
    void setGpuDeviceId(int gpuId) override {
        gpuDeviceId_ = gpuId;
        std::cout << "[SDXLTurboModel] Set GPU device ID: " << gpuId << std::endl;
    }
    
    void cleanup() override {
        std::cout << "[SDXLTurboModel] Cleaning up..." << std::endl;
    }
    
private:
    std::string outputDir_;
    int gpuDeviceId_;
    
    void createMockImageFile(const std::string& filePath, int width, int height) {
        // 复用StableDiffusion15TurboModel的实现
        std::ofstream file(filePath, std::ios::binary);
        if (!file) {
            std::cerr << "Failed to create mock image file: " << filePath << std::endl;
            return;
        }
        
        // 简单的PNG文件头部
        const char header[] = {
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        };
        
        file.write(header, sizeof(header));
        
        // 写入一些模拟数据
        char data[1024] = {0};
        for (int i = 0; i < 10; ++i) {
            file.write(data, sizeof(data));
        }
        
        file.close();
    }
};

// 模型实现类 - Mobile Diffusion
class MobileDiffusionModel : public IImgModel {
public:
    MobileDiffusionModel(const std::string& outputDir) 
        : outputDir_(outputDir), gpuDeviceId_(0) {}
    
    bool initialize() override {
        std::cout << "[MobileDiffusionModel] Initializing..." << std::endl;
        std::cout << "[MobileDiffusionModel] Loading lightweight model" << std::endl;
        // 模拟模型加载延迟
        std::this_thread::sleep_for(std::chrono::seconds(1));
        return true;
    }
    
    bool generate(const std::string& prompt, 
                 const ImgGenerationParams& params,
                 const std::string& outputPath,
                 std::function<void(float)> progressCallback = nullptr) override {
        std::cout << "[MobileDiffusionModel] Generating image with prompt: " << prompt << std::endl;
        
        // 模拟生成过程
        int steps = params.num_inference_steps;
        for (int i = 0; i < steps; ++i) {
            float progress = static_cast<float>(i + 1) / steps;
            
            if (progressCallback) {
                progressCallback(progress);
            }
            
            // 移动模型速度较快，但质量较低
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        
        // 创建模拟的图像文件
        createMockImageFile(outputPath, params.width, params.height);
        return true;
    }
    
    void setGpuDeviceId(int gpuId) override {
        gpuDeviceId_ = gpuId;
        std::cout << "[MobileDiffusionModel] Set GPU device ID: " << gpuId << std::endl;
    }
    
    void cleanup() override {
        std::cout << "[MobileDiffusionModel] Cleaning up..." << std::endl;
    }
    
private:
    std::string outputDir_;
    int gpuDeviceId_;
    
    void createMockImageFile(const std::string& filePath, int width, int height) {
        // 复用实现
        std::ofstream file(filePath, std::ios::binary);
        if (!file) {
            std::cerr << "Failed to create mock image file: " << filePath << std::endl;
            return;
        }
        
        const char header[] = {
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        };
        
        file.write(header, sizeof(header));
        char data[1024] = {0};
        for (int i = 0; i < 8; ++i) {
            file.write(data, sizeof(data));
        }
        
        file.close();
    }
};

// 模型实现类 - Mock (用于测试)
class MockImgModel : public IImgModel {
public:
    MockImgModel(const std::string& outputDir) 
        : outputDir_(outputDir), gpuDeviceId_(0) {}
    
    bool initialize() override {
        std::cout << "[MockImgModel] Initializing..." << std::endl;
        return true;
    }
    
    bool generate(const std::string& prompt, 
                 const ImgGenerationParams& params,
                 const std::string& outputPath,
                 std::function<void(float)> progressCallback = nullptr) override {
        std::cout << "[MockImgModel] Mock generating image with prompt: " << prompt << std::endl;
        
        // 模拟生成过程
        int steps = params.num_inference_steps;
        for (int i = 0; i < steps; ++i) {
            float progress = static_cast<float>(i + 1) / steps;
            
            if (progressCallback) {
                progressCallback(progress);
            }
            
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        
        // 创建模拟的图像文件
        createMockImageFile(outputPath, params.width, params.height);
        return true;
    }
    
    void setGpuDeviceId(int gpuId) override {
        gpuDeviceId_ = gpuId;
        std::cout << "[MockImgModel] Set GPU device ID: " << gpuId << std::endl;
    }
    
    void cleanup() override {
        std::cout << "[MockImgModel] Cleaning up..." << std::endl;
    }
    
private:
    std::string outputDir_;
    int gpuDeviceId_;
    
    void createMockImageFile(const std::string& filePath, int width, int height) {
        // 最简单的模拟
        std::ofstream file(filePath, std::ios::binary);
        if (!file) {
            std::cerr << "Failed to create mock image file: " << filePath << std::endl;
            return;
        }
        
        // 写入一些简单数据
        file.write("MOCK_PNG", 8);
        file.close();
    }
};

// 工厂方法：创建图像生成任务
std::shared_ptr<ImgTask> createImgTask(const std::string& taskId, 
                                      const std::string& prompt,
                                      const ImgGenerationParams& params) {
    auto task = std::make_shared<ImgTask>(taskId, prompt, params);
    return task;
}

} // namespace ai_scheduler