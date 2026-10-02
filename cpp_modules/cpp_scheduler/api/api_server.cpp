#include "api_server.h"
#include "../core/resource_isolation_scheduler.h"
#include "../workers/cpu_tts_worker.h"
#include "../workers/gpu_llm_worker.h"
#include <iostream>
#include <sstream>
#include <chrono>
#include <regex>

// Helper macro for logging to avoid direct std::cout usage in high-perf code
#define LOG_INFO(msg) do { std::cout << "[INFO] " << msg << std::endl; } while(0)
#define LOG_ERROR(msg) do { std::cerr << "[ERROR] " << msg << std::endl; } while(0)

namespace ai_scheduler::api {

APIServer::APIServer(int port)
    : port_(port),
      running_(false),
      server_handle_(nullptr),
      enable_auth_(false) {
    LOG_INFO("[API Server] Creating API server on port: " << port);
    registerRoutes();
}

APIServer::~APIServer() {
    stop();
    LOG_INFO("[API Server] Destroyed");
}

void APIServer::setScheduler(std::shared_ptr<ResourceIsolationScheduler> scheduler) {
    scheduler_ = scheduler;
    LOG_INFO("[API Server] Scheduler set");
}

void APIServer::setTTSWorker(std::shared_ptr<CPUTTSWorker> tts_worker) {
    tts_worker_ = tts_worker;
    LOG_INFO("[API Server] TTS worker set");
}

void APIServer::setLLMWorker(std::shared_ptr<GPULLMWorker> llm_worker) {
    llm_worker_ = llm_worker;
    LOG_INFO("[API Server] LLM worker set");
}

bool APIServer::start() {
    if (running_) {
        LOG_ERROR("[API Server] Server already running");
        return false;
    }
    
    // 验证必要的组件是否设置
    if (!scheduler_) {
        LOG_ERROR("[API Server] Error: Scheduler not set");
        return false;
    }
    
    running_ = true;
    server_thread_ = std::thread(&APIServer::serverThread, this);
    
    LOG_INFO("[API Server] Started on port " << port_);
    return true;
}

void APIServer::stop() {
    if (running_) {
        running_ = false;
        
        // 这里应该关闭libuv服务器
        if (server_handle_) {
            // 实际实现中应该释放服务器资源
            server_handle_ = nullptr;
        }
        
        if (server_thread_.joinable()) {
            server_thread_.join();
        }
        
        LOG_INFO("[API Server] Stopped");
    }
}

bool APIServer::isRunning() const {
    return running_;
}

int APIServer::getPort() const {
    return port_;
}

void APIServer::registerRoutes() {
    // 健康检查
    routes_["GET /health"] = std::bind(&APIServer::handleHealth, this, std::placeholders::_1);
    
    // LLM相关API
    routes_["POST /api/v1/llm/generate"] = std::bind(&APIServer::handleLLMRequest, this, std::placeholders::_1);
    
    // TTS相关API
    routes_["POST /api/v1/tts/synthesize"] = std::bind(&APIServer::handleTTSRequest, this, std::placeholders::_1);
    
    // 图像生成相关API
    routes_["POST /api/v1/image/generate"] = std::bind(&APIServer::handleImageRequest, this, std::placeholders::_1);
    
    // 状态查询API
    routes_["GET /api/v1/status"] = std::bind(&APIServer::handleStatusRequest, this, std::placeholders::_1);
    
    // 任务取消API
    routes_["DELETE /api/v1/tasks/:id"] = std::bind(&APIServer::handleCancelTask, this, std::placeholders::_1);
    
    // 任务查询API
    routes_["GET /api/v1/tasks/:id"] = std::bind(&APIServer::handleGetTask, this, std::placeholders::_1);
    
    std::cout << "[API Server] Routes registered: " << routes_.size() << std::endl;
}

void APIServer::serverThread() {
    std::cout << "[API Server] Server thread started" << std::endl;
    
    // 模拟服务器运行
    // 实际实现中，这里应该使用libuv或其他库来实现HTTP服务器
    while (running_) {
        // 模拟服务器处理循环
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    
    std::cout << "[API Server] Server thread stopped" << std::endl;
}

APIResponse APIServer::handleHealth(const APIRequest& request) {
    LOG_INFO("[API Server] Health check request received");

    bool scheduler_ready = (scheduler_ != nullptr && scheduler_->isRunning());
    bool tts_ready = (tts_worker_ != nullptr);
    bool llm_ready = (llm_worker_ != nullptr);
    // 注：image worker 已迁移至 Python 侧实现，C++ 端不再持有图像生成 worker

    // Contract: align to Python side health semantics (healthy/degraded).
    // "healthy" means core scheduler loop is running AND key workers exist.
    bool all_ready = scheduler_ready && tts_ready && llm_ready;

    std::stringstream ss;
    ss << "{"
       << "\"status\": \"" << (all_ready ? "healthy" : "degraded") << "\","
       << "\"components\": {"
       << "\"scheduler\": \"" << (scheduler_ready ? "healthy" : "unhealthy") << "\","
       << "\"tts\": \"" << (tts_ready ? "healthy" : "unhealthy") << "\","
       << "\"llm\": \"" << (llm_ready ? "healthy" : "unhealthy") << "\""
       << "}"
       << "}";

    return APIResponse(APIStatus::SUCCESS, ss.str());
}

APIResponse APIServer::handleLLMRequest(const APIRequest& request) {
    std::cout << "[API Server] LLM request received" << std::endl;
    
    if (!scheduler_ || !llm_worker_) {
        return createErrorResponse(APIStatus::SERVICE_UNAVAILABLE, "LLM service not available");
    }
    
    // 模拟解析JSON请求体
    std::string prompt = "";
    
    // 模拟从请求体中提取prompt
    size_t prompt_pos = request.body.find("\"prompt\":\"");
    if (prompt_pos != std::string::npos) {
        size_t start = prompt_pos + 10;
        size_t end = request.body.find("\"", start);
        if (end != std::string::npos) {
            prompt = request.body.substr(start, end - start);
        }
    }
    
    if (prompt.empty()) {
        return createErrorResponse(APIStatus::BAD_REQUEST, "Missing required field: prompt");
    }
    
    // 提交LLM任务
    LLMInferenceRequest llmReq;
    llmReq.prompt = prompt;
    // 默认参数
    llmReq.maxTokens = 100;
    llmReq.temperature = 0.7f;
    
    auto task = std::make_shared<LLMTask>(llmReq, llm_worker_.get());
    scheduler_->submitTask(task);
    std::string task_id = task->getTaskId();
    
    // 同步响应（对于演示）
    std::stringstream ss;
    ss << "{" 
       << "\"success\": true," 
       << "\"task_id\": \"" << task_id << "\"," 
       << "\"status\": \"pending\"," 
       << "\"message\": \"LLM request submitted successfully\"" 
       << "}";
    
    return APIResponse(APIStatus::SUCCESS, ss.str());
}

APIResponse APIServer::handleTTSRequest(const APIRequest& request) {
    std::cout << "[API Server] TTS request received" << std::endl;
    
    if (!scheduler_ || !tts_worker_) {
        return createErrorResponse(APIStatus::SERVICE_UNAVAILABLE, "TTS service not available");
    }
    
    // 模拟解析TTS参数
    std::string text = "";
    
    // 简化实现
    size_t text_pos = request.body.find("\"text\":\"");
    if (text_pos != std::string::npos) {
        size_t start = text_pos + 8;
        size_t end = request.body.find("\"", start);
        if (end != std::string::npos) {
            text = request.body.substr(start, end - start);
        }
    }
    
    if (text.empty()) {
        return createErrorResponse(APIStatus::BAD_REQUEST, "Missing required field: text");
    }
    
    // 提交TTS任务
    TTSParams params;
    params.text = text;
    // 默认参数
    params.voice_id = "zh_cn";
    
    auto task = std::make_shared<TTSTask>(
        "tts_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count()),
        TaskPriority::MEDIUM,
        params
    );
    scheduler_->submitTask(task);
    std::string task_id = task->getTaskId();
    
    std::stringstream ss;
    ss << "{" 
       << "\"success\": true," 
       << "\"task_id\": \"" << task_id << "\"," 
       << "\"status\": \"pending\"," 
       << "\"message\": \"TTS request submitted successfully\"" 
       << "}";
    
    return APIResponse(APIStatus::SUCCESS, ss.str());
}

APIResponse APIServer::handleImageRequest(const APIRequest& request) {
    std::cout << "[API Server] Image generation request received" << std::endl;

    // 注：图像生成已迁移至 Python 侧实现，C++ API Server 不再直接处理图像生成任务。
    // 保留路由以维持 API 兼容性，但返回 SERVICE_UNAVAILABLE 提示调用方走 Python 侧。
    return createErrorResponse(
        APIStatus::SERVICE_UNAVAILABLE,
        "Image generation is handled by the Python side; C++ API no longer serves this endpoint."
    );
}

APIResponse APIServer::handleStatusRequest(const APIRequest& request) {
    LOG_INFO("[API Server] Status request received");
    
    std::stringstream ss;
    ss << "{" 
       << "\"version\": \"1.0.0\"," 
       << "\"status\": \"running\"," 
       << "\"uptime\": 0," 
       << "\"resources\": {" 
       << "\"cpu_usage\": " << (tts_worker_ ? tts_worker_->getCPUUtilization() : 0.0f) << "," 
       << "\"gpu_usage\": 0.0," 
       << "\"memory_usage\": 0.0" 
       << "}," 
       << "\"queue_stats\": {" 
       << "\"total_tasks\": 0," 
       << "\"pending_tasks\": 0," 
       << "\"completed_tasks\": 0" 
       << "}" 
       << "}";
    
    return APIResponse(APIStatus::SUCCESS, ss.str());
}

APIResponse APIServer::handleCancelTask(const APIRequest& request) {
    LOG_INFO("[API Server] Cancel task request received");
    
    if (!scheduler_) {
        return createErrorResponse(APIStatus::SERVICE_UNAVAILABLE, "Scheduler not available");
    }
    
    // 提取任务ID
    std::string task_id_str = "";
    size_t id_pos = request.path.find_last_of('/');
    if (id_pos != std::string::npos) {
        task_id_str = request.path.substr(id_pos + 1);
    }
    
    try {
        bool success = scheduler_->cancelTask(task_id_str);
        
        std::stringstream ss;
        ss << "{" 
           << "\"success\": " << (success ? "true" : "false") << "," 
           << "\"message\": \"Task " << (success ? "cancelled successfully" : "not found or already completed") << "\"" 
           << "}";
        
        return APIResponse(APIStatus::SUCCESS, ss.str());
    } catch (...) {
        return createErrorResponse(APIStatus::BAD_REQUEST, "Invalid task ID");
    }
}

APIResponse APIServer::handleGetTask(const APIRequest& request) {
    LOG_INFO("[API Server] Get task status request received");
    
    if (!scheduler_) {
        return createErrorResponse(APIStatus::SERVICE_UNAVAILABLE, "Scheduler not available");
    }
    
    // 提取任务ID
    std::string task_id_str = "";
    size_t id_pos = request.path.find_last_of('/');
    if (id_pos != std::string::npos) {
        task_id_str = request.path.substr(id_pos + 1);
    }
    
    if (task_id_str.empty()) {
        return createErrorResponse(APIStatus::BAD_REQUEST, "Missing task ID");
    }
    
    auto task = scheduler_->getTask(task_id_str);
    if (!task) {
        return createErrorResponse(APIStatus::NOT_FOUND, "Task not found");
    }
    
    std::stringstream ss;
    ss << "{" 
       << "\"task_id\": \"" << task_id_str << "\"," 
       << "\"status\": \"" << (task->getStatus() == TaskStatus::COMPLETED ? "completed" : 
                              task->getStatus() == TaskStatus::FAILED ? "failed" :
                              task->getStatus() == TaskStatus::RUNNING ? "running" :
                              task->getStatus() == TaskStatus::PENDING ? "pending" :
                              task->getStatus() == TaskStatus::CANCELLED ? "cancelled" : "unknown") << "\"";
    
    // 如果任务完成，包含结果
    if (task->getStatus() == TaskStatus::COMPLETED) {
        ss << ",\"result\": " << task->getResult(); // Assuming getResult returns a JSON string or string representation
    }
    
    ss << "}";
    
    return APIResponse(APIStatus::SUCCESS, ss.str());
}

APIResponse APIServer::createErrorResponse(APIStatus status, const std::string& message) {
    std::stringstream ss;
    ss << "{" 
       << "\"success\": false," 
       << "\"error\": {" 
       << "\"code\": " << static_cast<int>(status) << "," 
       << "\"message\": \"" << message << "\"" 
       << "}" 
       << "}";
    
    return APIResponse(status, ss.str());
}

std::string APIServer::buildJSONResponse(bool success, const std::string& message, const void* data) {
    std::stringstream ss;
    ss << "{" 
       << "\"success\": " << (success ? "true" : "false") << "," 
       << "\"message\": \"" << message << "\"" 
       << "}";
    
    return ss.str();
}

std::string toJSON(const APIResponse& response) {
    // 简化实现，返回响应体
    return response.body;
}

bool parseJSON(const std::string& json, std::unordered_map<std::string, std::string>& result) {
    // 简化的JSON解析实现
    // 实际应用中应该使用专业的JSON库
    try {
        // 这里只是一个简化的示例
        std::regex keyValue("\"([^\"]+)\"\\s*:\\s*\"([^\"]+)\"");
        std::smatch match;
        std::string::const_iterator searchStart(json.cbegin());
        
        while (std::regex_search(searchStart, json.cend(), match, keyValue)) {
            result[match[1]] = match[2];
            searchStart = match.suffix().first;
        }
        
        return !result.empty();
    } catch (...) {
        return false;
    }
}

std::shared_ptr<APIServer> createDefaultAPIServer(int port) {
    auto server = std::make_shared<APIServer>(port);
    return server;
}

} // namespace ai_scheduler::api
