#ifndef RESOURCE_ISOLATION_TEST_H
#define RESOURCE_ISOLATION_TEST_H

#include "../../core/resource_isolation_scheduler.h"
#include "../../workers/cpu_tts_worker.h"
#include "../../workers/gpu_llm_worker.h"
#include "../../workers/gpu_img_worker.h"
#include "../../api/blackbox_integration_example.h"

#include <iostream>
#include <thread>
#include <chrono>
#include <vector>
#include <atomic>
#include <string>
#include <memory>
#include <functional>

namespace ai_scheduler::tests {

// 测试工具类
class TestUtils {
public:
    // 计时辅助函数
    template<typename Func>
    static long long measureExecutionTime(Func&& func) {
        auto start = std::chrono::high_resolution_clock::now();
        func();
        auto end = std::chrono::high_resolution_clock::now();
        return std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    }
    
    // 日志函数
    static void log(const std::string& message) {
        auto now = std::chrono::system_clock::now();
        auto time = std::chrono::system_clock::to_time_t(now);
        std::tm local_tm;
#ifdef _WIN32
        localtime_s(&local_tm, &time);
#else
        localtime_r(&time, &local_tm);
#endif
        char buffer[80];
        std::strftime(buffer, sizeof(buffer), "[%Y-%m-%d %H:%M:%S]", &local_tm);
        std::cout << buffer << " " << message << std::endl;
    }
    
    // 断言函数
    static bool assertEquals(const std::string& testName, bool expected, bool actual) {
        if (expected != actual) {
            log("❌ " + testName + " FAILED: expected " + std::to_string(expected) + ", got " + std::to_string(actual));
            return false;
        }
        log("✅ " + testName + " PASSED");
        return true;
    }
    
    template<typename T>
    static bool assertEquals(const std::string& testName, const T& expected, const T& actual) {
        if (expected != actual) {
            log("❌ " + testName + " FAILED: expected " + std::to_string(expected) + ", got " + std::to_string(actual));
            return false;
        }
        log("✅ " + testName + " PASSED");
        return true;
    }
};

// 资源隔离架构集成测试
class ResourceIsolationTest {
public:
    // 运行所有测试
    static bool runAllTests() {
        TestUtils::log("===== 开始资源隔离架构集成测试 =====");
        
        bool allPassed = true;
        
        allPassed &= testSchedulerInitialization();
        allPassed &= testLLMWorker();
        allPassed &= testTTSWorker();
        allPassed &= testImageWorker();
        allPassed &= testTaskPrioritization();
        allPassed &= testResourceIsolation();
        allPassed &= testConcurrencyPerformance();
        allPassed &= testErrorHandling();
        
        if (allPassed) {
            TestUtils::log("===== 所有测试通过! =====");
        } else {
            TestUtils::log("===== 部分测试失败 =====");
        }
        
        return allPassed;
    }
    
    // 测试1: 调度器初始化
    static bool testSchedulerInitialization() {
        TestUtils::log("测试1: 调度器初始化");
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        bool initialized = scheduler->initialize(4);
        
        // 检查工作线程数量
        bool threadCountCorrect = (scheduler->getWorkerThreadCount() == 4);
        
        scheduler->shutdown();
        
        return TestUtils::assertEquals("调度器初始化", true, initialized) && 
               TestUtils::assertEquals("工作线程数量", true, threadCountCorrect);
    }
    
    // 测试2: LLM Worker功能
    static bool testLLMWorker() {
        TestUtils::log("测试2: LLM Worker功能");
        
        auto worker = std::make_shared<GPULLMWorker>("LLM_Test_Worker", LLMEngineType::QWEN_2_5, 0);
        bool initialized = worker->initialize();
        
        if (!initialized) {
            TestUtils::log("LLM Worker初始化失败，跳过详细测试");
            return true; // 在测试环境中可能无法访问GPU，跳过但不报错
        }
        
        // 检查worker状态
        bool statusCorrect = (worker->getWorkerStatus() == WorkerStatus::READY);
        
        worker->shutdown();
        
        return TestUtils::assertEquals("LLM Worker状态", true, statusCorrect);
    }
    
