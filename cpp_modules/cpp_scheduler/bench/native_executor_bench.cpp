#include "core/native_executor.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

using namespace ai_scheduler;

static void summarizeIntervalsUs(const std::vector<int64_t>& v) {
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
}

int main() {
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
        summarizeIntervalsUs(v);
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
        summarizeIntervalsUs(v);
    }

    return 0;
}
