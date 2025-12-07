#ifndef BLACKBOX_INTEGRATION_EXAMPLE_H
#define BLACKBOX_INTEGRATION_EXAMPLE_H

#include "api_server.h"
#include "api_client.h"
#include "../core/resource_isolation_scheduler.h"
#include "../workers/cpu_tts_worker.h"
#include "../workers/gpu_llm_worker.h"
#include "../workers/gpu_img_worker.h"

#include <iostream>
#include <thread>
#include <chrono>
#include <memory>

namespace ai_scheduler::api {

// 黑盒集成示例类 - 展示如何使用完整的资源隔离架构
class BlackBoxIntegrationExample {
public:
    // 运行完整示例
    static void runFullExample() {
        std::cout << "=== 黑盒架构集成示例启动 ===" << std::endl;
        
        // 1. 创建配置
        auto config = std::make_shared<BlackBoxConfig>();
        config->setLLMEngine("qwen2.5");
        config->setTTSVoice("coqui");
        config->setImageModel("sd1.5-turbo");
        config->setGPUAllocatedForLLM(70); // 分配70% GPU给LLM
        config->setGPUAllocatedForImage(30); // 分配30% GPU给图像生成
        config->setMaxConcurrentTasks(10);
        
        // 2. 初始化黑盒服务
        auto server = createBlackBoxServer(config);
        if (!server) {
            std::cerr << "黑盒服务初始化失败" << std::endl;
            return;
        }
        
        // 3. 启动API服务器
        if (!server->start()) {
            std::cerr << "API服务器启动失败" << std::endl;
            return;
        }
        
        std::cout << "黑盒服务已启动，监听端口: 8080" << std::endl;
        std::cout << "等待服务初始化完成..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        
        // 4. 创建API客户端
        auto client = createDefaultAPIClient("http://localhost:8080");
        
        // 5. 演示LLM实时响应
        runLLMDemo(client);
        
        // 6. 演示TTS并行合成
        runTTSDemo(client);
        
        // 7. 演示图像异步生成
        runImageDemo(client);
        
        // 8. 演示资源隔离效果
        runResourceIsolationDemo(client);
        
        // 9. 清理资源
        std::cout << "\n=== 黑盒架构集成示例完成 ===" << std::endl;
        server->stop();
    }
    
    // 创建完整的黑盒服务器
    static std::shared_ptr<APIServer> createBlackBoxServer(std::shared_ptr<BlackBoxConfig> config) {
        // 创建API服务器
        auto server = std::make_shared<APIServer>(8080);
        
        // 创建资源隔离调度器
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(4); // 4个CPU线程
        
        // 创建LLM worker (GPU实时)
        auto llmWorker = std::make_shared<GPULLMWorker>("LLM_GPU_Worker", LLMEngineType::QWEN_2_5, 0);
        if (!llmWorker->initialize()) {
            std::cerr << "LLM Worker初始化失败" << std::endl;
            return nullptr;
        }
        
        // 创建TTS worker (CPU实时)
        auto ttsWorker = std::make_shared<CPUTTSWorker>("TTS_CPU_Worker", TTSEngineType::COQUI_GLOW_TTS);
        if (!ttsWorker->initialize()) {
            std::cerr << "TTS Worker初始化失败" << std::endl;
            return nullptr;
        }
        
        // 创建图像生成worker (GPU异步队列)
        auto imgWorker = std::make_shared<GPUImgWorker>("IMG_GPU_Worker", 
                                                       ImgEngineType::STABLE_DIFFUSION_1_5_TURBO, 1);
        if (!imgWorker->initialize()) {
            std::cerr << "Image Worker初始化失败" << std::endl;
            return nullptr;
        }
        
        // 设置服务器组件
        server->setScheduler(scheduler);
        server->setLLMWorker(llmWorker);
        server->setTTSWorker(ttsWorker);
        server->setImageWorker(imgWorker);
        
        return server;
    }
    
    // LLM演示
    static void runLLMDemo(std::shared_ptr<APIClient> client) {
        std::cout << "\n=== LLM实时响应演示 ===" << std::endl;
        
        std::string prompt = "请简单解释什么是资源隔离调度架构？";
        std::cout << "发送LLM请求: " << prompt << std::endl;
        
        auto start = std::chrono::high_resolution_clock::now();
        auto response = client->generateLLM(prompt);
        auto end = std::chrono::high_resolution_clock::now();
        
        auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
        
        if (response.isSuccess()) {
            std::cout << "LLM响应成功，耗时: " << duration << "ms" << std::endl;
            std::cout << "响应内容: " << response.body << std::endl;
        } else {
            std::cout << "LLM响应失败: " << response.status_code << std::endl;
        }
    }
    
