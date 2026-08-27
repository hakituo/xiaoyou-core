#pragma once
#include <uv.h>
#include <thread>
#include <functional>
#include <atomic>
#include <mutex>
#include <vector>

namespace ai_scheduler {

class NativeExecutor {
public:
    NativeExecutor();
    ~NativeExecutor();

    bool start();
    void stop();

    void executeAsync(std::function<void()> func);
    void addTimer(uint64_t timeout_ms, uint64_t repeat_ms, std::function<void()> callback);

    uv_loop_t* getLoop() { return loop_; }
    bool isRunning() const { return running_; }

private:
    static void asyncCallback(uv_async_t* handle);
    static void timerCallback(uv_timer_t* handle);
    static void closeTimerHandle(uv_handle_t* handle);
    void loopThread();
    void closeAllTimersInLoopThread();

    uv_loop_t* loop_;
    uv_async_t async_handle_;
    std::thread thread_;
    std::atomic<bool> running_;
    std::atomic<bool> stop_requested_;
    
    std::mutex queue_mutex_;
    std::vector<std::function<void()>> task_queue_;

    std::mutex timers_mutex_;
    std::vector<uv_timer_t*> timers_;
    
    struct TimerData {
        NativeExecutor* executor;
        std::function<void()> callback;
    };
};

} // namespace ai_scheduler
