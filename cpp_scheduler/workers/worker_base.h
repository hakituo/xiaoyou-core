#ifndef WORKER_BASE_H
#define WORKER_BASE_H

#include <string>
#include <memory>
#include <functional>

namespace ai_scheduler {

// 工作器基类
class WorkerBase {
public:
    using Callback = std::function<void(bool success, const std::string& result)>;
    
    WorkerBase(const std::string& name);
    virtual ~WorkerBase() = default;
    
    // 初始化工作器
    virtual bool initialize() = 0;
    
    // 清理资源
    virtual void cleanup() = 0;
    
    // 执行任务
    virtual void executeTask(const std::string& input, Callback callback) = 0;
    
    // 获取工作器状态
    virtual bool isReady() const = 0;
    
    // 获取工作器名称
    const std::string& getName() const { return name_; }
    
protected:
    std::string name_;
    std::atomic<bool> initialized_;
};

// 工作器工厂类
template <typename T>
class WorkerFactory {
public:
    static std::shared_ptr<T> create() {
        auto worker = std::make_shared<T>();
        if (!worker->initialize()) {
            return nullptr;
        }
        return worker;
    }
};

} // namespace ai_scheduler

#endif // WORKER_BASE_H