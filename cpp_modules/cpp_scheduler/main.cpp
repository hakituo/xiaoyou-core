#include "core/resource_isolation_scheduler.h"
#include "workers/cpu_tts_worker.h"
#include "workers/gpu_tts_worker.h"
#include "workers/gpu_llm_worker.h"
#include "api/api_server.h"
#include "api/api_client.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <string>
#include <algorithm>
#include <atomic>
#include <future>
#include <vector>
#include <mutex>

using namespace ai_scheduler;
using namespace ai_scheduler::api;

static void runNativeExecutorBenchmark() {
    const int iterations = 200000;

    {
        NativeExecutor executor;
        executor.start();

        std::atomic<int> done{0};
        auto done_promise = std::make_shared<std::promise<void>>();
        auto done_future = done_promise->get_future();

        auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < iterations; ++i) {
            executor.executeAsync([&done, done_promise]() {
                int v = done.fetch_add(1, std::memory_order_relaxed) + 1;
                if (v == iterations) {
                    done_promise->set_value();
                }
            });
        }
        auto t_submit = std::chrono::steady_clock::now();

        done_future.wait();
        auto t_done = std::chrono::steady_clock::now();

        executor.stop();

        auto submit_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_submit - t0).count();
        auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_done - t0).count();

        std::cout << "[BENCH] NativeExecutor dispatch" << std::endl;
        std::cout << "  iterations=" << iterations << std::endl;
        std::cout << "  submit_ms=" << submit_ms << std::endl;
        std::cout << "  total_ms=" << total_ms << std::endl;
    }

    {
        std::atomic<int> done{0};
        auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < iterations; ++i) {
            done.fetch_add(1, std::memory_order_relaxed);
        }
        auto t_done = std::chrono::steady_clock::now();
        auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_done - t0).count();

        std::cout << "[BENCH] No NativeExecutor (direct loop)" << std::endl;
        std::cout << "  iterations=" << iterations << std::endl;
        std::cout << "  total_ms=" << total_ms << std::endl;
    }

    struct IntervalState {
        std::mutex m;
        std::vector<int64_t> intervals_us;
        std::chrono::steady_clock::time_point last;
        bool has_last = false;
        std::atomic<bool> running{true};
    };

    auto summarize = [](const std::vector<int64_t>& v) {
        if (v.empty()) {
            std::cout << "  samples=0" << std::endl;
            return;
        }
        int64_t min_v = v[0];
        int64_t max_v = v[0];
        int64_t sum = 0;
        for (auto x : v) {
            min_v = (std::min)(min_v, x);
            max_v = (std::max)(max_v, x);
            sum += x;
        }
        double avg = static_cast<double>(sum) / static_cast<double>(v.size());
        std::cout << "  samples=" << v.size() << std::endl;
        std::cout << "  interval_us_avg=" << avg << std::endl;
        std::cout << "  interval_us_min=" << min_v << std::endl;
        std::cout << "  interval_us_max=" << max_v << std::endl;
    };

    const uint64_t interval_ms = 10;
    const auto run_ms = std::chrono::milliseconds(2000);

    {
        auto state = std::make_shared<IntervalState>();

        NativeExecutor executor;
        executor.start();
        executor.addTimer(interval_ms, interval_ms, [state]() {
            auto now = std::chrono::steady_clock::now();
            if (!state->has_last) {
                state->last = now;
                state->has_last = true;
                return;
            }
            auto dt = std::chrono::duration_cast<std::chrono::microseconds>(now - state->last).count();
            state->last = now;
            std::lock_guard<std::mutex> lock(state->m);
            state->intervals_us.push_back(dt);
        });

        std::this_thread::sleep_for(run_ms);
        executor.stop();

        std::vector<int64_t> v;
        {
            std::lock_guard<std::mutex> lock(state->m);
            v = state->intervals_us;
        }
        std::cout << "[BENCH] Timer jitter (NativeExecutor)" << std::endl;
        std::cout << "  interval_ms=" << interval_ms << std::endl;
        summarize(v);
    }

    {
        auto state = std::make_shared<IntervalState>();

        std::thread t([state, interval_ms]() {
            while (state->running.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
                auto now = std::chrono::steady_clock::now();
                if (!state->has_last) {
                    state->last = now;
                    state->has_last = true;
                    continue;
                }
                auto dt = std::chrono::duration_cast<std::chrono::microseconds>(now - state->last).count();
                state->last = now;
                std::lock_guard<std::mutex> lock(state->m);
                state->intervals_us.push_back(dt);
            }
        });

        std::this_thread::sleep_for(run_ms);
        state->running.store(false, std::memory_order_relaxed);
        t.join();

        std::vector<int64_t> v;
        {
            std::lock_guard<std::mutex> lock(state->m);
            v = state->intervals_us;
        }
        std::cout << "[BENCH] Timer jitter (std::thread sleep)" << std::endl;
        std::cout << "  interval_ms=" << interval_ms << std::endl;
        summarize(v);
    }
}

