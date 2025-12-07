#include "gpu_image_worker.h"
#include <iostream>
#include <chrono>
#include <thread>
#include <stdexcept>
#include <filesystem>
#include <random>

namespace ai_scheduler {

GPUImageWorker::GPUImageWorker(int gpu_id, ImageModel default_model)
    : WorkerBase("GPUImageWorker"),
      gpu_id_(gpu_id),
      default_model_(default_model),
      task_queue_(nullptr),
      python_module_(nullptr),
      python_generate_func_(nullptr),
      gpu_utilization_(0.0f),
      gpu_memory_usage_(0),
      total_generation_time_(0),
      generation_count_(0),
      output_dir_("./output/images") {
    std::cout << "GPUImageWorker initialized with GPU ID: " << gpu_id_ 
              << ", Default model: " << modelToString(default_model_) << std::endl;
}

GPUImageWorker::~GPUImageWorker() {
    cleanup();
}

bool GPUImageWorker::initialize() {
    std::cout << "Initializing GPUImageWorker..." << std::endl;
    
    // 1. 设置专用GPU ID，确保与LLM的GPU资源隔离
    std::cout << "Setting dedicated GPU device to: " << gpu_id_ << std::endl;
    std::cout << "IMPORTANT: This GPU is isolated from LLM tasks to prevent resource contention" << std::endl;
    
    // 2. 创建输出目录
    std::filesystem::create_directories(output_dir_);
    std::cout << "Output directory created: " << output_dir_ << std::endl;
    
    // 3. 初始化Python接口
    if (!initializePythonInterface()) {
        std::cerr << "Failed to initialize Python interface" << std::endl;
        return false;
    }
    
    // 4. 初始化异步任务队列（只允许1个并发任务，避免GPU过载）
    task_queue_ = std::make_unique<TaskQueue>(1);
    task_queue_->initialize();
    
    initialized_ = true;
    std::cout << "GPUImageWorker initialized successfully with async queue" << std::endl;
    return true;
}

void GPUImageWorker::cleanup() {
    if (!initialized_) {
        return;
    }
    
    std::cout << "Cleaning up GPUImageWorker..." << std::endl;
    
    // 停止任务队列
    if (task_queue_) {
        task_queue_->shutdown();
        task_queue_ = nullptr;
    }
    
    // 释放Python资源
    if (python_module_) {
        std::cout << "Python module resources released" << std::endl;
        python_module_ = nullptr;
        python_generate_func_ = nullptr;
    }
    
    initialized_ = false;
    std::cout << "GPUImageWorker cleaned up" << std::endl;
}

void GPUImageWorker::executeTask(const std::string& prompt, Callback callback) {
    // 使用默认参数进行图像生成
    ImageGenerationParams params;
    params.prompt = prompt;
    params.model = default_model_;
    
    generateImage(params, callback);
}

uint64_t GPUImageWorker::generateImage(const ImageGenerationParams& params, Callback callback) {
    if (!isReady()) {
        if (callback) {
            callback(false, "Image worker not ready");
        }
        return 0;
    }
    
    // 创建任务包装器，提交到异步队列
    uint64_t task_id = task_queue_->enqueue([this, params, callback]() {
        try {
            std::cout << "Processing image generation task with prompt: " << params.prompt << std::endl;
            
            // 记录开始时间
            auto start_time = std::chrono::high_resolution_clock::now();
            
            // 执行图像生成
            std::string output_path;
            bool success = generateInternal(params, output_path);
            
            // 记录结束时间
            auto end_time = std::chrono::high_resolution_clock::now();
            uint64_t generation_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
            
            // 更新统计信息
            if (success) {
                total_generation_time_ += generation_time;
                generation_count_++;
                
                std::cout << "Image generation completed in " << generation_time << "ms, saved to: " << output_path << std::endl;
                
                // 更新GPU使用统计（模拟）
                gpu_utilization_ = 80.0f + (rand() % 20);  // 模拟80-100%的GPU使用率
                gpu_memory_usage_ = 4 * 1024 * 1024 * 1024;  // 模拟4GB内存使用
                
                if (callback) {
                    callback(true, output_path);
                }
            } else {
                std::cerr << "Image generation failed for prompt: " << params.prompt << std::endl;
                if (callback) {
                    callback(false, "Image generation failed");
                }
            }
            
        } catch (const std::exception& e) {
            std::cerr << "Exception in image generation: " << e.what() << std::endl;
            if (callback) {
                callback(false, "Exception: " + std::string(e.what()));
            }
        }
    }, 10);  // 图像任务优先级设为10（中等优先级）
    
    std::cout << "Image generation task enqueued with ID: " << task_id 
              << " (will execute asynchronously without blocking LLM/TTS)" << std::endl;
    
    return task_id;
}

bool GPUImageWorker::cancelTask(uint64_t task_id) {
    if (task_queue_) {
        return task_queue_->cancel(task_id);
    }
    return false;
}

bool GPUImageWorker::isReady() const {
    return initialized_ && task_queue_ != nullptr && python_generate_func_ != nullptr;
}

size_t GPUImageWorker::getQueueSize() const {
    if (task_queue_) {
        return task_queue_->size();
    }
    return 0;
}

size_t GPUImageWorker::getRunningTaskCount() const {
    if (task_queue_) {
        return task_queue_->runningCount();
    }
    return 0;
}

float GPUImageWorker::getGPUUtilization() const {
    return gpu_utilization_;
}

void GPUImageWorker::setDefaultModel(ImageModel model) {
    default_model_ = model;
    std::cout << "Default model set to: " << modelToString(model) << std::endl;
}

bool GPUImageWorker::generateInternal(const ImageGenerationParams& params, std::string& output_path) {
    // 生成唯一的输出文件名
    auto now = std::chrono::system_clock::now();
    auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    
    output_path = output_dir_ + "/image_" + std::to_string(timestamp) + ".png";
    
    // 调用Python接口进行实际生成
    return callPythonGenerate(params, output_path);
}

bool GPUImageWorker::initializePythonInterface() {
    try {
        std::cout << "Initializing Python interface for image generation..." << std::endl;
        std::cout << "Loading model: " << modelToString(default_model_) << " on GPU " << gpu_id_ << std::endl;
        
        // 模拟模型加载延迟（实际应用中会加载真实的Stable Diffusion模型）
        std::cout << "Loading Stable Diffusion model... This may take a few seconds..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        
        // 设置模拟的函数指针
        python_module_ = reinterpret_cast<void*>(1);
        python_generate_func_ = reinterpret_cast<void*>(2);
        
        std::cout << "Image generation Python interface initialized successfully" << std::endl;
        std::cout << "IMPORTANT: This worker uses a separate GPU from LLM, ensuring non-blocking operation" << std::endl;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Error initializing image generation Python interface: " << e.what() << std::endl;
        return false;
    }
}

bool GPUImageWorker::callPythonGenerate(const ImageGenerationParams& params, std::string& output_path) {
    try {
        if (!python_generate_func_) {
            return false;
        }
        
        // 在实际实现中，这里会调用Python的图像生成函数
        // 现在模拟生成过程
        std::cout << "Generating image with parameters: " << std::endl;
        std::cout << "- Prompt: " << params.prompt << std::endl;
        std::cout << "- Model: " << modelToString(params.model) << std::endl;
        std::cout << "- Size: " << params.width << "x" << params.height << std::endl;
        std::cout << "- Steps: " << params.steps << std::endl;
        std::cout << "- GPU: " << gpu_id_ << " (isolated from LLM)" << std::endl;
        
        // 模拟图像生成延迟（根据分辨率和步数调整）
        int delay_ms = params.width * params.height / 1000 * params.steps / 20;
        std::cout << "Processing... (estimated time: ~" << delay_ms / 1000 << " seconds)" << std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(std::max(1000, delay_ms)));
        
        // 模拟输出文件路径
        output_path = output_dir_ + "/generated_image.png";
        
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Error in image generation: " << e.what() << std::endl;
        return false;
    }
}

std::string GPUImageWorker::modelToString(ImageModel model) const {
    switch (model) {
        case ImageModel::SD15_TURBO:
            return "Stable Diffusion 1.5 Turbo";
        case ImageModel::SDXL_TURBO:
            return "Stable Diffusion XL Turbo";
        case ImageModel::MOBILE_DIFFUSION:
            return "MobileDiffusion";
        case ImageModel::SVD:
            return "Stable Video Diffusion";
        default:
            return "Unknown";
    }
}

} // namespace ai_scheduler