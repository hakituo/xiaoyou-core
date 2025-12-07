#include "api_client.h"
#include <iostream>
#include <sstream>
#include <chrono>
#include <thread>
#include <random>

namespace ai_scheduler::api {

APIClient::APIClient(const std::string& base_url, const std::string& api_key)
    : base_url_(base_url),
      api_key_(api_key),
      timeout_ms_(30000),  // 默认30秒超时
      http_client_handle_(nullptr) {
    
    // 移除base_url末尾的斜杠
    if (!base_url_.empty() && base_url_.back() == '/') {
        base_url_.pop_back();
    }
    
    std::cout << "[API Client] Created with base URL: " << base_url_ << std::endl;
    
    // 实际实现中应该初始化HTTP客户端
    // http_client_handle_ = initializeHttpClient();
}

APIClient::~APIClient() {
    // 清理资源
    if (http_client_handle_) {
        // 实际实现中应该释放HTTP客户端资源
        // cleanupHttpClient(http_client_handle_);
        http_client_handle_ = nullptr;
    }
    
    std::cout << "[API Client] Destroyed" << std::endl;
}

void APIClient::setTimeout(int timeout_ms) {
    timeout_ms_ = std::max(1000, timeout_ms); // 最小1秒
    std::cout << "[API Client] Timeout set to: " << timeout_ms_ << "ms" << std::endl;
}

void APIClient::setAPIKey(const std::string& api_key) {
    api_key_ = api_key;
    std::cout << "[API Client] API key set" << std::endl;
}

ClientResponse APIClient::sendRequest(const ClientRequest& request) {
    std::cout << "[API Client] Sending request to: " << request.endpoint << std::endl;
    return executeRequest(request);
}

void APIClient::sendRequestAsync(const ClientRequest& request, APICallback callback) {
    std::cout << "[API Client] Sending async request to: " << request.endpoint << std::endl;
    
    // 实际实现中应该在单独的线程中执行请求
    std::thread([this, request, callback]() {
        try {
            ClientResponse response = executeRequest(request);
            callback(response);
        } catch (const std::exception& e) {
            std::cerr << "[API Client] Async request error: " << e.what() << std::endl;
            ClientResponse error_response(500, "Internal error: " + std::string(e.what()));
            callback(error_response);
        }
    }).detach();
}

ClientResponse APIClient::generateLLM(const std::string& prompt) {
    ClientRequest request(RequestMethod::POST, "/api/v1/llm/generate");
    request.body = buildLLMRequestBody(prompt);
    return sendRequest(request);
}

void APIClient::generateLLMAsync(const std::string& prompt, APICallback callback) {
    ClientRequest request(RequestMethod::POST, "/api/v1/llm/generate");
    request.body = buildLLMRequestBody(prompt);
    sendRequestAsync(request, callback);
}

ClientResponse APIClient::synthesizeTTS(const std::string& text, const std::string& voice_id) {
    ClientRequest request(RequestMethod::POST, "/api/v1/tts/synthesize");
    request.body = buildTTSRequestBody(text, voice_id);
    return sendRequest(request);
}

void APIClient::synthesizeTTSAsync(const std::string& text, APICallback callback, const std::string& voice_id) {
    ClientRequest request(RequestMethod::POST, "/api/v1/tts/synthesize");
    request.body = buildTTSRequestBody(text, voice_id);
    sendRequestAsync(request, callback);
}

ClientResponse APIClient::generateImage(const std::string& prompt, int width, int height) {
    ClientRequest request(RequestMethod::POST, "/api/v1/image/generate");
    request.body = buildImageRequestBody(prompt, width, height);
    return sendRequest(request);
}

void APIClient::generateImageAsync(const std::string& prompt, APICallback callback, int width, int height) {
    ClientRequest request(RequestMethod::POST, "/api/v1/image/generate");
    request.body = buildImageRequestBody(prompt, width, height);
    sendRequestAsync(request, callback);
}

ClientResponse APIClient::getStatus() {
    ClientRequest request(RequestMethod::GET, "/api/v1/status");
    return sendRequest(request);
}

ClientResponse APIClient::cancelTask(uint64_t task_id) {
    ClientRequest request(RequestMethod::DELETE, "/api/v1/tasks/" + std::to_string(task_id));
    return sendRequest(request);
}

std::string APIClient::getBaseURL() const {
    return base_url_;
}

std::string APIClient::buildURL(const std::string& endpoint) {
    std::string url = base_url_;
    
    // 确保endpoint以/开头
    if (!endpoint.empty() && endpoint.front() != '/') {
        url += '/';
    }
    
    url += endpoint;
    return url;
}

std::string APIClient::buildLLMRequestBody(const std::string& prompt) {
    std::stringstream ss;
    ss << "{\"prompt\":\"" << prompt << "\",\"temperature\":0.7,\"max_tokens\":2048}";
    return ss.str();
}

std::string APIClient::buildTTSRequestBody(const std::string& text, const std::string& voice_id) {
    std::stringstream ss;
    ss << "{\"text\":\"" << text << "\"";
    if (!voice_id.empty()) {
        ss << ",\"voice_id\":\"" << voice_id << "\"";
    }
    ss << ",\"speed\":1.0,\"pitch\":1.0,\"volume\":1.0,\"format\":\"wav\"}";
    return ss.str();
}

std::string APIClient::buildImageRequestBody(const std::string& prompt, int width, int height) {
    std::stringstream ss;
    ss << "{\"prompt\":\"" << prompt << "\",\"width\":" << width << ",\"height\":" << height 
       << ",\"steps\":20,\"guidance_scale\":7.5}";
    return ss.str();
}

ClientResponse APIClient::executeRequest(const ClientRequest& request) {
    // 模拟HTTP请求执行
    std::cout << "[API Client] Executing request: " << static_cast<int>(request.method) << " " << request.endpoint << std::endl;
    
    // 构建完整URL
    std::string full_url = buildURL(request.endpoint);
    std::cout << "[API Client] Full URL: " << full_url << std::endl;
    
    // 模拟不同端点的响应
    ClientResponse response;
    
    try {
        // 根据端点生成模拟响应
        if (request.endpoint == "/health") {
            response.status_code = 200;
            response.body = "{\"status\":\"ok\"}";
        } else if (request.endpoint == "/api/v1/llm/generate") {
            // 模拟LLM响应
            std::this_thread::sleep_for(std::chrono::milliseconds(500)); // 模拟延迟
            response.status_code = 200;
            response.body = "{\"success\":true,\"task_id\":12345,\"status\":\"processing\"}";
        } else if (request.endpoint == "/api/v1/tts/synthesize") {
            // 模拟TTS响应
            std::this_thread::sleep_for(std::chrono::milliseconds(300)); // 模拟延迟
            response.status_code = 200;
            response.body = "{\"success\":true,\"task_id\":54321,\"status\":\"processing\"}";
        } else if (request.endpoint == "/api/v1/image/generate") {
            // 模拟图像生成响应
            std::this_thread::sleep_for(std::chrono::milliseconds(200)); // 模拟延迟
            response.status_code = 200;
            response.body = "{\"success\":true,\"task_id\":98765,\"status\":\"queued\"}";
        } else if (request.endpoint == "/api/v1/status") {
            // 模拟状态响应
            response.status_code = 200;
            response.body = "{\"status\":\"running\",\"version\":\"1.0.0\"}";
        } else {
            // 未知端点
            response.status_code = 404;
            response.body = "{\"error\":\"Endpoint not found\"}";
        }
        
        // 设置响应头
        response.headers["Content-Type"] = "application/json";
        response.headers["Server"] = "AI Scheduler API";
        
        std::cout << "[API Client] Request completed with status: " << response.status_code << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "[API Client] Request failed: " << e.what() << std::endl;
        response.status_code = 500;
        response.body = "{\"error\":\"Internal error\"}";
    }
    
    return response;
}

std::shared_ptr<APIClient> createDefaultAPIClient(const std::string& base_url) {
    auto client = std::make_shared<APIClient>(base_url);
    return client;
}

// 示例使用方法
void APIClientExample::runExample() {
    std::cout << "\n=== API Client Example ===" << std::endl;
    
    // 创建客户端
    auto client = createDefaultAPIClient("http://localhost:8080");
    client->setTimeout(60000); // 设置60秒超时
    
    // 1. 健康检查
    std::cout << "\n1. Health Check:" << std::endl;
    ClientRequest health_request(RequestMethod::GET, "/health");
    ClientResponse health_response = client->sendRequest(health_request);
    std::cout << "Status: " << health_response.status_code << std::endl;
    std::cout << "Body: " << health_response.body << std::endl;
    
    // 2. LLM生成示例
    std::cout << "\n2. LLM Generation (Async):" << std::endl;
    client->generateLLMAsync("写一个简短的AI助手介绍", [](const ClientResponse& response) {
        std::cout << "LLM Async Response - Status: " << response.status_code << std::endl;
        std::cout << "Body: " << response.body << std::endl;
    });
    
    // 3. TTS合成示例
    std::cout << "\n3. TTS Synthesis (Sync):" << std::endl;
    ClientResponse tts_response = client->synthesizeTTS("你好，这是一段测试语音。");
    std::cout << "Status: " << tts_response.status_code << std::endl;
    std::cout << "Body: " << tts_response.body << std::endl;
    
    // 4. 图像生成示例
    std::cout << "\n4. Image Generation (Async):" << std::endl;
    client->generateImageAsync("一只可爱的小猫", [](const ClientResponse& response) {
        std::cout << "Image Async Response - Status: " << response.status_code << std::endl;
        std::cout << "Body: " << response.body << std::endl;
    });
    
    // 5. 获取状态
    std::cout << "\n5. Get Status:" << std::endl;
    ClientResponse status_response = client->getStatus();
    std::cout << "Status: " << status_response.status_code << std::endl;
    std::cout << "Body: " << status_response.body << std::endl;
    
    // 等待异步操作完成
    std::cout << "\nWaiting for async operations to complete..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(2));
    
    std::cout << "\n=== Example Completed ===" << std::endl;
}

} // namespace ai_scheduler::api