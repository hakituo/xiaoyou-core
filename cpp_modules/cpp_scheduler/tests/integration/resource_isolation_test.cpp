#include "resource_isolation_test.h"

namespace ai_scheduler::tests {

// 测试任务执行时间统计
static void analyzeTaskPerformance() {
    TestUtils::log("分析任务执行性能");
    
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    scheduler->initialize(4);
    
    // 测试不同任务类型的执行时间
    long long llmTime = TestUtils::measureExecutionTime([&scheduler]() {
        auto task = std::make_shared<Task<int>>(TaskType::LLM_INFERENCE, TaskPriority::HIGH);
        task->setTaskFunction([]() -> int {
            // 模拟LLM推理（较长时间）
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            return 1;
        });
        auto future = scheduler->submitTask(task);
        future->wait();
    });
    
    long long ttsTime = TestUtils::measureExecutionTime([&scheduler]() {
        auto task = std::make_shared<Task<int>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
        task->setTaskFunction([]() -> int {
            // 模拟TTS合成（中等时间）
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            return 2;
        });
        auto future = scheduler->submitTask(task);
        future->wait();
    });
    
    long long imgTime = TestUtils::measureExecutionTime([&scheduler]() {
        auto task = std::make_shared<Task<int>>(TaskType::IMAGE_GENERATION, TaskPriority::LOW);
        task->setTaskFunction([]() -> int {
            // 模拟图像生成（长时间）
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            return 3;
        });
        auto future = scheduler->submitTask(task);
        future->wait();
    });
    
    TestUtils::log("LLM任务平均执行时间: " + std::to_string(llmTime) + "ms");
    TestUtils::log("TTS任务平均执行时间: " + std::to_string(ttsTime) + "ms");
    TestUtils::log("图像生成任务平均执行时间: " + std::to_string(imgTime) + "ms");
    
    scheduler->shutdown();
}

// 测试并发任务吞吐量
static void testTaskThroughput() {
    TestUtils::log("测试任务吞吐量");
    
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    scheduler->initialize(8); // 使用较多线程
    
    const int totalTasks = 50;
    std::atomic<int> completedTasks{0};
    
    auto startTime = std::chrono::high_resolution_clock::now();
    
    std::vector<std::shared_ptr<std::future<void>>> futures;
    
    // 创建混合任务类型
    for (int i = 0; i < totalTasks; ++i) {
        TaskType taskType;
        TaskPriority priority;
        
        // 均匀分布任务类型
        if (i % 3 == 0) {
            taskType = TaskType::LLM_INFERENCE;
            priority = TaskPriority::HIGH;
        } else if (i % 3 == 1) {
            taskType = TaskType::TTS_SYNTHESIS;
            priority = TaskPriority::MEDIUM;
        } else {
            taskType = TaskType::IMAGE_GENERATION;
            priority = TaskPriority::LOW;
        }
        
        auto task = std::make_shared<Task<void>>(taskType, priority);
        task->setTaskFunction([&completedTasks, taskType]() {
            // 根据任务类型设置不同的执行时间
            int sleepTime;
            switch (taskType) {
                case TaskType::LLM_INFERENCE:
                    sleepTime = 50;
                    break;
                case TaskType::TTS_SYNTHESIS:
                    sleepTime = 20;
                    break;
                case TaskType::IMAGE_GENERATION:
                    sleepTime = 80;
                    break;
                default:
                    sleepTime = 30;
            }
            
            std::this_thread::sleep_for(std::chrono::milliseconds(sleepTime));
            completedTasks++;
        });
        
        futures.push_back(scheduler->submitTask(task));
    }
    
    // 等待所有任务完成
    for (auto& future : futures) {
        future->wait();
    }
    
    auto endTime = std::chrono::high_resolution_clock::now();
    auto totalDuration = std::chrono::duration_cast<std::chrono::milliseconds>(endTime - startTime).count();
    
    double tasksPerSecond = (totalDuration > 0) ? (totalTasks * 1000.0 / totalDuration) : 0;
    
    TestUtils::log("总任务数: " + std::to_string(totalTasks));
    TestUtils::log("总执行时间: " + std::to_string(totalDuration) + "ms");
    TestUtils::log("吞吐量: " + std::to_string(tasksPerSecond) + " 任务/秒");
    TestUtils::log("完成任务数: " + std::to_string(completedTasks));
    
    scheduler->shutdown();
}

// 测试任务取消功能
static void testTaskCancellation() {
    TestUtils::log("测试任务取消功能");
    
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    scheduler->initialize(2);
    
    // 创建一个长时间运行的任务
    auto longTask = std::make_shared<Task<int>>(TaskType::IMAGE_GENERATION, TaskPriority::LOW);
    longTask->setTaskFunction([]() -> int {
        // 模拟长时间运行
        std::this_thread::sleep_for(std::chrono::seconds(5));
        return 1;
    });
    
    auto future = scheduler->submitTask(longTask);
    
    // 等待一小段时间后取消任务
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    
    bool cancelled = scheduler->cancelTask(longTask->getTaskId());
    TestUtils::log("任务取消请求: " + std::string(cancelled ? "成功" : "失败"));
    
    try {
        future->get();
        TestUtils::log("警告: 已取消的任务仍返回了结果");
    } catch (const std::exception& e) {
        TestUtils::log("成功捕获已取消任务的异常: " + std::string(e.what()));
    }
    
    scheduler->shutdown();
}

// 测试资源监控功能
static void testResourceMonitoring() {
    TestUtils::log("测试资源监控功能");
    
    auto ttsWorker = std::make_shared<CPUTTSWorker>("TTS_Monitor_Worker", TTSEngineType::PYTTSX3);
    if (ttsWorker->initialize()) {
        // 运行一些任务
        auto ttsParams = std::make_shared<TTSParams>("测试资源监控功能", "test", 1.0);
        auto ttsTask = createTTSTask("monitor_task", ttsParams);
        
        std::string taskId = ttsWorker->submitTask(ttsTask);
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        
        // 获取worker统计信息
        auto stats = ttsWorker->getWorkerStats();
        TestUtils::log("TTS Worker 统计信息:");
        TestUtils::log("  总任务数: " + std::to_string(stats.totalTasks));
        TestUtils::log("  成功任务数: " + std::to_string(stats.completedTasks));
        TestUtils::log("  失败任务数: " + std::to_string(stats.failedTasks));
        TestUtils::log("  平均执行时间: " + std::to_string(stats.averageExecutionTime) + "ms");
        
        ttsWorker->shutdown();
    } else {
        TestUtils::log("TTS Worker初始化失败，跳过资源监控测试");
    }
}

// 增强版的资源隔离测试
static void testEnhancedResourceIsolation() {
    TestUtils::log("测试增强版资源隔离");
    
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    scheduler->initialize(8);
    
    std::atomic<int> llmCompleted{0};
    std::atomic<int> ttsCompleted{0};
    std::atomic<int> imgCompleted{0};
    
    // 启动多个长时间运行的LLM任务 (模拟GPU占用)
    std::vector<std::shared_ptr<std::future<void>>> llmFutures;
    for (int i = 0; i < 3; ++i) {
        auto task = std::make_shared<Task<void>>(TaskType::LLM_INFERENCE, TaskPriority::HIGH);
        task->setTaskFunction([&llmCompleted]() {
            std::this_thread::sleep_for(std::chrono::seconds(2));
            llmCompleted++;
        });
        llmFutures.push_back(scheduler->submitTask(task));
    }
    
    // 立即启动多个TTS任务 (CPU任务应该不受LLM影响)
    std::vector<std::shared_ptr<std::future<void>>> ttsFutures;
    for (int i = 0; i < 5; ++i) {
        auto task = std::make_shared<Task<void>>(TaskType::TTS_SYNTHESIS, TaskPriority::MEDIUM);
        task->setTaskFunction([&ttsCompleted]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            ttsCompleted++;
        });
        ttsFutures.push_back(scheduler->submitTask(task));
    }
    