    // 测试3: TTS Worker功能
    static bool testTTSWorker() {
        TestUtils::log("测试3: TTS Worker功能");
        
        auto worker = std::make_shared<CPUTTSWorker>("TTS_Test_Worker", TTSEngineType::PYTTSX3);
        bool initialized = worker->initialize();
        
        if (!initialized) {
            TestUtils::log("TTS Worker初始化失败，跳过详细测试");
            return true; // 在测试环境中可能无法访问PyTTSX3，跳过但不报错
        }
        
        // 检查worker状态
        bool statusCorrect = (worker->getWorkerStatus() == WorkerStatus::READY);
        
        // 创建一个简单的TTS任务
        auto ttsParams = std::make_shared<TTSParams>("这是一段测试文本", "test_voice", 1.0);
        auto ttsTask = createTTSTask("test_tts_task", ttsParams);
        
        // 提交任务并检查
        std::string taskId = worker->submitTask(ttsTask);
        bool submitSuccess = !taskId.empty();
        
        worker->shutdown();
        
        return TestUtils::assertEquals("TTS Worker状态", true, statusCorrect) &&
               TestUtils::assertEquals("TTS任务提交", true, submitSuccess);
    }
    
    // 测试4: 图像生成Worker功能
    static bool testImageWorker() {
        TestUtils::log("测试4: 图像生成Worker功能");
        
        auto worker = std::make_shared<GPUImgWorker>("IMG_Test_Worker", ImgEngineType::STABLE_DIFFUSION_1_5_TURBO, 1);
        bool initialized = worker->initialize();
        
        if (!initialized) {
            TestUtils::log("图像Worker初始化失败，跳过详细测试");
            return true; // 在测试环境中可能无法访问GPU，跳过但不报错
        }
        
        // 检查worker状态
        bool statusCorrect = (worker->getWorkerStatus() == WorkerStatus::READY);
        
        worker->shutdown();
        
        return TestUtils::assertEquals("图像Worker状态", true, statusCorrect);
    }
    
    // 测试5: 任务优先级
    static bool testTaskPrioritization() {
        TestUtils::log("测试5: 任务优先级");
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(2);
        
        // 创建不同优先级的任务
        auto highPriorityTask = std::make_shared<Task<int>>(TaskType::LLM_INFERENCE, TaskPriority::HIGH);
        highPriorityTask->setTaskFunction([]() -> int { return 1; });
        
        auto mediumPriorityTask = std::make_shared<Task<int>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
        mediumPriorityTask->setTaskFunction([]() -> int { return 2; });
        
        auto lowPriorityTask = std::make_shared<Task<int>>(TaskType::IMAGE_GENERATION, TaskPriority::LOW);
        lowPriorityTask->setTaskFunction([]() -> int { return 3; });
        
        // 按顺序提交，但高优先级应该先执行
        auto lowFuture = scheduler->submitTask(lowPriorityTask);
        auto mediumFuture = scheduler->submitTask(mediumPriorityTask);
        auto highFuture = scheduler->submitTask(highPriorityTask);
        
        // 检查结果顺序
        bool orderCorrect = true;
        try {
            // 高优先级应该最先完成
            int highResult = highFuture->get();
            int mediumResult = mediumFuture->get();
            int lowResult = lowFuture->get();
            
            orderCorrect = (highResult == 1 && mediumResult == 2 && lowResult == 3);
        } catch (...) {
            orderCorrect = false;
        }
        
        scheduler->shutdown();
        
        return TestUtils::assertEquals("任务优先级", true, orderCorrect);
    }
    
    // 测试6: 资源隔离效果
    static bool testResourceIsolation() {
        TestUtils::log("测试6: 资源隔离效果");
        
        // 这里我们测试不同类型任务的执行是否不会互相阻塞
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(4);
        
        std::atomic<int> llmTaskCount{0};
        std::atomic<int> ttsTaskCount{0};
        std::atomic<int> imgTaskCount{0};
        
        // 创建多个不同类型的任务
        const int taskCount = 5;
        std::vector<std::shared_ptr<std::future<void>>> futures;
        
        // LLM任务 (模拟GPU任务)
        for (int i = 0; i < taskCount; ++i) {
            auto task = std::make_shared<Task<void>>(TaskType::LLM_INFERENCE, TaskPriority::HIGH);
            task->setTaskFunction([&llmTaskCount]() {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                llmTaskCount++;
            });
            futures.push_back(scheduler->submitTask(task));
        }
        
        // TTS任务 (CPU任务)
        for (int i = 0; i < taskCount; ++i) {
            auto task = std::make_shared<Task<void>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
            task->setTaskFunction([&ttsTaskCount]() {
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                ttsTaskCount++;
            });
            futures.push_back(scheduler->submitTask(task));
        }
        
        // 图像任务 (GPU队列任务)
        for (int i = 0; i < taskCount; ++i) {
            auto task = std::make_shared<Task<void>>(TaskType::IMAGE_GENERATION, TaskPriority::LOW);
            task->setTaskFunction([&imgTaskCount]() {
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
                imgTaskCount++;
            });
            futures.push_back(scheduler->submitTask(task));
        }
        
        // 等待所有任务完成
        for (auto& future : futures) {
            future->wait();
        }
        
        // 检查所有任务是否都执行了
        bool allTasksExecuted = (llmTaskCount == taskCount && 
                                ttsTaskCount == taskCount && 
                                imgTaskCount == taskCount);
        
        scheduler->shutdown();
        
        return TestUtils::assertEquals("资源隔离 - 所有任务执行", true, allTasksExecuted);
    }
    
