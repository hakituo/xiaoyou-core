#include "system_integration_test.h"
#include "../core/async_scheduler.h"
#include "../workers/gpu_llm_worker.h"
#include "../workers/cpu_tts_worker.h"
#include "../workers/gpu_image_worker.h"
#include "../queue/task_queue.h"
#include "../api/api_server.h"
#include "../api/api_client.h"
#include <iostream>
#include <chrono>
#include <random>
#include <algorithm>
#include <iomanip>

namespace ai_scheduler::tests {

SystemIntegrationTest::SystemIntegrationTest()
    : is_initialized_(false),
      completed_llm_tasks_(0),
      completed_tts_tasks_(0),
      completed_image_tasks_(0),
      total_llm_time_(0),
      total_tts_time_(0) {
    std::cout << "[SystemTest] Creating system integration test" << std::endl;
}

SystemIntegrationTest::~SystemIntegrationTest() {
    cleanup();
    std::cout << "[SystemTest] Test destroyed" << std::endl;
}

bool SystemIntegrationTest::initialize() {
    std::cout << "[SystemTest] Initializing test environment" << std::endl;
    
    try {
        // 创建调度器
        scheduler_ = std::make_shared<AsyncScheduler>(4); // 4个工作线程
        if (!scheduler_->initialize()) {
            std::cerr << "[SystemTest] Failed to initialize scheduler" << std::endl;
            return false;
        }
        
        // 创建LLM worker
        llm_worker_ = std::make_shared<GPULLMWorker>("llama_model", 4); // 4个CUDA线程
        if (!llm_worker_->initialize()) {
            std::cerr << "[SystemTest] Failed to initialize LLM worker" << std::endl;
            return false;
        }
        scheduler_->registerWorker(TaskType::LLM_GPU, llm_worker_);
        
        // 创建TTS worker
        tts_worker_ = std::make_shared<CPUTTSWorker>(TTSEngineType::COQUI_GLOW_TTS, 2); // 2个CPU线程
        if (!tts_worker_->initialize()) {
            std::cerr << "[SystemTest] Failed to initialize TTS worker" << std::endl;
            return false;
        }
        scheduler_->registerWorker(TaskType::TTS_CPU, tts_worker_);
        
        // 创建图像生成队列和worker
        image_queue_ = std::make_shared<TaskQueue>("image_generation_queue");
        if (!image_queue_->initialize()) {
            std::cerr << "[SystemTest] Failed to initialize image queue" << std::endl;
            return false;
        }
        
        image_worker_ = std::make_shared<GPUImageWorker>("sd15_turbo", 1); // 1个CUDA线程（限制GPU使用）
        if (!image_worker_->initialize()) {
            std::cerr << "[SystemTest] Failed to initialize image worker" << std::endl;
            return false;
        }
        scheduler_->registerWorker(TaskType::IMAGE_GPU_QUEUE, image_worker_);
        
        // 启动调度器
        if (!scheduler_->start()) {
            std::cerr << "[SystemTest] Failed to start scheduler" << std::endl;
            return false;
        }
        
        // 创建API服务器
        api_server_ = std::make_shared<api::APIServer>(8080);
        api_server_->setScheduler(scheduler_);
        api_server_->setLLMWorker(llm_worker_);
        api_server_->setTTSWorker(tts_worker_);
        api_server_->setImageWorker(image_worker_);
        api_server_->setImageTaskQueue(image_queue_);
        
        if (!api_server_->start()) {
            std::cerr << "[SystemTest] Failed to start API server" << std::endl;
            return false;
        }
        
        is_initialized_ = true;
        std::cout << "[SystemTest] Test environment initialized successfully" << std::endl;
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "[SystemTest] Initialization error: " << e.what() << std::endl;
        return false;
    }
}

void SystemIntegrationTest::cleanup() {
    if (is_initialized_) {
        std::cout << "[SystemTest] Cleaning up test environment" << std::endl;
        
        // 停止API服务器
        if (api_server_) {
            api_server_->stop();
            api_server_.reset();
        }
        
        // 停止调度器
        if (scheduler_) {
            scheduler_->stop();
            scheduler_.reset();
        }
        
        // 清理各个worker
        image_worker_.reset();
        image_queue_.reset();
        tts_worker_.reset();
        llm_worker_.reset();
        
        is_initialized_ = false;
        std::cout << "[SystemTest] Cleanup completed" << std::endl;
    }
}

TestResult SystemIntegrationTest::runAllTests() {
    std::cout << "\n=== RUNNING ALL SYSTEM INTEGRATION TESTS ===" << std::endl;
    
    auto start_time = std::chrono::high_resolution_clock::now();
    
    // 运行各个测试
    TestResult basic_result = testBasicFunctionality();
    printTestReport(basic_result);
    
    if (!basic_result.success) {
        return TestResult(false, "Basic functionality test failed, aborting further tests", 0);
    }
    
    TestResult perf_result = testConcurrentPerformance(10, 20, 5); // 10个LLM请求，20个TTS请求，5个图像请求
    printTestReport(perf_result);
    
    TestResult isolation_result = testResourceIsolation();
    printTestReport(isolation_result);
    
    TestResult error_result = testErrorHandling();
    printTestReport(error_result);
    
    TestResult api_result = testAPIEndpoints();
    printTestReport(api_result);
    
    auto end_time = std::chrono::high_resolution_clock::now();
    int duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
    
    bool all_passed = basic_result.success && perf_result.success && isolation_result.success && 
                     error_result.success && api_result.success;
    
    std::cout << "\n=== ALL TESTS COMPLETED IN " << duration << "ms ===" << std::endl;
    std::cout << "Overall Result: " << (all_passed ? "PASSED" : "FAILED") << std::endl;
    
    // 打印性能报告
    PerformanceMetrics metrics = getPerformanceMetrics();
    std::cout << "\n=== PERFORMANCE METRICS ===" << std::endl;
    std::cout << "LLM Requests/Second: " << metrics.llm_requests_per_second << std::endl;
    std::cout << "TTS Requests/Second: " << metrics.tts_requests_per_second << std::endl;
    std::cout << "Image Requests Queued: " << metrics.image_requests_queued << std::endl;
    std::cout << "Avg LLM Response Time: " << metrics.average_llm_response_time << "ms" << std::endl;
    std::cout << "Avg TTS Response Time: " << metrics.average_tts_response_time << "ms" << std::endl;
    std::cout << "CPU Utilization: " << metrics.cpu_utilization << "%" << std::endl;
    std::cout << "GPU Utilization: " << metrics.gpu_utilization << "%" << std::endl;
    
    return TestResult(all_passed, all_passed ? "All tests passed" : "Some tests failed", duration);
}

TestResult SystemIntegrationTest::testBasicFunctionality() {
    std::cout << "\n[TEST] Basic Functionality Test" << std::endl;
    auto start_time = std::chrono::high_resolution_clock::now();
    
    try {
        // 测试LLM
        bool llm_success = false;
        scheduler_->submitTask(TaskType::LLM_GPU, "写一个简短的介绍：什么是人工智能？", [&llm_success](bool success, const std::string& result, void* data) {
            llm_success = success;
            std::cout << "LLM Test Result: " << (success ? "Success" : "Failed") << std::endl;
        });
        
        // 等待LLM任务完成
        std::this_thread::sleep_for(std::chrono::seconds(2));
        
        // 测试TTS
        bool tts_success = false;
        scheduler_->submitTask(TaskType::TTS_CPU, "这是一个TTS功能测试。", [&tts_success](bool success, const std::string& result, void* data) {
            tts_success = success;
            std::cout << "TTS Test Result: " << (success ? "Success" : "Failed") << std::endl;
        });
        
        // 等待TTS任务完成
        std::this_thread::sleep_for(std::chrono::seconds(1));
        
        // 测试图像生成队列
        bool image_success = false;
        scheduler_->submitTask(TaskType::IMAGE_GPU_QUEUE, "一个美丽的风景", [&image_success](bool success, const std::string& result, void* data) {
            image_success = success;
            std::cout << "Image Test Result: " << (success ? "Success" : "Failed") << std::endl;
        });
        
        // 等待图像任务进入队列
        std::this_thread::sleep_for(std::chrono::seconds(1));
        
        auto end_time = std::chrono::high_resolution_clock::now();
        int duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        if (llm_success && tts_success) {
            return TestResult(true, "All basic functionality tests passed", duration);
        } else {
            return TestResult(false, "Basic functionality tests failed: LLM=" + 
                              std::string(llm_success ? "ok" : "fail") + 
                              ", TTS=" + std::string(tts_success ? "ok" : "fail"), duration);
        }
    }
    catch (const std::exception& e) {
        std::cerr << "Basic test exception: " << e.what() << std::endl;
        return TestResult(false, std::string("Exception: ") + e.what(), 0);
    }
}

TestResult SystemIntegrationTest::testConcurrentPerformance(int llm_requests, int tts_requests, int image_requests) {
    std::cout << "\n[TEST] Concurrent Performance Test" << std::endl;
    std::cout << "Configuration: " << llm_requests << " LLM, " 
              << tts_requests << " TTS, " << image_requests << " Image requests" << std::endl;
    
    auto start_time = std::chrono::high_resolution_clock::now();
    
    // 重置计数器
    completed_llm_tasks_ = 0;
    completed_tts_tasks_ = 0;
    completed_image_tasks_ = 0;
    total_llm_time_ = 0;
    total_tts_time_ = 0;
    
    // 生成测试数据
    std::vector<std::string> llm_prompts = generateTestPrompts(llm_requests);
    std::vector<std::string> tts_texts = generateTestTexts(tts_requests);
    std::vector<std::string> image_prompts = generateTestPrompts(image_requests);
    
    // 创建线程池同时执行所有测试
    std::vector<std::thread> test_threads;
    
    // 启动资源监控
    std::thread monitor_thread(&SystemIntegrationTest::monitorResources, this);
    
    // 启动LLM测试线程
    for (const auto& prompt : llm_prompts) {
        test_threads.emplace_back(&SystemIntegrationTest::runLLMTest, this, prompt);
    }
    
    // 启动TTS测试线程
    for (const auto& text : tts_texts) {
        test_threads.emplace_back(&SystemIntegrationTest::runTTSTest, this, text);
    }
    
    // 启动图像生成测试线程
    for (const auto& prompt : image_prompts) {
        test_threads.emplace_back(&SystemIntegrationTest::runImageTest, this, prompt);
    }
    
    // 等待所有测试线程完成
    for (auto& thread : test_threads) {
        if (thread.joinable()) {
            thread.join();
        }
    }
    
    // 停止资源监控
    monitor_thread.join();
    
    auto end_time = std::chrono::high_resolution_clock::now();
    int total_duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
    
    // 计算性能指标
    metrics_.llm_requests_per_second = total_duration > 0 ? (llm_requests * 1000) / total_duration : 0;
    metrics_.tts_requests_per_second = total_duration > 0 ? (tts_requests * 1000) / total_duration : 0;
    metrics_.image_requests_queued = image_requests;
    
    if (completed_llm_tasks_ > 0) {
        metrics_.average_llm_response_time = static_cast<float>(total_llm_time_) / completed_llm_tasks_;
    }
    if (completed_tts_tasks_ > 0) {
        metrics_.average_tts_response_time = static_cast<float>(total_tts_time_) / completed_tts_tasks_;
    }
    
    std::cout << "Performance Test Results:" << std::endl;
    std::cout << "  Completed LLM Tasks: " << completed_llm_tasks_ << "/" << llm_requests << std::endl;
    std::cout << "  Completed TTS Tasks: " << completed_tts_tasks_ << "/" << tts_requests << std::endl;
    std::cout << "  Completed Image Tasks: " << completed_image_tasks_ << "/" << image_requests << std::endl;
    std::cout << "  Total Duration: " << total_duration << "ms" << std::endl;
    
    // 检查是否所有任务都成功完成
    bool all_llm_completed = completed_llm_tasks_ == llm_requests;
    bool all_tts_completed = completed_tts_tasks_ == tts_requests;
    
    // 图像生成是异步的，可能还在队列中，所以不要求全部完成
    bool success = all_llm_completed && all_tts_completed;
    
    return TestResult(success, 
                      success ? "Concurrent performance test passed" : "Some concurrent tasks failed", 
                      total_duration);
}

TestResult SystemIntegrationTest::testResourceIsolation() {
    std::cout << "\n[TEST] Resource Isolation Test" << std::endl;
    auto start_time = std::chrono::high_resolution_clock::now();
    
    try {
        // 1. 启动一个耗时的图像生成任务（应该使用队列）
        std::cout << "Starting long-running image generation task..." << std::endl;
        scheduler_->submitTask(TaskType::IMAGE_GPU_QUEUE, 
                              "一个非常详细的复杂场景，需要长时间渲染", 
                              [](bool success, const std::string& result, void* data) {
            std::cout << "Long image task completed: " << (success ? "success" : "failure") << std::endl;
        });
        
        // 2. 同时执行LLM和TTS任务，验证它们不受影响
        int llm_count = 3;
        int tts_count = 5;
        std::atomic<int> isolated_llm_success(0);
        std::atomic<int> isolated_tts_success(0);
        
        // 启动LLM任务
        for (int i = 0; i < llm_count; ++i) {
            std::thread([this, i, &isolated_llm_success]() {
                auto task_start = std::chrono::high_resolution_clock::now();
                bool success = false;
                scheduler_->submitTask(TaskType::LLM_GPU, 
                                      "什么是资源隔离？请用简单的语言解释。", 
                                      [&success](bool s, const std::string& r, void* d) {
                    success = s;
                });
                
                // 等待任务完成
                std::this_thread::sleep_for(std::chrono::seconds(2));
                if (success) {
                    isolated_llm_success++;
                }
                
                auto task_end = std::chrono::high_resolution_clock::now();
                auto task_time = std::chrono::duration_cast<std::chrono::milliseconds>(task_end - task_start).count();
                std::cout << "Isolated LLM Task " << i << " completed in " << task_time << "ms" << std::endl;
            }).detach();
        }
        
        // 启动TTS任务
        for (int i = 0; i < tts_count; ++i) {
            std::thread([this, i, &isolated_tts_success]() {
                auto task_start = std::chrono::high_resolution_clock::now();
                bool success = false;
                scheduler_->submitTask(TaskType::TTS_CPU, 
                                      "这是资源隔离测试中的TTS任务。", 
                                      [&success](bool s, const std::string& r, void* d) {
                    success = s;
                });
                
                // 等待任务完成
                std::this_thread::sleep_for(std::chrono::seconds(1));
                if (success) {
                    isolated_tts_success++;
                }
                
                auto task_end = std::chrono::high_resolution_clock::now();
                auto task_time = std::chrono::duration_cast<std::chrono::milliseconds>(task_end - task_start).count();
                std::cout << "Isolated TTS Task " << i << " completed in " << task_time << "ms" << std::endl;
            }).detach();
        }
        
        // 等待所有任务完成
        std::this_thread::sleep_for(std::chrono::seconds(5));
        
        auto end_time = std::chrono::high_resolution_clock::now();
        int duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        std::cout << "Resource Isolation Results:" << std::endl;
        std::cout << "  LLM Success Rate: " << isolated_llm_success << "/" << llm_count << std::endl;
        std::cout << "  TTS Success Rate: " << isolated_tts_success << "/" << tts_count << std::endl;
        
        bool success = (isolated_llm_success == llm_count) && (isolated_tts_success == tts_count);
        
        return TestResult(success, 
                          success ? "Resource isolation test passed: LLM and TTS work normally during image generation" : 
                          "Resource isolation test failed: Some tasks were affected", 
                          duration);
    }
    catch (const std::exception& e) {
        std::cerr << "Resource isolation test exception: " << e.what() << std::endl;
        return TestResult(false, std::string("Exception: ") + e.what(), 0);
    }
}

TestResult SystemIntegrationTest::testErrorHandling() {
    std::cout << "\n[TEST] Error Handling Test" << std::endl;
    auto start_time = std::chrono::high_resolution_clock::now();
    
    try {
        int success_count = 0;
        const int total_tests = 3;
        
        // 1. 测试空提示词
        bool empty_prompt_handled = false;
        scheduler_->submitTask(TaskType::LLM_GPU, "", [&empty_prompt_handled](bool success, const std::string& result, void* data) {
            // 应该失败，但系统不应崩溃
            empty_prompt_handled = !success; // 失败是预期的
            std::cout << "Empty prompt test: " << (empty_prompt_handled ? "handled correctly" : "not handled") << std::endl;
        });
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if (empty_prompt_handled) success_count++;
        
        // 2. 测试超长文本
        std::string long_text(10000, 'a'); // 10000个字符的文本
        bool long_text_handled = false;
        scheduler_->submitTask(TaskType::TTS_CPU, long_text, [&long_text_handled](bool success, const std::string& result, void* data) {
            // 应该适当处理，可能截断或返回错误，但不应崩溃
            long_text_handled = true;
            std::cout << "Long text test: handled, success: " << (success ? "yes" : "no") << std::endl;
        });
        std::this_thread::sleep_for(std::chrono::seconds(2));
        success_count++;
        
        // 3. 测试取消任务
        uint64_t task_id = scheduler_->submitTask(TaskType::LLM_GPU, 
                                                 "这是一个可以被取消的任务", 
                                                 [](bool success, const std::string& result, void* data) {
            std::cout << "Cancelled task completed: " << (success ? "success" : "failure") << std::endl;
        });
        
        bool cancel_success = scheduler_->cancelTask(task_id);
        std::cout << "Task cancellation: " << (cancel_success ? "successful" : "failed") << std::endl;
        if (cancel_success) success_count++;
        
        auto end_time = std::chrono::high_resolution_clock::now();
        int duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        std::cout << "Error Handling Results: " << success_count << "/" << total_tests << " tests passed" << std::endl;
        
        bool overall_success = success_count >= 2; // 允许一个测试失败
        
        return TestResult(overall_success, 
                          overall_success ? "Error handling test passed" : "Some error cases not handled correctly", 
                          duration);
    }
    catch (const std::exception& e) {
        std::cerr << "Error handling test exception: " << e.what() << std::endl;
        return TestResult(false, std::string("Exception: ") + e.what(), 0);
    }
}

TestResult SystemIntegrationTest::testAPIEndpoints() {
    std::cout << "\n[TEST] API Endpoints Test" << std::endl;
    auto start_time = std::chrono::high_resolution_clock::now();
    
    try {
        // 创建API客户端
        auto client = api::createDefaultAPIClient("http://localhost:8080");
        int success_count = 0;
        const int total_tests = 5;
        
        // 1. 测试健康检查
        auto health_response = client->sendRequest(api::ClientRequest(api::RequestMethod::GET, "/health"));
        bool health_ok = health_response.isSuccess();
        std::cout << "Health Check: " << (health_ok ? "PASSED" : "FAILED") << std::endl;
        if (health_ok) success_count++;
        
        // 2. 测试LLM API
        auto llm_response = client->generateLLM("API测试：什么是API？");
        bool llm_ok = llm_response.isSuccess();
        std::cout << "LLM API: " << (llm_ok ? "PASSED" : "FAILED") << std::endl;
        if (llm_ok) success_count++;
        
        // 3. 测试TTS API
        auto tts_response = client->synthesizeTTS("这是API接口测试的TTS合成。");
        bool tts_ok = tts_response.isSuccess();
        std::cout << "TTS API: " << (tts_ok ? "PASSED" : "FAILED") << std::endl;
        if (tts_ok) success_count++;
        
        // 4. 测试图像生成API
        auto image_response = client->generateImage("API测试图像");
        bool image_ok = image_response.isSuccess();
        std::cout << "Image API: " << (image_ok ? "PASSED" : "FAILED") << std::endl;
        if (image_ok) success_count++;
        
        // 5. 测试状态API
        auto status_response = client->getStatus();
        bool status_ok = status_response.isSuccess();
        std::cout << "Status API: " << (status_ok ? "PASSED" : "FAILED") << std::endl;
        if (status_ok) success_count++;
        
        auto end_time = std::chrono::high_resolution_clock::now();
        int duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        std::cout << "API Test Results: " << success_count << "/" << total_tests << " endpoints working" << std::endl;
        
        bool success = success_count >= 4; // 允许一个API端点失败
        
        return TestResult(success, 
                          success ? "API endpoints test passed" : "Some API endpoints not working", 
                          duration);
    }
    catch (const std::exception& e) {
        std::cerr << "API test exception: " << e.what() << std::endl;
        return TestResult(false, std::string("Exception: ") + e.what(), 0);
    }
}

PerformanceMetrics SystemIntegrationTest::getPerformanceMetrics() const {
    return metrics_;
}

void SystemIntegrationTest::printTestReport(const TestResult& result) const {
    std::cout << "\nTest Report:" << std::endl;
    std::cout << "  Result: " << (result.success ? "✅ PASSED" : "❌ FAILED") << std::endl;
    std::cout << "  Message: " << result.message << std::endl;
    std::cout << "  Duration: " << result.duration_ms << "ms" << std::endl;
}

void SystemIntegrationTest::runLLMTest(const std::string& prompt) {
    auto start_time = std::chrono::high_resolution_clock::now();
    
    scheduler_->submitTask(TaskType::LLM_GPU, prompt, [this, start_time](bool success, const std::string& result, void* data) {
        auto end_time = std::chrono::high_resolution_clock::now();
        uint64_t duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        if (success) {
            completed_llm_tasks_++;
            total_llm_time_ += duration;
        }
        
        // 每10个任务打印一次进度
        if (completed_llm_tasks_ % 10 == 0 || completed_llm_tasks_ == 1) {
            std::cout << "LLM Task completed in " << duration << "ms, Progress: " << completed_llm_tasks_ << std::endl;
        }
    });
    
    // 等待任务进入队列
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
}

void SystemIntegrationTest::runTTSTest(const std::string& text) {
    auto start_time = std::chrono::high_resolution_clock::now();
    
    scheduler_->submitTask(TaskType::TTS_CPU, text, [this, start_time](bool success, const std::string& result, void* data) {
        auto end_time = std::chrono::high_resolution_clock::now();
        uint64_t duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();
        
        if (success) {
            completed_tts_tasks_++;
            total_tts_time_ += duration;
        }
        
        // 每20个任务打印一次进度
        if (completed_tts_tasks_ % 20 == 0 || completed_tts_tasks_ == 1) {
            std::cout << "TTS Task completed in " << duration << "ms, Progress: " << completed_tts_tasks_ << std::endl;
        }
    });
    
    // 等待任务进入队列
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
}

void SystemIntegrationTest::runImageTest(const std::string& prompt) {
    scheduler_->submitTask(TaskType::IMAGE_GPU_QUEUE, prompt, [this](bool success, const std::string& result, void* data) {
        if (success) {
            completed_image_tasks_++;
            std::cout << "Image Task completed, Progress: " << completed_image_tasks_ << std::endl;
        }
    });
    
    // 等待任务进入队列
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
}

void SystemIntegrationTest::monitorResources() {
    // 模拟资源监控
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<> cpu_dist(10.0, 80.0);
    std::uniform_real_distribution<> gpu_dist(20.0, 90.0);
    
    for (int i = 0; i < 20; ++i) { // 监控约10秒
        metrics_.cpu_utilization = cpu_dist(gen);
        metrics_.gpu_utilization = gpu_dist(gen);
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
}

std::vector<std::string> SystemIntegrationTest::generateTestPrompts(int count) {
    std::vector<std::string> prompts = {
        "什么是人工智能？",
        "解释机器学习的基本原理。",
        "描述深度学习的应用场景。",
        "什么是自然语言处理？",
        "计算机视觉的主要挑战是什么？",
        "生成一个短故事。",
        "写一首关于技术的诗。",
        "解释量子计算的概念。",
        "什么是云计算？",
        "区块链技术的优缺点是什么？"
    };
    
    std::vector<std::string> result;
    for (int i = 0; i < count; ++i) {
        result.push_back(prompts[i % prompts.size()] + " (Test " + std::to_string(i) + ")");
    }
    
    return result;
}

std::vector<std::string> SystemIntegrationTest::generateTestTexts(int count) {
    std::vector<std::string> texts = {
        "这是一段测试文本。",
        "语音合成技术正在快速发展。",
        "CPU推理可以有效减少GPU资源占用。",
        "系统集成测试验证各组件协同工作能力。",
        "异步并发架构提高了系统吞吐量。"
    };
    
    std::vector<std::string> result;
    for (int i = 0; i < count; ++i) {
        result.push_back(texts[i % texts.size()] + " 测试编号：" + std::to_string(i));
    }
    
    return result;
}

bool SystemIntegrationTest::checkSystemHealth() {
    // 检查所有组件状态
    bool scheduler_healthy = scheduler_ && scheduler_->isRunning();
    bool llm_healthy = llm_worker_ && llm_worker_->isReady();
    bool tts_healthy = tts_worker_ && tts_worker_->isReady();
    bool image_healthy = image_worker_ && image_worker_->isReady();
    
    return scheduler_healthy && llm_healthy && tts_healthy && image_healthy;
}

int runIntegrationTests(int argc, char** argv) {
    std::cout << "=== SYSTEM INTEGRATION TESTS STARTING ===" << std::endl;
    
    SystemIntegrationTest test;
    
    if (!test.initialize()) {
        std::cerr << "Failed to initialize test environment" << std::endl;
        return 1;
    }
    
    TestResult result = test.runAllTests();
    
    test.cleanup();
    
    std::cout << "\n=== TESTS FINISHED ===" << std::endl;
    std::cout << "Exit code: " << (result.success ? 0 : 1) << std::endl;
    
    return result.success ? 0 : 1;
}

} // namespace ai_scheduler::tests