    // 启动图像生成任务 (应该排队等待)
    std::vector<std::shared_ptr<std::future<void>>> imgFutures;
    for (int i = 0; i < 2; ++i) {
        auto task = std::make_shared<Task<void>>(TaskType::IMAGE_GENERATION, TaskPriority::LOW);
        task->setTaskFunction([&imgCompleted]() {
            std::this_thread::sleep_for(std::chrono::seconds(1));
            imgCompleted++;
        });
        imgFutures.push_back(scheduler->submitTask(task));
    }
    
    // 检查TTS任务是否能在LLM任务运行时完成
    std::this_thread::sleep_for(std::chrono::milliseconds(800));
    
    int ttsProgress = ttsCompleted.load();
    TestUtils::log("在LLM任务运行期间，TTS任务完成数: " + std::to_string(ttsProgress));
    
    // 等待所有任务完成
    for (auto& future : ttsFutures) future->wait();
    for (auto& future : imgFutures) future->wait();
    for (auto& future : llmFutures) future->wait();
    
    TestUtils::log("最终完成统计:");
    TestUtils::log("  LLM任务: " + std::to_string(llmCompleted) + "/3");
    TestUtils::log("  TTS任务: " + std::to_string(ttsCompleted) + "/5");
    TestUtils::log("  图像任务: " + std::to_string(imgCompleted) + "/2");
    
