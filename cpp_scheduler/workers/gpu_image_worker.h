#pragma once

#include "resource_isolation_scheduler.h"
#include <mutex>
#include <string>
#include <atomic>
#include <memory>
#include <future>
#include <vector>

namespace ai_scheduler {

// 图像生成参数结构
enum class ImageModel {
    SD15_TURBO,
    SDXL_TURBO,
    MOBILE_DIFFUSION,
    SVD
};

struct ImageGenerationParams {
    std::string prompt;
    std::string negative_prompt;
    int width;
    int height;
    float guidance_scale;
    int steps;
    int seed;
    ImageModel model;
    
    // 默认构造函数
    ImageGenerationParams()
        : width(512), height(512), guidance_scale(7.5f),
          steps(20), seed(-1), model(ImageModel::SD15_TURBO) {
    }
};

// 图像生成任务类
class ImageTask : public ITask {
public:
    ImageTask(const std::string& taskId, const ImageGenerationParams& params)
        : ITask(taskId, TaskType::IMAGE_GENERATION), params_(params) {}
    
    ~ImageTask() override = default;
    
    // 获取图像生成参数
    const ImageGenerationParams& getParams() const { return params_; }
    
    // 设置/获取输出路径
    void setOutputPath(const std::string& path) { outputPath_ = path; }
    const std::string& getOutputPath() const { return outputPath_; }
    
    // 设置/获取图像数据
    void setImageData(const std::vector<uint8_t>& data) { imageData_ = data; }
    const std::vector<uint8_t>& getImageData() const { return imageData_; }
    
private:
    ImageGenerationParams params_;
    std::string outputPath_;
    std::vector<uint8_t> imageData_;
};

// 图像生成模型接口
class IImageModel {
public:
    virtual ~IImageModel() = default;
    
    // 初始化模型
    virtual bool initialize() = 0;
    
    // 清理模型资源
    virtual void cleanup() = 0;
    
    // 生成图像
    virtual bool generate(const ImageGenerationParams& params, 
                         std::string& outputPath, 
                         std::vector<uint8_t>& imageData) = 0;
    
    // 设置线程数
    virtual void setNumThreads(int numThreads) = 0;
    
    // 获取GPU内存使用情况
    virtual size_t getGPUMemoryUsage() const = 0;
    
    // 预热模型
    virtual bool warmup() = 0;
};

// GPU图像生成Worker类 - 异步非阻塞处理图像生成任务
class GPUImageWorker : public IWorker {
public:
    GPUImageWorker(const std::string& workerId = "GPU_Image_Worker", 
                  int gpuId = 1, 
                  ImageModel defaultModel = ImageModel::SD15_TURBO);
    ~GPUImageWorker() override;
    
    // IWorker接口方法
    bool initialize() override;
    void shutdown() override;
    std::string submitTask(const std::shared_ptr<ITask>& task) override;
    bool cancelTask(const std::string& taskId) override;
    WorkerStatus getWorkerStatus() const override;
    std::map<std::string, std::string> getWorkerStats() const override;
    
    // 设置任务完成回调
    void setTaskCompletedCallback(TaskCompletedCallback callback) override;
    
    // 其他方法
    void updateResourceMetrics() override;
    bool warmupModel() override;
    
    // 增强的图像生成接口
    std::string generateImage(const ImageGenerationParams& params);
    
    // 设置默认模型
    void setDefaultModel(ImageModel model);
    
private:
    // 创建图像生成模型
    std::shared_ptr<IImageModel> createModel(ImageModel modelType);
    
    // 处理任务队列
    void processTaskQueue();
    
    // 处理单个任务
    bool processTask(const std::shared_ptr<ImageTask>& task);
    
    // 执行实际的图像生成
    bool generateInternal(const ImageGenerationParams& params, 
                         std::string& outputPath, 
                         std::vector<uint8_t>& imageData);
    
    // Python接口交互
    bool initializePythonInterface();
    bool callPythonGenerate(const ImageGenerationParams& params, 
                           std::string& outputPath, 
                           std::vector<uint8_t>& imageData);
    
    // 转换模型枚举为字符串
    std::string modelToString(ImageModel model) const;
    
    // 成员变量
    std::string workerId_;
    int gpuId_;  // 专用GPU ID（与LLM不同）
    ImageModel defaultModel_;
    bool initialized_;
    bool running_;
    bool busy_;
    
    // 任务队列和线程
    std::queue<std::shared_ptr<ITask>> taskQueue_;
    std::mutex taskMutex_;
    std::condition_variable taskCondition_;
    std::thread executionThread_;
    
    // 模型和回调
    std::shared_ptr<IImageModel> model_;
    TaskCompletedCallback taskCompletedCallback_;
    std::mutex callbackMutex_;
    
    // 资源监控和统计
    float gpuUtilization_;
    size_t gpuMemoryUsage_;
    size_t peakGPUMemoryUsage_;
    uint64_t totalGenerationTime_;
    uint64_t generationCount_;
    int activeTasksCount_;
    int completedTasksCount_;
    
    // 输出目录
    std::string outputDir_;
    
    // 统计信息互斥锁
    std::mutex statsMutex_;
};

} // namespace ai_scheduler

#endif // GPU_IMAGE_WORKER_H