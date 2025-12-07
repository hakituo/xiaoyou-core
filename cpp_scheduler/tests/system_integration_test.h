#ifndef SYSTEM_INTEGRATION_TEST_H
#define SYSTEM_INTEGRATION_TEST_H

#include <memory>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <condition_variable>
#include <functional>

// 前向声明
namespace ai_scheduler {
    class AsyncScheduler;
    class GPULLMWorker;
    class CPUTTSWorker;
    class GPUImageWorker;
    class TaskQueue;
    namespace api {
        class APIServer;
    }
}

namespace ai_scheduler::tests {

// 测试结果结构
struct TestResult {
    bool success;
    std::string message;
    int duration_ms;
    
    TestResult(bool s = false, const std::string& msg = "", int d = 0)
        : success(s), message(msg), duration_ms(d) {}
};

// 性能指标结构
struct PerformanceMetrics {
    int llm_requests_per_second;
    int tts_requests_per_second;
    int image_requests_queued;
    float average_llm_response_time;
    float average_tts_response_time;
    float cpu_utilization;
    float gpu_utilization;
    
    PerformanceMetrics()
        : llm_requests_per_second(0),
          tts_requests_per_second(0),
          image_requests_queued(0),
          average_llm_response_time(0.0f),
          average_tts_response_time(0.0f),
          cpu_utilization(0.0f),
          gpu_utilization(0.0f) {}
};

// 系统集成测试类
class SystemIntegrationTest {
public:
    SystemIntegrationTest();
    ~SystemIntegrationTest();
    
    // 初始化测试环境
    bool initialize();
    
    // 清理测试环境
    void cleanup();
    
    // 运行所有测试
    TestResult runAllTests();
    
    // 1. 基本功能测试
    TestResult testBasicFunctionality();
    
    // 2. 并发性能测试
    TestResult testConcurrentPerformance(int llm_requests, int tts_requests, int image_requests);
    
    // 3. 资源隔离测试
    TestResult testResourceIsolation();
    
    // 4. 错误处理测试
    TestResult testErrorHandling();
    
    // 5. API接口测试
    TestResult testAPIEndpoints();
    
    // 获取性能指标
    PerformanceMetrics getPerformanceMetrics() const;
    
    // 打印测试报告
    void printTestReport(const TestResult& result) const;
    
private:
    // 组件引用
    std::shared_ptr<AsyncScheduler> scheduler_;
    std::shared_ptr<GPULLMWorker> llm_worker_;
    std::shared_ptr<CPUTTSWorker> tts_worker_;
    std::shared_ptr<GPUImageWorker> image_worker_;
    std::shared_ptr<TaskQueue> image_queue_;
    std::shared_ptr<api::APIServer> api_server_;
    
    // 测试状态
    std::atomic<bool> is_initialized_;
    
    // 性能统计
    PerformanceMetrics metrics_;
    
    // 并发测试辅助
    std::atomic<int> completed_llm_tasks_;
    std::atomic<int> completed_tts_tasks_;
    std::atomic<int> completed_image_tasks_;
    std::atomic<uint64_t> total_llm_time_;
    std::atomic<uint64_t> total_tts_time_;
    
    // 线程同步
    std::mutex test_mutex_;
    std::condition_variable test_condition_;
    
    // 执行单个LLM测试
    void runLLMTest(const std::string& prompt);
    
    // 执行单个TTS测试
    void runTTSTest(const std::string& text);
    
    // 执行单个图像生成测试
    void runImageTest(const std::string& prompt);
    
    // 监控系统资源
    void monitorResources();
    
    // 生成测试数据
    std::vector<std::string> generateTestPrompts(int count);
    std::vector<std::string> generateTestTexts(int count);
    
    // 检查系统状态
    bool checkSystemHealth();
};

// 运行测试的便捷函数
int runIntegrationTests(int argc, char** argv);

} // namespace ai_scheduler::tests

#endif // SYSTEM_INTEGRATION_TEST_H