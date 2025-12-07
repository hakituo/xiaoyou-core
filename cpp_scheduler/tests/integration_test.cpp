#include "integration_test.h"

#include <iostream>
#include <string>
#include <memory>
#include <future>

namespace ai_scheduler::tests {

// 为方便测试，实现一个简单的Mock TaskContext
class MockTaskContext : public ITaskContext {
public:
    MockTaskContext(TaskType type, TaskPriority priority)
        : taskType_(type), taskPriority_(priority), taskId_(0) {}
    
    TaskType getTaskType() const override {
        return taskType_;
    }
    
    TaskPriority getTaskPriority() const override {
        return taskPriority_;
    }
    
    uint64_t getTaskId() const override {
        return taskId_;
    }
    
    void setProgress(float progress) override {
        // 模拟进度更新
        currentProgress_ = progress;
    }
    
    float getProgress() const {
        return currentProgress_;
    }
    
private:
    TaskType taskType_;
    TaskPriority taskPriority_;
    uint64_t taskId_;
    float currentProgress_ = 0.0f;
};

// Mock Worker类，用于测试
class MockWorker : public IWorker {
public:
    MockWorker(const std::string& name) : name_(name), initialized_(false) {}
    
    bool initialize() override {
        initialized_ = true;
        return true;
    }
    
    void cleanup() override {
        initialized_ = false;
    }
    
    bool isInitialized() const override {
        return initialized_;
    }
    
    const std::string& getName() const override {
        return name_;
    }
    
    // Mock处理函数
    template<typename T> T processTask(const T& input) {
        return input; // 原样返回
    }
    
private:
    std::string name_;
    bool initialized_;
};

// 资源隔离调度器测试的扩展实现
// 这里可以添加一些需要具体实现的测试辅助函数

// 集成测试运行器
bool runIntegrationTest(const std::string& testName) {
    std::cout << "运行指定测试: " << testName << std::endl;
    
    if (testName == "all") {
        return runAllIntegrationTests();
    } else if (testName == "scheduler") {
        ResourceIsolationSchedulerTest test;
        return test.run() == TestResult::SUCCESS;
    } else if (testName == "api") {
        APIServerTest test;
        return test.run() == TestResult::SUCCESS;
    } else if (testName == "isolation") {
        ResourceIsolationTest test;
        return test.run() == TestResult::SUCCESS;
    } else if (testName == "queue") {
        TaskQueueTest test;
        return test.run() == TestResult::SUCCESS;
    } else if (testName == "blackbox") {
        BlackBoxIntegrationTest test;
        return test.run() == TestResult::SUCCESS;
    } else {
        std::cout << "未知的测试名称: " << testName << std::endl;
        return false;
    }
}

} // namespace ai_scheduler::tests

// 主测试入口函数
int main(int argc, char** argv) {
    std::string testName = "all";
    
    if (argc > 1) {
        testName = argv[1];
    }
    
    return ai_scheduler::tests::runIntegrationTest(testName) ? 0 : 1;
}