    // 验证资源隔离效果: TTS任务应该能在LLM任务运行时完成大部分
    bool isolationEffective = (ttsProgress >= 3); // TTS应该至少完成3个
    TestUtils::assertEquals("资源隔离有效性", true, isolationEffective);
    
    scheduler->shutdown();
}

// 测试稳定性和长时间运行
static void testStability() {
    TestUtils::log("测试系统稳定性");
    
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    scheduler->initialize(4);
    
    const int iterations = 10;
    int successfulIterations = 0;
    
    for (int i = 0; i < iterations; ++i) {
        TestUtils::log("稳定性测试迭代: " + std::to_string(i + 1) + "/" + std::to_string(iterations));
        
        try {
            // 每次迭代提交多种任务
            std::vector<std::shared_ptr<std::future<int>>> futures;
            
            for (int j = 0; j < 5; ++j) {
                TaskType taskType = static_cast<TaskType>(j % 3);
                auto task = std::make_shared<Task<int>>(taskType, TaskPriority::MEDIUM);
                task->setTaskFunction([j]() -> int {
                    std::this_thread::sleep_for(std::chrono::milliseconds(50 + j * 10));
                    return j;
                });
                futures.push_back(scheduler->submitTask(task));
            }
            
            // 等待所有任务完成
            for (auto& future : futures) {
                future->get();
            }
            
            successfulIterations++;
        } catch (const std::exception& e) {
            TestUtils::log("迭代失败: " + std::string(e.what()));
        }
    }
    
    TestUtils::log("稳定性测试: " + std::to_string(successfulIterations) + "/" + std::to_string(iterations) + " 迭代成功");
    
    scheduler->shutdown();
    
    // 稳定性测试应该至少有80%的迭代成功
    bool stable = (successfulIterations >= iterations * 0.8);
    TestUtils::assertEquals("系统稳定性", true, stable);
}

} // namespace ai_scheduler::tests

// 测试程序入口函数
int main() {
    std::cout << "资源隔离架构 - 集成测试套件\n" << std::endl;
    
    try {
        // 运行核心集成测试
        ai_scheduler::tests::runIntegrationTests();
        
        // 运行额外的测试
        std::cout << "\n运行额外的增强测试...\n" << std::endl;
        
        ai_scheduler::tests::analyzeTaskPerformance();
        ai_scheduler::tests::testTaskThroughput();
        ai_scheduler::tests::testTaskCancellation();
        ai_scheduler::tests::testResourceMonitoring();
        ai_scheduler::tests::testEnhancedResourceIsolation();
        ai_scheduler::tests::testStability();
        
        std::cout << "\n所有测试完成!\n" << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "测试运行失败: " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "测试运行时发生未知错误" << std::endl;
        return 1;
    }
}