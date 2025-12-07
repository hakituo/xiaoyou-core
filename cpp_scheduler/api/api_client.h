#ifndef API_CLIENT_H
#define API_CLIENT_H

#include <string>
#include <memory>
#include <functional>
#include <unordered_map>

namespace ai_scheduler::api {

// API客户端配置
enum class RequestMethod {
    GET,
    POST,
    PUT,
    DELETE
};

// API请求配置
struct ClientRequest {
    RequestMethod method;
    std::string endpoint;
    std::string body;
    std::unordered_map<std::string, std::string> headers;
    std::unordered_map<std::string, std::string> query_params;
    
    ClientRequest(RequestMethod m = RequestMethod::GET, const std::string& ep = "")
        : method(m), endpoint(ep) {
        headers["Content-Type"] = "application/json";
    }
};

// API响应
struct ClientResponse {
    int status_code;
    std::string body;
    std::unordered_map<std::string, std::string> headers;
    
    ClientResponse(int code = 0, const std::string& b = "")
        : status_code(code), body(b) {}
    
    bool isSuccess() const {
        return status_code >= 200 && status_code < 300;
    }
};

// API回调函数类型
typedef std::function<void(const ClientResponse&)> APICallback;

// API客户端类 - 用于调用黑盒接口
class APIClient {
public:
    APIClient(const std::string& base_url, const std::string& api_key = "");
    ~APIClient();
    
    // 设置超时时间（毫秒）
    void setTimeout(int timeout_ms);
    
    // 设置API密钥
    void setAPIKey(const std::string& api_key);
    
    // 同步API调用
    ClientResponse sendRequest(const ClientRequest& request);
    
    // 异步API调用
    void sendRequestAsync(const ClientRequest& request, APICallback callback);
    
    // 便捷方法 - LLM生成
    ClientResponse generateLLM(const std::string& prompt, const std::string& model = "", float temperature = 0.7f);
    void generateLLMAsync(const std::string& prompt, APICallback callback, const std::string& model = "", float temperature = 0.7f);
    
    // 便捷方法 - TTS合成
    ClientResponse synthesizeTTS(const std::string& text, const std::string& voice_id = "", float speed = 1.0f);
    void synthesizeTTSAsync(const std::string& text, APICallback callback, const std::string& voice_id = "", float speed = 1.0f);
    
    // 便捷方法 - 图像生成
    ClientResponse generateImage(const std::string& prompt, int width = 512, int height = 512, 
                               bool use_turbo = true, int steps = 4);
    void generateImageAsync(const std::string& prompt, APICallback callback,
                          int width = 512, int height = 512,
                          bool use_turbo = true, int steps = 4);
    
    // 便捷方法 - 获取任务状态
    ClientResponse getTaskStatus(const std::string& task_id);
    
    // 便捷方法 - 获取系统状态
    ClientResponse getSystemStatus();
    
    // 便捷方法 - 获取资源统计
    ClientResponse getResourceStats();
    
    // 便捷方法 - 获取图像任务进度
    ClientResponse getImageProgress(const std::string& task_id);
    
    // 便捷方法 - 取消任务
    ClientResponse cancelTask(const std::string& task_id);
    
    // 获取基础URL
    std::string getBaseURL() const;
    
private:
    // 构建完整URL
    std::string buildURL(const std::string& endpoint);
    
    // 构建请求体
    std::string buildLLMRequestBody(const std::string& prompt, const std::string& model, float temperature);
    std::string buildTTSRequestBody(const std::string& text, const std::string& voice_id, float speed);
    std::string buildImageRequestBody(const std::string& prompt, int width, int height, bool use_turbo, int steps);
    
    // 执行HTTP请求
    ClientResponse executeRequest(const ClientRequest& request);
    
    // 成员变量
    std::string base_url_;
    std::string api_key_;
    int timeout_ms_;
    void* http_client_handle_; // 内部HTTP客户端句柄
};

// 创建默认API客户端实例
std::shared_ptr<APIClient> createDefaultAPIClient(const std::string& base_url = "http://localhost:8080");

// 示例使用方法 - 展示如何集成黑盒接口
class APIClientExample {
public:
    static void runExample();
};

} // namespace ai_scheduler::api

#endif // API_CLIENT_H