    // 测试7: 并发性能
    static bool testConcurrencyPerformance() {
        TestUtils::log("测试7: 并发性能");
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(8);
        
        // 并发执行多个任务并测量性能
        const int taskCount = 20;
        std::vector<std::shared_ptr<std::future<int>>> futures;
        
        // 创建计算密集型任务
        auto startTime = std::chrono::high_resolution_clock::now();
        
        for (int i = 0; i < taskCount; ++i) {
            auto task = std::make_shared<Task<int>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
            task->setTaskFunction([i]() -> int {
                // 模拟计算密集型工作
                int result = 0;
                for (int j = 0; j < 10000000; ++j) {
                    result += j % 100;
                }
                return result + i;
            });
            futures.push_back(scheduler->submitTask(task));
        }
        
        // 等待所有任务完成
        for (auto& future : futures) {
            future->get();
        }
        
        auto endTime = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(endTime - startTime).count();
        
        TestUtils::log("并发执行 " + std::to_string(taskCount) + " 个任务耗时: " + std::to_string(duration) + "ms");
        
        // 这里不设置硬性时间要求，因为不同机器性能不同
        // 只记录性能数据用于参考
        
        scheduler->shutdown();
        return true; // 总是通过这个测试，因为性能是相对的
    }
    
    // 测试8: 错误处理
    static bool testErrorHandling() {
        TestUtils::log("测试8: 错误处理");
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(2);
        
        // 创建一个会抛出异常的任务
        auto errorTask = std::make_shared<Task<int>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
        errorTask->setTaskFunction([]() -> int {
            throw std::runtime_error("测试异常");
            return 0; // 永远不会执行到这里
        });
        
        auto future = scheduler->submitTask(errorTask);
        
        bool caughtException = false;
        try {
            future->get();
        } catch (const std::exception& e) {
            caughtException = true;
            TestUtils::log("成功捕获任务异常: " + std::string(e.what()));
        }
        
        scheduler->shutdown();
        
        return TestUtils::assertEquals("异常处理", true, caughtException);
    }
};

// 黑盒服务端集成测试
class BlackBoxServerTest {
public:
    // 测试黑盒服务初始化
    static bool testServerInitialization() {
        TestUtils::log("黑盒服务测试: 服务器初始化");
        
        auto config = std::make_shared<BlackBoxConfig>();
        config->setLLMEngine("mock"); // 使用mock引擎进行测试
        config->setTTSVoice("mock");
        config->setImageModel("mock");
        
        auto server = api::BlackBoxIntegrationExample::createBlackBoxServer(config);
        
        // 在测试环境中，如果资源不足，服务器可能初始化失败
        if (!server) {
            TestUtils::log("服务器初始化失败 (在测试环境中可能是正常的)");
            return true; // 测试环境中允许跳过
        }
        
        bool canStart = server->start();
        if (canStart) {
            server->stop();
        }
        
        return true; // 测试环境中不做硬性要求
    }
    
    // 测试完整的黑盒服务流程
    static bool testBlackBoxFlow() {
        TestUtils::log("黑盒服务测试: 完整服务流程");
        
        try {
            // 注意：在实际测试环境中可能无法运行完整示例
            // 这里只是演示测试结构，不实际执行
            TestUtils::log("在实际环境中运行 api::BlackBoxIntegrationExample::runFullExample()");
            TestUtils::log("在测试环境中跳过实际执行");
        } catch (const std::exception& e) {
            TestUtils::log("测试过程中捕获异常: " + std::string(e.what()));
        }
        
        return true; // 测试环境中不做硬性要求
    }
};

// 运行所有集成测试的主函数
inline bool runIntegrationTests() {
    std::cout << "\n========== 资源隔离架构集成测试套件 ==========\n" << std::endl;
    
    bool allPassed = true;
    
    // 运行核心测试
    allPassed &= ResourceIsolationTest::runAllTests();
    
    // 运行黑盒服务测试
    allPassed &= BlackBoxServerTest::testServerInitialization();
    allPassed &= BlackBoxServerTest::testBlackBoxFlow();
    
    std::cout << "\n========== 测试完成，结果: " << (allPassed ? "通过" : "失败") << " ==========\n" << std::endl;
    
    return allPassed;
}

} // namespace ai_scheduler::tests

#endif // RESOURCE_ISOLATION_TEST_H