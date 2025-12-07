#pragma once

#include <string>
#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <memory>
#include <map>
#include <atomic>

// 包含基础接口
#include "worker_interface.h"

namespace ai_scheduler {

// 图像生成引擎类型
enum class ImgEngineType {
    STABLE_DIFFUSION_1_5_TURBO,
    SDXL_TURBO,
    MOBILE_DIFFUSION,
    MOCK
};

// 图像生成参数结构体
struct ImgGenerationParams {
    std::string prompt;               // 提示词
    std::string negative_prompt;      // 反向提示词
    int width = 512;                  // 图像宽度
    int height = 512;                 // 图像高度
    float guidance_scale = 7.5f;      // 引导尺度
    int num_inference_steps = 20;     // 推理步数
    int seed = -1;                    // 随机种子，-1表示随机
    bool use_turbo_mode = true;       // 是否使用turbo模式
    
    // 构造函数
    ImgGenerationParams() = default;
    
    ImgGenerationParams(const std::string& prompt, 
                        const std::string& negative_prompt = "",
                        int width = 512, 
                        int height = 512,
                        float guidance_scale = 7.5f,
                        int num_inference_steps = 20,
                        int seed = -1,
                        bool use_turbo_mode = true)
        : prompt(prompt),
          negative_prompt(negative_prompt),
          width(width),
          height(height),
          guidance_scale(guidance_scale),
          num_inference_steps(num_inference_steps),
          seed(seed),
          use_turbo_mode(use_turbo_mode) {}
};

// 图像生成任务类
class ImgTask : public ITask {
public:
    ImgTask(const std::string& taskId, 
            const std::string& prompt,
            const ImgGenerationParams& params)
        : ITask(taskId),
          prompt_(prompt),
          params_(params),
          outputPath_(""),
          imgData_(nullptr),
          imgDataSize_(0),
          progress_(0.0f) {}
    
    // 获取任务类型
    TaskType getTaskType() const override {
        return TaskType::IMAGE_GENERATION;
    }
    
    // 获取提示词
    const std::string& getPrompt() const {
        return prompt_;
    }
    
    // 获取生成参数
    const ImgGenerationParams& getParams() const {
        return params_;
    }
    
    // 设置/获取输出路径
    void setOutputPath(const std::string& path) {
        outputPath_ = path;
    }
    
    const std::string& getOutputPath() const {
        return outputPath_;
    }
    
    // 设置/获取图像数据
    void setImageData(const uint8_t* data, size_t size) {
        if (imgData_) {
            delete[] imgData_;
        }
        imgData_ = new uint8_t[size];
        imgDataSize_ = size;
        std::memcpy(imgData_, data, size);
    }
    
    const uint8_t* getImageData() const {
        return imgData_;
    }
    
    size_t getImageDataSize() const {
        return imgDataSize_;
    }
    
    // 设置/获取进度
    void setProgress(float progress) {
        progress_ = std::min(1.0f, std::max(0.0f, progress));
    }
    
    float getProgress() const {
        return progress_;
    }
    
    // 析构函数
    ~ImgTask() {
        if (imgData_) {
            delete[] imgData_;
        }
    }
    
private:
    std::string prompt_;
    ImgGenerationParams params_;
    std::string outputPath_;
    uint8_t* imgData_;
    size_t imgDataSize_;
    float progress_;
};

// 图像生成模型接口
class IImgModel {
public:
    virtual ~IImgModel() = default;
    
    // 初始化模型
    virtual bool initialize() = 0;
    
    // 生成图像
    virtual bool generate(const std::string& prompt, 
                         const ImgGenerationParams& params,
                         const std::string& outputPath,
                         std::function<void(float)> progressCallback = nullptr) = 0;
    
    // 设置GPU设备ID
    virtual void setGpuDeviceId(int gpuId) = 0;
    
    // 清理资源
    virtual void cleanup() = 0;
};

// GPU图像生成worker类
class GPUImgWorker : public IWorker {
public:
    GPUImgWorker(const std::string& workerId = "GPU_IMG_Worker",
                ImgEngineType engineType = ImgEngineType::STABLE_DIFFUSION_1_5_TURBO,
                int gpuDeviceId = 0);
    
    ~GPUImgWorker();
    
    // 禁用拷贝构造和赋值操作
    GPUImgWorker(const GPUImgWorker&) = delete;
    GPUImgWorker& operator=(const GPUImgWorker&) = delete;
    
    // 初始化worker
    bool initialize() override;
    
    // 关闭worker
    void shutdown() override;
    
    // 提交任务
    std::string submitTask(const std::shared_ptr<ITask>& task) override;
    
    // 取消任务
    bool cancelTask(const std::string& taskId) override;
    
    // 获取worker状态
    WorkerStatus getWorkerStatus() const override;
    
    // 获取worker统计信息
    std::map<std::string, std::string> getWorkerStats() const override;
    
    // 设置任务完成回调
    void setTaskCompletedCallback(TaskCompletedCallback callback) override;
    
    // 设置进度回调
    void setProgressCallback(std::function<void(const std::string&, float)> callback) {
        progressCallback_ = callback;
    }
    
private:
    // 任务队列处理函数
    void processTaskQueue();
    
    // 处理单个任务
    bool processTask(const std::shared_ptr<ImgTask>& task);
    
    // 创建模型实例
    std::shared_ptr<IImgModel> createModel(ImgEngineType engineType);
    
    // 更新资源指标
    void updateResourceMetrics();
    
    // 生成输出文件名
    std::string generateOutputFilename();
    
    // 成员变量
    std::string workerId_;
    ImgEngineType engineType_;
    int gpuDeviceId_;
    
    // 状态控制
    std::atomic<bool> initialized_;
    std::atomic<bool> running_;
    std::atomic<bool> busy_;
    
    // 任务管理
    std::queue<std::shared_ptr<ITask>> taskQueue_;
    std::mutex taskMutex_;
    std::condition_variable taskCondition_;
    std::thread executionThread_;
    
    // 回调函数
    TaskCompletedCallback taskCompletedCallback_;
    std::mutex callbackMutex_;
    std::function<void(const std::string&, float)> progressCallback_;
    
    // 模型相关
    std::shared_ptr<IImgModel> model_;
    std::string outputDir_;
    
    // 统计信息
    std::atomic<int> activeTasksCount_;
    std::atomic<int> completedTasksCount_;
    std::atomic<int> failedTasksCount_;
    std::atomic<long long> totalGenerationTime_;
    std::atomic<int> generationCount_;
    std::atomic<float> gpuUtilization_;
    std::atomic<float> avgInferenceSteps_;
    std::mutex statsMutex_;
};

// 工厂方法：创建图像生成任务
extern std::shared_ptr<ImgTask> createImgTask(const std::string& taskId, 
                                             const std::string& prompt,
                                             const ImgGenerationParams& params);

} // namespace ai_scheduler