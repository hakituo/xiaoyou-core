#include "core/async_scheduler.h"
#include "queue/task_queue.h"
#include <iostream>
#include <thread>
#include <chrono>

using namespace ai_scheduler;

// 示例任务类
class ExampleTask : public Task {
public:
    ExampleTask(TaskType type, const std::string& name)
        : Task(type), name_(name) {
    }
    
    void execute() override {
        std::cout << "Executing task: " << name_ << " of type " 
                  << static_cast<int>(getType()) << std::endl;
        
        // 模拟任务执行
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        
        notifyComplete(true, "Task " + name_ + " completed successfully");
    }
    
private:
    std::string name_;
};

int main(int argc, char* argv[]) {
    std::cout << "=== AI Scheduler Architecture Demo ===" << std::endl;
    
    // 1. 初始化异步调度器
    AsyncScheduler scheduler;
    if (!scheduler.initialize(2, 4)) {  // 2个GPU worker, 4个CPU worker
        std::cerr << "Failed to initialize scheduler" << std::endl;
        return 1;
    }
    
    // 2. 启动调度器（在单独线程中运行事件循环）
    std::thread scheduler_thread([&scheduler]() {
        scheduler.start();
    });
    
    // 3. 等待调度器启动
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    
    // 4. 提交示例任务
    std::cout << "\nSubmitting example tasks..." << std::endl;
    
    // LLM任务（GPU，高优先级）
    auto llm_task = std::make_shared<ExampleTask>(TaskType::LLM_GPU, "LLM推理任务");
    llm_task->setCallback([](bool success, const std::string& result) {
        std::cout << "LLM Task callback: " << (success ? "success" : "failed") 
                  << ", result: " << result << std::endl;
    });
    scheduler.submitTask(llm_task);
    
    // TTS任务（CPU）
    auto tts_task = std::make_shared<ExampleTask>(TaskType::TTS_CPU, "TTS语音合成任务");
    tts_task->setCallback([](bool success, const std::string& result) {
        std::cout << "TTS Task callback: " << (success ? "success" : "failed") 
                  << ", result: " << result << std::endl;
    });
    scheduler.submitTask(tts_task);
    
    // 图像生成任务（GPU队列）
    auto img_task = std::make_shared<ExampleTask>(TaskType::IMAGE_GPU_QUEUE, "图像生成任务");
    img_task->setCallback([](bool success, const std::string& result) {
        std::cout << "Image Task callback: " << (success ? "success" : "failed") 
                  << ", result: " << result << std::endl;
    });
    scheduler.submitTask(img_task);
    
    // 5. 等待任务完成
    // 使用更高效的等待方式，避免长时间阻塞主线程
    // 实际应用中应该使用条件变量或信号量
    int wait_count = 0;
    while (wait_count < 20) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        wait_count++;
    }
    
    // 6. 展示GPU图像生成队列的独立使用
    std::cout << "\nDemonstrating GPU Image Task Queue..." << std::endl;
    TaskQueue img_queue(1);  // 只允许一个并发任务
    img_queue.initialize();
    
    // 添加多个图像生成任务
    for (int i = 0; i < 3; ++i) {
        auto task_id = img_queue.enqueue([i]() {
            std::cout << "Processing image task " << i << " on GPU..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            std::cout << "Image task " << i << " completed" << std::endl;
        }, i);
        std::cout << "Enqueued image task with ID: " << task_id << std::endl;
    }
    
    // 等待图像任务完成
    // 优化：分段等待
    wait_count = 0;
    while (wait_count < 20) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        wait_count++;
    }
    img_queue.shutdown();
    
    // 7. 停止调度器
    std::cout << "\nShutting down scheduler..." << std::endl;
    scheduler.stop();
    
    if (scheduler_thread.joinable()) {
        scheduler_thread.join();
    }
    
    std::cout << "\nDemo completed successfully!" << std::endl;
    std::cout << "\n=== Architecture Summary ===" << std::endl;
    std::cout << "1. GPU Worker #1: Dedicated to LLM inference (real-time)" << std::endl;
    std::cout << "2. CPU Workers: Handle TTS synthesis (parallel, no GPU usage)" << std::endl;
    std::cout << "3. GPU Worker #2: Image generation with async queue (non-blocking)" << std::endl;
    
    return 0;
}