    // TTS演示
    static void runTTSDemo(std::shared_ptr<APIClient> client) {
        std::cout << "\n=== TTS并行合成演示 ===" << std::endl;
        
        std::vector<std::string> texts = {
            "这是第一段语音合成文本，用于演示CPU并行处理能力。",
            "这是第二段语音合成文本，即使在LLM运行时也能流畅执行。",
            "这是第三段语音合成文本，展示资源隔离的优势。"
        };
        
        std::vector<std::thread> threads;
        for (size_t i = 0; i < texts.size(); ++i) {
            threads.emplace_back([client, &texts, i]() {
                std::cout << "开始TTS合成 (" << i+1 << ")" << std::endl;
                auto start = std::chrono::high_resolution_clock::now();
                
                client->synthesizeTTSAsync(texts[i], [start, i](const ClientResponse& response) {
                    auto end = std::chrono::high_resolution_clock::now();
                    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
                    
                    if (response.isSuccess()) {
                        std::cout << "TTS合成完成 (" << i+1 << "), 耗时: " << duration << "ms" << std::endl;
                    } else {
                        std::cout << "TTS合成失败 (" << i+1 << ")" << std::endl;
                    }
                });
            });
        }
        
        // 等待所有线程完成
        for (auto& thread : threads) {
            if (thread.joinable()) {
                thread.join();
            }
        }
        
        // 等待所有TTS任务完成
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    
    // 图像生成演示
    static void runImageDemo(std::shared_ptr<APIClient> client) {
        std::cout << "\n=== 图像异步生成演示 ===" << std::endl;
        
        std::string prompt = "一只可爱的小猫坐在窗台上看风景，卡通风格";
        std::string taskId;
        
        // 异步发送图像生成请求
        client->generateImageAsync(prompt, [&taskId](const ClientResponse& response) {
            if (response.isSuccess()) {
                std::cout << "图像生成请求已接受，开始异步处理..." << std::endl;
                // 在实际实现中，这里应该解析响应中的task_id
                taskId = "img_task_12345";
            }
        }, 512, 512, true, 4);
        
        // 模拟进度查询
        std::this_thread::sleep_for(std::chrono::seconds(1));
        
        // 演示进度查询
        if (!taskId.empty()) {
            std::cout << "查询图像生成进度..." << std::endl;
            auto progressResponse = client->getImageProgress(taskId);
            if (progressResponse.isSuccess()) {
                std::cout << "进度查询成功" << std::endl;
            }
        }
        
        // 等待图像生成完成
        std::this_thread::sleep_for(std::chrono::seconds(3));
        
        // 查询资源使用情况
        std::cout << "\n查询系统资源使用情况..." << std::endl;
        auto statsResponse = client->getResourceStats();
        if (statsResponse.isSuccess()) {
            std::cout << "资源统计获取成功" << std::endl;
        }
    }
    
    // 资源隔离演示
    static void runResourceIsolationDemo(std::shared_ptr<APIClient> client) {
        std::cout << "\n=== 资源隔离效果演示 ===" << std::endl;
        
        // 1. 启动一个LLM请求
        std::thread llmThread([client]() {
            std::cout << "启动LLM请求 (高优先级)" << std::endl;
            client->generateLLM("写一首关于AI和人类协作的短诗");
            std::cout << "LLM请求完成" << std::endl;
        });
        
        // 2. 同时启动多个TTS请求
        std::thread ttsThread([client]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            std::cout << "同时启动TTS请求 (CPU资源)" << std::endl;
            client->synthesizeTTS("即使LLM在使用GPU，TTS也能在CPU上并行运行");
        });
        
        // 3. 同时启动图像生成请求 (放入队列)
        std::thread imgThread([client]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(800));
            std::cout << "同时启动图像生成请求 (GPU队列)" << std::endl;
            client->generateImageAsync("未来科技城市夜景", nullptr, 512, 512);
        });
        
        // 等待所有线程完成
        if (llmThread.joinable()) llmThread.join();
        if (ttsThread.joinable()) ttsThread.join();
        if (imgThread.joinable()) imgThread.join();
        
        std::cout << "\n资源隔离演示完成，所有任务都能在各自的资源域中执行而不相互干扰" << std::endl;
    }
};

// 黑盒架构服务类 - 为厂商提供的统一接口
class BlackBoxService {
public:
    BlackBoxService(int port = 8080) : port_(port) {}
    
    // 初始化服务
    bool initialize() {
        std::cout << "[黑盒服务] 初始化开始..." << std::endl;
        
        // 创建默认配置
        config_ = std::make_shared<BlackBoxConfig>();
        
        // 创建并初始化API服务器
        server_ = BlackBoxIntegrationExample::createBlackBoxServer(config_);
        if (!server_) {
            return false;
        }
        
        return true;
    }
    
    // 启动服务
    bool start() {
        if (!server_) {
            return false;
        }
        
        return server_->start();
    }
    
    // 停止服务
    void stop() {
        if (server_) {
            server_->stop();
        }
    }
    
    // 设置配置
    void setConfig(std::shared_ptr<BlackBoxConfig> config) {
        config_ = config;
    }
    
    // 获取配置
    std::shared_ptr<BlackBoxConfig> getConfig() const {
        return config_;
    }
    
    // 获取服务状态
    bool isRunning() const {
        return server_ && server_->isRunning();
    }
    
    // 获取端口
    int getPort() const {
        return port_;
    }
    
private:
    int port_;
    std::shared_ptr<APIServer> server_;
    std::shared_ptr<BlackBoxConfig> config_;
};

// 创建默认的黑盒服务实例
inline std::shared_ptr<BlackBoxService> createDefaultBlackBoxService(int port = 8080) {
    auto service = std::make_shared<BlackBoxService>(port);
    if (service->initialize()) {
        return service;
    }
    return nullptr;
}

} // namespace ai_scheduler::api

#endif // BLACKBOX_INTEGRATION_EXAMPLE_H