// 示例任务类
template<typename ResultType>
class ExampleTask : public ITask {
public:
    ExampleTask(::TaskType type, const std::string& name)
        : ITask(name, type, TaskPriority::MEDIUM), name_(name) {
    }
    
    void execute() override {
        std::cout << "Executing task: " << name_ << " of type " 
                  << static_cast<int>(getType()) << std::endl;
        
        // 模拟任务执行
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        
        setStatus(TaskStatus::COMPLETED);
    }

    std::shared_ptr<void> getResult() const override {
        return nullptr;
    }
    
private:
    std::string name_;
};

int main(int argc, char* argv[]) {
    std::cout << "=== AI Scheduler Architecture Demo ===" << std::endl;

    if (argc >= 2 && std::string(argv[1]) == "--bench-native-executor") {
        runNativeExecutorBenchmark();
        return 0;
    }
    
    // 1. 初始化资源隔离调度器
    auto scheduler = std::make_shared<ResourceIsolationScheduler>();
    if (!scheduler->initialize(4)) {  // 4个CPU线程
        std::cerr << "Failed to initialize scheduler" << std::endl;
        return 1;
    }
    
    // 2. 初始化Worker
    auto ttsCpuWorker = std::make_shared<CPUTTSWorker>("CPU_TTS_Worker");
    ttsCpuWorker->initialize();
    scheduler->addWorker(ttsCpuWorker);

    auto ttsGpuWorker = std::make_shared<GPUTTSWorker>("GPU_TTS_Worker");
    ttsGpuWorker->initialize();
    scheduler->addWorker(ttsGpuWorker);

    auto llmWorker = std::make_shared<GPULLMWorker>();
    llmWorker->initialize();
    scheduler->addWorker(llmWorker);

    // 3. 启动 API Server (Mock)
    auto apiServer = std::make_shared<APIServer>(8080);
    apiServer->setScheduler(scheduler);
    apiServer->setTTSWorker(ttsCpuWorker); // API Server 目前只接受一个 TTS Worker 指针，但不影响调度器内部逻辑
    apiServer->setLLMWorker(llmWorker);
    
    if (apiServer->start()) {
        std::cout << "API Server started on port 8080 (Mock Mode)" << std::endl;
    } else {
        std::cerr << "Failed to start API Server" << std::endl;
    }

    // 4. 提交示例任务 (Direct C++ Call)
    std::cout << "\n--- Direct C++ Task Submission ---" << std::endl;
    
    // LLM任务
    LLMInferenceRequest llmReq;
    llmReq.prompt = "Hello";
    auto llmTask = std::make_shared<LLMTask>(llmReq, llmWorker.get());
    scheduler->submitTask(llmTask);
    
    // TTS任务
    TTSParams ttsParams;
    ttsParams.text = "Hello world";
    auto ttsTask = std::make_shared<TTSTask>("tts_1", TaskPriority::MEDIUM, ttsParams);
    scheduler->submitTask(ttsTask);

    // 注：图像生成任务已迁移至 Python 侧实现，C++ 端仅保留资源协调能力

    // 5. 运行 API Client 示例 (Mock Client -> Mock Server Logic)
    std::cout << "\n--- API Client Example Run ---" << std::endl;
    runAPIClientExample();

    // 6. 等待任务完成
    std::cout << "\nWaiting for all tasks..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(3));
    
    std::cout << "Shutting down..." << std::endl;
    apiServer->stop();
    scheduler->shutdown();
    return 0;
}
