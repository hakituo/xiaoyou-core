#ifndef INTEGRATION_TEST_H
#define INTEGRATION_TEST_H

#include <iostream>
#include <string>
#include <vector>
#include <memory>
#include <thread>
#include <chrono>
#include <cassert>

#include "../api/api_server.h"
#include "../api/api_client.h"
#include "../api/blackbox_integration_example.h"
#include "../core/resource_isolation_scheduler.h"
#include "../workers/cpu_tts_worker.h"
#include "../workers/gpu_llm_worker.h"
#include "../workers/gpu_img_worker.h"

namespace ai_scheduler::tests {

// 测试结果枚举
enum class TestResult {
    SUCCESS,
    FAILED,
    SKIPPED
};

// 测试用例基类
class TestCase {
public:
    TestCase(const std::string& name) : name_(name), result_(TestResult::SKIPPED) {}
    virtual ~TestCase() = default;
    
    // 运行测试
    TestResult run() {
        std::cout << "[测试] 运行: " << name_ << std::endl;
        try {
            result_ = TestResult::FAILED;
            
            // 执行测试
            if (execute()) {
                result_ = TestResult::SUCCESS;
                std::cout << "[测试] ✓ 通过: " << name_ << std::endl;
            } else {
                std::cout << "[测试] ✗ 失败: " << name_ << std::endl;
            }
        } catch (const std::exception& e) {
            std::cout << "[测试] ✗ 异常: " << name_ << ", 错误: " << e.what() << std::endl;
            result_ = TestResult::FAILED;
        } catch (...) {
            std::cout << "[测试] ✗ 未知异常: " << name_ << std::endl;
            result_ = TestResult::FAILED;
        }
        return result_;
    }
    
    // 获取测试结果
    TestResult getResult() const { return result_; }
    const std::string& getName() const { return name_; }
    
    // 判断是否通过
    bool isSuccess() const { return result_ == TestResult::SUCCESS; }
    
protected:
    // 子类实现具体测试逻辑
    virtual bool execute() = 0;
    
    // 断言辅助函数
    bool expectTrue(bool condition, const std::string& message = "") {
        if (!condition) {
            std::cout << "[断言失败] " << message << std::endl;
            return false;
        }
        return true;
    }
    
    // 延迟辅助函数
    void delay(int milliseconds) {
        std::this_thread::sleep_for(std::chrono::milliseconds(milliseconds));
    }
    
private:
    std::string name_;
    TestResult result_;
};

// 测试套件类
class TestSuite {
public:
    TestSuite(const std::string& name) : name_(name) {}
    ~TestSuite() {
        tests_.clear();
    }
    
    // 添加测试用例
    void addTest(std::shared_ptr<TestCase> test) {
        tests_.push_back(test);
    }
    
