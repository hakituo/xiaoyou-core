#include "native_executor.h"
#include <algorithm>

namespace ai_scheduler {

NativeExecutor::NativeExecutor() : loop_(nullptr), running_(false), stop_requested_(false) {
    loop_ = uv_loop_new();
    uv_async_init(loop_, &async_handle_, asyncCallback);
    async_handle_.data = this;
}

NativeExecutor::~NativeExecutor() {
    stop();
    if (loop_) {
        uv_loop_delete(loop_);
        loop_ = nullptr;
    }
}

bool NativeExecutor::start() {
    if (running_) {
        return true;
    }

    stop_requested_ = false;
    running_ = true;
    thread_ = std::thread(&NativeExecutor::loopThread, this);
    return true;
}

void NativeExecutor::stop() {
    if (!running_) {
        return;
    }

    stop_requested_ = true;
    uv_async_send(&async_handle_);

    if (thread_.joinable()) {
        thread_.join();
    }

    running_ = false;
}

void NativeExecutor::executeAsync(std::function<void()> func) {
    if (!func) {
        return;
    }
    if (stop_requested_) {
        return;
    }
    if (!running_) {
        func();
        return;
    }
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        task_queue_.push_back(std::move(func));
    }
    uv_async_send(&async_handle_);
}

void NativeExecutor::addTimer(uint64_t timeout_ms, uint64_t repeat_ms, std::function<void()> callback) {
    if (!running_ || stop_requested_) {
        return;
    }
    executeAsync([this, timeout_ms, repeat_ms, callback = std::move(callback)]() {
        if (stop_requested_) {
            return;
        }
        
        uv_timer_t* timer = new uv_timer_t;
        if (uv_timer_init(loop_, timer) != 0) {
            delete timer;
            return;
        }

        auto data = new TimerData{this, std::move(callback)};
        timer->data = data;

        int result = uv_timer_start(timer, timerCallback, timeout_ms, repeat_ms);
        if (result != 0) {
            delete data;
            delete timer;
            return;
        }

        {
            std::lock_guard<std::mutex> lock(timers_mutex_);
            timers_.push_back(timer);
        }
    });
}

void NativeExecutor::asyncCallback(uv_async_t* handle) {
    auto executor = static_cast<NativeExecutor*>(handle->data);

    if (executor->stop_requested_) {
        executor->closeAllTimersInLoopThread();
        if (!uv_is_closing(reinterpret_cast<uv_handle_t*>(&executor->async_handle_))) {
            uv_close(reinterpret_cast<uv_handle_t*>(&executor->async_handle_), nullptr);
        }
        return;
    }
    
    std::vector<std::function<void()>> current_tasks;
    {
        std::lock_guard<std::mutex> lock(executor->queue_mutex_);
        current_tasks.swap(executor->task_queue_);
    }
    
    for (auto& task : current_tasks) {
        task();
    }
}

void NativeExecutor::timerCallback(uv_timer_t* handle) {
    auto data = static_cast<TimerData*>(handle->data);
    if (data && data->executor && !data->executor->stop_requested_ && data->callback) {
        data->callback();
    }

    if (uv_timer_get_repeat(handle) == 0) {
        if (data && data->executor) {
            std::lock_guard<std::mutex> lock(data->executor->timers_mutex_);
            auto& timers = data->executor->timers_;
            timers.erase(std::remove(timers.begin(), timers.end(), handle), timers.end());
        }
        uv_close(reinterpret_cast<uv_handle_t*>(handle), closeTimerHandle);
    }
}

void NativeExecutor::closeTimerHandle(uv_handle_t* handle) {
    auto d = static_cast<TimerData*>(handle->data);
    delete d;
    delete reinterpret_cast<uv_timer_t*>(handle);
}

void NativeExecutor::closeAllTimersInLoopThread() {
    std::vector<uv_timer_t*> timers_snapshot;
    {
        std::lock_guard<std::mutex> lock(timers_mutex_);
        timers_snapshot = timers_;
        timers_.clear();
    }

    for (auto* timer : timers_snapshot) {
        if (!timer) {
            continue;
        }
        uv_timer_stop(timer);
        if (!uv_is_closing(reinterpret_cast<uv_handle_t*>(timer))) {
            uv_close(reinterpret_cast<uv_handle_t*>(timer), closeTimerHandle);
        }
    }
}

void NativeExecutor::loopThread() {
    uv_run(loop_, UV_RUN_DEFAULT);
    uv_run(loop_, UV_RUN_NOWAIT);
}

} // namespace ai_scheduler