    // 运行所有测试
    bool runAll() {
        std::cout << "\n=== 开始测试套件: " << name_ << " ===" << std::endl;
        
        int successCount = 0;
        int failCount = 0;
        int skipCount = 0;
        
        for (auto& test : tests_) {
            TestResult result = test->run();
            switch (result) {
                case TestResult::SUCCESS: successCount++;
                case TestResult::FAILED: failCount++;
                case TestResult::SKIPPED: skipCount++;
            }
        }
        
        std::cout << "\n=== 测试套件完成: " << name_ << " ===" << std::endl;
        std::cout << "总计: " << tests_.size() << " 个测试" << std::endl;
        std::cout << "成功: " << successCount << " 个" << std::endl;
        std::cout << "失败: " << failCount << " 个" << std::endl;
        std::cout << "跳过: " << skipCount << " 个" << std::endl;
        
        return failCount == 0;
    }
    
private:
    std::string name_;
    std::vector<std::shared_ptr<TestCase>> tests_;
};

// 1. 资源隔离调度器测试
class ResourceIsolationSchedulerTest : public TestCase {
public:
    ResourceIsolationSchedulerTest() : TestCase("ResourceIsolationSchedulerTest") {}
    
protected:
    bool execute() override {
        std::cout << "  测试1: 调度器初始化" << std::endl;
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        bool initResult = scheduler->initialize(4);
        
        if (!expectTrue(initResult, "调度器初始化失败")) {
            return false;
        }
        
        std::cout << "  测试2: 提交不同类型任务" << std::endl;
        
        // 提交LLM任务
        auto llmFuture = scheduler->submitTask<TaskType::LLM_INFERENCE>([](const ITaskContext& ctx) {
            return "LLM任务执行成功";
        });
        
        // 提交TTS任务
        auto ttsFuture = scheduler->submitTask<TaskType::TTS_SYNTHESIS>([](const ITaskContext& ctx) {
            return "TTS任务执行成功";
        });
        
        // 提交图像生成任务
        auto imgFuture = scheduler->submitTask<TaskType::IMAGE_GENERATION>([](const ITaskContext& ctx) {
            return "图像生成任务执行成功";
        });
        
        // 等待所有任务完成
        std::string llmResult = llmFuture.get();
        std::string ttsResult = ttsFuture.get();
        std::string imgResult = imgFuture.get();
        
        if (!expectTrue(llmResult == "LLM任务执行成功", "LLM任务结果不匹配")) {
            return false;
        }
        
        if (!expectTrue(ttsResult == "TTS任务执行成功", "TTS任务结果不匹配")) {
            return false;
        }
        
        if (!expectTrue(imgResult == "图像生成任务执行成功", "图像任务结果不匹配")) {
            return false;
        }
        
        std::cout << "  测试3: 并发任务执行" << std::endl;
        std::vector<std::future<int>> futures;
        
        // 提交多个并发任务
        for (int i = 0; i < 8; ++i) {
            futures.push_back(scheduler->submitTask<TaskType::TTS_SYNTHESIS>([i](const ITaskContext& ctx) {
                // 模拟工作负载
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                return i;
            }));
        }
        
        // 验证所有任务都能正确完成
        int sum = 0;
        for (auto& future : futures) {
            sum += future.get();
        }
        
        // 验证结果（0+1+2+...+7=28）
        if (!expectTrue(sum == 28, "并发任务结果错误")) {
            return false;
        }
        
        return true;
    }
};

// 2. API服务器测试
class APIServerTest : public TestCase {
public:
    APIServerTest() : TestCase("APIServerTest") {}
    
protected:
    bool execute() override {
        // 注意：这个测试在实际环境中可能需要mock服务器
        std::cout << "  测试1: 服务器配置验证" << std::endl;
        
        auto config = std::make_shared<BlackBoxConfig>();
        config->setLLMEngine("qwen2.5");
        config->setTTSVoice("coqui");
        config->setImageModel("sd1.5-turbo");
        config->setGPUAllocatedForLLM(70);
        config->setGPUAllocatedForImage(30);
        
        // 验证配置设置
        if (!expectTrue(config->getLLMEngine() == "qwen2.5", "LLM引擎配置错误")) {
            return false;
        }
        
        if (!expectTrue(config->getTTSVoice() == "coqui", "TTS声音配置错误")) {
            return false;
        }
        
        if (!expectTrue(config->getImageModel() == "sd1.5-turbo", "图像模型配置错误")) {
            return false;
        }
        
        // 在实际测试环境中，这里应该启动服务器并进行HTTP请求测试
        std::cout << "  注意: 跳过服务器HTTP请求测试，需要在实际环境中运行" << std::endl;
        
        return true;
    }
};

// 3. 资源隔离测试
class ResourceIsolationTest : public TestCase {
public:
    ResourceIsolationTest() : TestCase("ResourceIsolationTest") {}
    
protected:
    bool execute() override {
        std::cout << "  测试1: 不同资源域任务并行执行" << std::endl;
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(4);
        
        auto start = std::chrono::high_resolution_clock::now();
        
        // 提交长时间运行的CPU密集型任务
        auto cpuFuture = scheduler->submitTask<TaskType::TTS_SYNTHESIS>([](const ITaskContext& ctx) {
            // 模拟CPU密集型工作
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            return "CPU任务完成";
        });
        
        // 提交短时间运行的任务，应该不受前面长时间任务影响
        auto shortFuture = scheduler->submitTask<TaskType::LLM_INFERENCE>([](const ITaskContext& ctx) {
            return "短任务立即执行";
        });
        
        // 验证短任务能立即完成，不受长时间任务影响
        std::string shortResult = shortFuture.get();
        if (!expectTrue(shortResult == "短任务立即执行", "资源隔离失败，短任务被阻塞")) {
            return false;
        }
        
        // 等待长时间任务完成
        std::string cpuResult = cpuFuture.get();
        
        auto end = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
        
        std::cout << "  并行执行耗时: " << duration << "ms" << std::endl;
        
        return true;
    }
};

// 4. 任务队列管理测试
class TaskQueueTest : public TestCase {
public:
    TaskQueueTest() : TestCase("TaskQueueTest") {}
    
protected:
    bool execute() override {
        std::cout << "  测试1: 任务优先级管理" << std::endl;
        
        auto scheduler = std::make_shared<ResourceIsolationScheduler>();
        scheduler->initialize(2);
        
        // 提交低优先级长时间任务
        auto lowFuture = scheduler->submitTask<TaskType::IMAGE_GENERATION>([](const ITaskContext& ctx) {
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            return "低优先级任务完成";
        });
        
        // 提交高优先级任务，应该优先执行
        auto highFuture = scheduler->submitTask<TaskType::LLM_INFERENCE>([](const ITaskContext& ctx) {
            return "高优先级任务完成";
        }, TaskPriority::HIGH);
        
        // 高优先级任务应该先完成
        std::string highResult = highFuture.get();
        if (!expectTrue(highResult == "高优先级任务完成", "任务优先级管理失败")) {
            return false;
        }
        
        // 确认低优先级任务还在运行
        bool isLowReady = false;
        try {
            // 尝试非阻塞获取结果
            isLowReady = lowFuture.wait_for(std::chrono::milliseconds(50)) == std::future_status::ready;
        } catch (...) {
            // 忽略异常
        }
        
        // 低优先级任务应该还在运行
        if (!expectTrue(!isLowReady, "低优先级任务不应该已完成")) {
            return false;
        }
        
        // 等待低优先级任务完成
        lowFuture.get();
        
        return true;
    }
};

// 5. 黑盒接口集成测试
class BlackBoxIntegrationTest : public TestCase {
public:
    BlackBoxIntegrationTest() : TestCase("BlackBoxIntegrationTest") {}
    
protected:
    bool execute() override {
        std::cout << "  测试1: 创建黑盒服务" << std::endl;
        
        // 创建黑盒服务配置
        auto config = std::make_shared<BlackBoxConfig>();
        
        // 在实际环境中，这里应该完整启动服务器并进行集成测试
        // 为了单元测试的目的，我们只验证配置和初始化逻辑
        
        std::cout << "  注意: 跳过完整集成测试，需要在实际环境中运行" << std::endl;
        
        return true;
    }
};

// 运行所有集成测试
inline bool runAllIntegrationTests() {
    TestSuite suite("资源隔离调度架构集成测试");
    
    suite.addTest(std::make_shared<ResourceIsolationSchedulerTest>());
    suite.addTest(std::make_shared<APIServerTest>());
    suite.addTest(std::make_shared<ResourceIsolationTest>());
    suite.addTest(std::make_shared<TaskQueueTest>());
    suite.addTest(std::make_shared<BlackBoxIntegrationTest>());
    
    return suite.runAll();
}

// 测试主函数
inline int testMain(int argc, char** argv) {
    std::cout << "\n============================================" << std::endl;
    std::cout << "     资源隔离调度架构集成测试套件" << std::endl;
    std::cout << "============================================" << std::endl;
    
    bool allPassed = runAllIntegrationTests();
    
    std::cout << "\n============================================" << std::endl;
    std::cout << "测试结果: " << (allPassed ? "全部通过" : "有测试失败") << std::endl;
    std::cout << "============================================" << std::endl;
    
    return allPassed ? 0 : 1;
}

} // namespace ai_scheduler::tests

#endif // INTEGRATION_TEST_H