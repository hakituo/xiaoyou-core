#include "system_config.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <algorithm>
#include <nlohmann/json.hpp> // 假设使用nlohmann/json库处理JSON

namespace ai_scheduler::config {

// 静态单例实例
std::shared_ptr<SystemConfig> SystemConfig::instance_ = nullptr;
std::mutex SystemConfig::instance_mutex_;

// ConfigValue 实现
ConfigValue::ConfigValue(const std::string& value) 
    : type_(Type::STRING), string_value_(value), int_value_(0), double_value_(0.0), bool_value_(false) {
}

ConfigValue::ConfigValue(int64_t value) 
    : type_(Type::INTEGER), string_value_(), int_value_(value), double_value_(static_cast<double>(value)), bool_value_(value != 0) {
}

ConfigValue::ConfigValue(double value) 
    : type_(Type::DOUBLE), string_value_(), int_value_(static_cast<int64_t>(value)), double_value_(value), bool_value_(value != 0.0) {
}

ConfigValue::ConfigValue(bool value) 
    : type_(Type::BOOLEAN), string_value_(value ? "true" : "false"), int_value_(value ? 1 : 0), double_value_(value ? 1.0 : 0.0), bool_value_(value) {
}

ConfigValue::ConfigValue() 
    : type_(Type::NONE), string_value_(), int_value_(0), double_value_(0.0), bool_value_(false) {
}

std::string ConfigValue::asString() const {
    switch (type_) {
        case Type::STRING:
            return string_value_;
        case Type::INTEGER:
            return std::to_string(int_value_);
        case Type::DOUBLE:
            return std::to_string(double_value_);
        case Type::BOOLEAN:
            return bool_value_ ? "true" : "false";
        default:
            return "";
    }
}

int64_t ConfigValue::asInt() const {
    switch (type_) {
        case Type::STRING:
            try {
                return std::stoll(string_value_);
            } catch (...) {
                return 0;
            }
        case Type::INTEGER:
            return int_value_;
        case Type::DOUBLE:
            return static_cast<int64_t>(double_value_);
        case Type::BOOLEAN:
            return bool_value_ ? 1 : 0;
        default:
            return 0;
    }
}

double ConfigValue::asDouble() const {
    switch (type_) {
        case Type::STRING:
            try {
                return std::stod(string_value_);
            } catch (...) {
                return 0.0;
            }
        case Type::INTEGER:
            return static_cast<double>(int_value_);
        case Type::DOUBLE:
            return double_value_;
        case Type::BOOLEAN:
            return bool_value_ ? 1.0 : 0.0;
        default:
            return 0.0;
    }
}

bool ConfigValue::asBool() const {
    switch (type_) {
        case Type::STRING: {
            std::string lower = string_value_;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            return (lower == "true" || lower == "1" || lower == "yes" || lower == "y");
        }
        case Type::INTEGER:
            return int_value_ != 0;
        case Type::DOUBLE:
            return double_value_ != 0.0;
        case Type::BOOLEAN:
            return bool_value_;
        default:
            return false;
    }
}

bool ConfigValue::isValid() const {
    return type_ != Type::NONE;
}

bool ConfigValue::operator==(const ConfigValue& other) const {
    if (type_ != other.type_) {
        return false;
    }
    
    switch (type_) {
        case Type::STRING:
            return string_value_ == other.string_value_;
        case Type::INTEGER:
            return int_value_ == other.int_value_;
        case Type::DOUBLE:
            return double_value_ == other.double_value_;
        case Type::BOOLEAN:
            return bool_value_ == other.bool_value_;
        default:
            return true; // NONE == NONE
    }
}

bool ConfigValue::operator!=(const ConfigValue& other) const {
    return !(*this == other);
}

// SystemConfig 实现
std::shared_ptr<SystemConfig> SystemConfig::getInstance() {
    std::lock_guard<std::mutex> lock(instance_mutex_);
    if (!instance_) {
        instance_ = std::shared_ptr<SystemConfig>(new SystemConfig());
    }
    return instance_;
}

SystemConfig::SystemConfig() : initialized_(false) {
    initializeDefaults();
}

SystemConfig::~SystemConfig() {
    // 清理资源
}

bool SystemConfig::initialize(const std::string& config_file) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    if (initialized_) {
        return true; // 已经初始化
    }
    
    // 初始化默认配置
    initializeDefaults();
    
    // 如果提供了配置文件，尝试加载
    if (!config_file.empty()) {
        if (!loadFromFile(config_file)) {
            std::cerr << "Failed to load config file: " << config_file << std::endl;
            // 继续使用默认配置
        }
    }
    
    // 验证配置
    if (!validate()) {
        std::cerr << "Configuration validation failed" << std::endl;
        return false;
    }
    
    initialized_ = true;
    return true;
}

bool SystemConfig::loadFromFile(const std::string& config_file) {
    try {
        std::ifstream file(config_file);
        if (!file.is_open()) {
            return false;
        }
        
        std::stringstream buffer;
        buffer << file.rdbuf();
        file.close();
        
        return loadFromJson(buffer.str());
    }
    catch (const std::exception& e) {
        std::cerr << "Error loading config from file: " << e.what() << std::endl;
        return false;
    }
}

bool SystemConfig::loadFromJson(const std::string& json_string) {
    try {
        std::lock_guard<std::mutex> lock(config_mutex_);
        
        nlohmann::json config_json = nlohmann::json::parse(json_string);
        
        // 加载工作器配置
        if (config_json.contains("workers")) {
            const auto& workers_json = config_json["workers"];
            
            // GPU LLM工作器配置
            if (workers_json.contains("gpu_llm")) {
                const auto& llm_json = workers_json["gpu_llm"];
                loadWorkerConfigFromJson(WorkerType::GPU_LLM, llm_json);
            }
            
            // CPU TTS工作器配置
            if (workers_json.contains("cpu_tts")) {
                const auto& tts_json = workers_json["cpu_tts"];
                loadWorkerConfigFromJson(WorkerType::CPU_TTS, tts_json);
            }
            
            // GPU图像工作器配置
            if (workers_json.contains("gpu_image")) {
                const auto& image_json = workers_json["gpu_image"];
                loadWorkerConfigFromJson(WorkerType::GPU_IMAGE, image_json);
            }
        }
        
        // 加载API服务器配置
        if (config_json.contains("api_server")) {
            const auto& api_json = config_json["api_server"];
            loadAPIServerConfigFromJson(api_json);
        }
        
        // 加载监控配置
        if (config_json.contains("monitoring")) {
            const auto& monitoring_json = config_json["monitoring"];
            loadMonitoringConfigFromJson(monitoring_json);
        }
        
        // 加载优化配置
        if (config_json.contains("optimization")) {
            const auto& optimization_json = config_json["optimization"];
            loadOptimizationConfigFromJson(optimization_json);
        }
        
        // 加载全局配置
        if (config_json.contains("global")) {
            const auto& global_json = config_json["global"];
            for (auto& [key, value] : global_json.items()) {
                ConfigValue config_value;
                if (value.is_string()) {
                    config_value = ConfigValue(value.get<std::string>());
                } else if (value.is_number_integer()) {
                    config_value = ConfigValue(value.get<int64_t>());
                } else if (value.is_number_float()) {
                    config_value = ConfigValue(value.get<double>());
                } else if (value.is_boolean()) {
                    config_value = ConfigValue(value.get<bool>());
                }
                
                if (config_value.isValid()) {
                    global_configs_[key] = config_value;
                    notifyConfigChanged(key, config_value);
                }
            }
        }
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Error parsing config JSON: " << e.what() << std::endl;
        return false;
    }
}

bool SystemConfig::saveToFile(const std::string& config_file) const {
    try {
        std::lock_guard<std::mutex> lock(config_mutex_);
        
        std::ofstream file(config_file);
        if (!file.is_open()) {
            return false;
        }
        
        file << exportToJson();
        file.close();
        
        return true;
    }
    catch (const std::exception& e) {
        std::cerr << "Error saving config to file: " << e.what() << std::endl;
        return false;
    }
}

std::string SystemConfig::exportToJson() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    nlohmann::json config_json;
    
    // 导出工作器配置
    nlohmann::json workers_json;
    
    // GPU LLM工作器配置
    workers_json["gpu_llm"] = exportWorkerConfigToJson(WorkerType::GPU_LLM);
    
    // CPU TTS工作器配置
    workers_json["cpu_tts"] = exportWorkerConfigToJson(WorkerType::CPU_TTS);
    
    // GPU图像工作器配置
    workers_json["gpu_image"] = exportWorkerConfigToJson(WorkerType::GPU_IMAGE);
    
    config_json["workers"] = workers_json;
    
    // 导出API服务器配置
    config_json["api_server"] = exportAPIServerConfigToJson();
    
    // 导出监控配置
    config_json["monitoring"] = exportMonitoringConfigToJson();
    
    // 导出优化配置
    config_json["optimization"] = exportOptimizationConfigToJson();
    
    // 导出全局配置
    nlohmann::json global_json;
    for (const auto& [key, value] : global_configs_) {
        if (value.isValid()) {
            switch (value.asInt()) { // 简单判断类型，实际应该有更好的方法
                case 0:
                case 1:
                    if (value.asString() == "true" || value.asString() == "false") {
                        global_json[key] = value.asBool();
                    } else {
                        global_json[key] = value.asInt();
                    }
                    break;
                default:
                    if (value.asString().find('.') != std::string::npos) {
                        global_json[key] = value.asDouble();
                    } else {
                        global_json[key] = value.asInt();
                    }
                    break;
            }
        }
    }
    config_json["global"] = global_json;
    
    return config_json.dump(2); // 美化输出，缩进2个空格
}

void SystemConfig::setWorkerConfig(WorkerType worker_type, WorkerConfigKey key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    worker_configs_[worker_type][key] = value;
    
    // 通知配置更改
    std::string config_key = getWorkerConfigKeyString(worker_type) + "." + getWorkerConfigKeyString(key);
    notifyConfigChanged(config_key, value);
}

ConfigValue SystemConfig::getWorkerConfig(WorkerType worker_type, WorkerConfigKey key, const ConfigValue& default_value) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    auto worker_it = worker_configs_.find(worker_type);
    if (worker_it != worker_configs_.end()) {
        auto key_it = worker_it->second.find(key);
        if (key_it != worker_it->second.end() && key_it->second.isValid()) {
            return key_it->second;
        }
    }
    
    return default_value;
}

void SystemConfig::setAPIServerConfig(APIServerConfigKey key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    api_server_configs_[key] = value;
    
    // 通知配置更改
    std::string config_key = "api_server." + getAPIServerConfigKeyString(key);
    notifyConfigChanged(config_key, value);
}

ConfigValue SystemConfig::getAPIServerConfig(APIServerConfigKey key, const ConfigValue& default_value) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    auto it = api_server_configs_.find(key);
    if (it != api_server_configs_.end() && it->second.isValid()) {
        return it->second;
    }
    
    return default_value;
}

void SystemConfig::setMonitoringConfig(MonitoringConfigKey key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    monitoring_configs_[key] = value;
    
    // 通知配置更改
    std::string config_key = "monitoring." + getMonitoringConfigKeyString(key);
    notifyConfigChanged(config_key, value);
}

ConfigValue SystemConfig::getMonitoringConfig(MonitoringConfigKey key, const ConfigValue& default_value) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    auto it = monitoring_configs_.find(key);
    if (it != monitoring_configs_.end() && it->second.isValid()) {
        return it->second;
    }
    
    return default_value;
}

void SystemConfig::setOptimizationConfig(OptimizationConfigKey key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    optimization_configs_[key] = value;
    
    // 通知配置更改
    std::string config_key = "optimization." + getOptimizationConfigKeyString(key);
    notifyConfigChanged(config_key, value);
}

ConfigValue SystemConfig::getOptimizationConfig(OptimizationConfigKey key, const ConfigValue& default_value) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    auto it = optimization_configs_.find(key);
    if (it != optimization_configs_.end() && it->second.isValid()) {
        return it->second;
    }
    
    return default_value;
}

void SystemConfig::setGlobalConfig(const std::string& key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(config_mutex_);
    global_configs_[key] = value;
    notifyConfigChanged(key, value);
}

ConfigValue SystemConfig::getGlobalConfig(const std::string& key, const ConfigValue& default_value) const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    auto it = global_configs_.find(key);
    if (it != global_configs_.end() && it->second.isValid()) {
        return it->second;
    }
    
    return default_value;
}

void SystemConfig::resetToDefaults() {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    // 清空现有配置
    worker_configs_.clear();
    api_server_configs_.clear();
    monitoring_configs_.clear();
    optimization_configs_.clear();
    global_configs_.clear();
    
    // 重新初始化默认配置
    initializeDefaults();
    
    initialized_ = false;
}

bool SystemConfig::validate() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    
    // 验证必要的配置项
    
    // 验证API服务器配置
    if (getAPIServerConfig(APIServerConfigKey::ENABLED).asBool()) {
        int port = getAPIServerConfig(APIServerConfigKey::PORT, ConfigValue(8080)).asInt();
        if (port < 1 || port > 65535) {
            std::cerr << "Invalid API server port: " << port << std::endl;
            return false;
        }
    }
    
    // 验证工作器配置
    for (auto worker_type : {WorkerType::GPU_LLM, WorkerType::CPU_TTS, WorkerType::GPU_IMAGE}) {
        if (getWorkerConfig(worker_type, WorkerConfigKey::ENABLED).asBool()) {
            int min_threads = getWorkerConfig(worker_type, WorkerConfigKey::MIN_THREADS).asInt();
            int max_threads = getWorkerConfig(worker_type, WorkerConfigKey::MAX_THREADS).asInt();
            
            if (min_threads < 1 || max_threads < min_threads) {
                std::cerr << "Invalid thread configuration for worker type: " << static_cast<int>(worker_type) << std::endl;
                return false;
            }
            
            // 对于GPU工作器，验证GPU ID
            if (worker_type == WorkerType::GPU_LLM || worker_type == WorkerType::GPU_IMAGE) {
                int gpu_id = getWorkerConfig(worker_type, WorkerConfigKey::GPU_ID, ConfigValue(0)).asInt();
                if (gpu_id < 0) {
                    std::cerr << "Invalid GPU ID for worker type: " << static_cast<int>(worker_type) << std::endl;
                    return false;
                }
            }
        }
    }
    
    // 验证监控配置
    if (getMonitoringConfig(MonitoringConfigKey::ENABLED).asBool()) {
        int interval = getMonitoringConfig(MonitoringConfigKey::COLLECTION_INTERVAL_MS, ConfigValue(1000)).asInt();
        if (interval < 100) { // 最小间隔100ms
            std::cerr << "Monitoring collection interval too small: " << interval << "ms" << std::endl;
            return false;
        }
    }
    
    return true;
}

bool SystemConfig::isInitialized() const {
    return initialized_;
}

std::vector<std::string> SystemConfig::getAllConfigKeys() const {
    std::lock_guard<std::mutex> lock(config_mutex_);
    std::vector<std::string> keys;
    
    // 获取工作器配置键
    for (auto worker_type : {WorkerType::GPU_LLM, WorkerType::CPU_TTS, WorkerType::GPU_IMAGE}) {
        std::string worker_prefix = getWorkerConfigKeyString(worker_type) + ".";
        
        auto worker_it = worker_configs_.find(worker_type);
        if (worker_it != worker_configs_.end()) {
            for (const auto& [key, value] : worker_it->second) {
                keys.push_back(worker_prefix + getWorkerConfigKeyString(key));
            }
        }
    }
    
    // 获取API服务器配置键
    for (const auto& [key, value] : api_server_configs_) {
        keys.push_back("api_server." + getAPIServerConfigKeyString(key));
    }
    
    // 获取监控配置键
    for (const auto& [key, value] : monitoring_configs_) {
        keys.push_back("monitoring." + getMonitoringConfigKeyString(key));
    }
    
    // 获取优化配置键
    for (const auto& [key, value] : optimization_configs_) {
        keys.push_back("optimization." + getOptimizationConfigKeyString(key));
    }
    
    // 获取全局配置键
    for (const auto& [key, value] : global_configs_) {
        keys.push_back(key);
    }
    
    return keys;
}

void SystemConfig::registerConfigChangeListener(ConfigChangeListener listener) {
    std::lock_guard<std::mutex> lock(listener_mutex_);
    config_change_listeners_.push_back(listener);
}

void SystemConfig::notifyConfigChanged(const std::string& key, const ConfigValue& value) {
    std::lock_guard<std::mutex> lock(listener_mutex_);
    
    for (const auto& listener : config_change_listeners_) {
        try {
            listener(key, value);
        } catch (const std::exception& e) {
            std::cerr << "Error in config change listener: " << e.what() << std::endl;
        }
    }
}

void SystemConfig::initializeDefaults() {
    // 初始化GPU LLM工作器默认配置
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::ENABLED] = ConfigValue(true);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_THREADS] = ConfigValue(4);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MIN_THREADS] = ConfigValue(2);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::QUEUE_CAPACITY] = ConfigValue(100);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::BATCH_SIZE] = ConfigValue(8);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_BATCH_SIZE] = ConfigValue(32);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MIN_BATCH_SIZE] = ConfigValue(1);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::BATCH_TIMEOUT_MS] = ConfigValue(50);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_CONCURRENT_TASKS] = ConfigValue(4);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::GPU_ID] = ConfigValue(0);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_GPU_MEMORY_MB] = ConfigValue(8192);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::GPU_UTIL_THRESHOLD] = ConfigValue(0.8f);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::LLM_MODEL_PATH] = ConfigValue("models/llm/model.bin");
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::LLM_CONTEXT_SIZE] = ConfigValue(4096);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::LLM_TEMPERATURE] = ConfigValue(0.7f);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::LLM_MAX_TOKENS] = ConfigValue(1024);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_MEMORY_MB] = ConfigValue(16384);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::MAX_CPU_USAGE_PERCENT] = ConfigValue(80);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::ENABLE_CACHING] = ConfigValue(true);
    worker_configs_[WorkerType::GPU_LLM][WorkerConfigKey::CACHE_SIZE_MB] = ConfigValue(1024);
    
    // 初始化CPU TTS工作器默认配置
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::ENABLED] = ConfigValue(true);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MAX_THREADS] = ConfigValue(8);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MIN_THREADS] = ConfigValue(4);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::QUEUE_CAPACITY] = ConfigValue(200);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::BATCH_SIZE] = ConfigValue(4);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MAX_BATCH_SIZE] = ConfigValue(16);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MIN_BATCH_SIZE] = ConfigValue(1);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::BATCH_TIMEOUT_MS] = ConfigValue(20);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MAX_CONCURRENT_TASKS] = ConfigValue(8);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::CPU_AFFINITY] = ConfigValue("all");
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::CPU_PRIORITY] = ConfigValue("normal");
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::TTS_MODEL_PATH] = ConfigValue("models/tts/coqui_models/");
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::TTS_VOICE] = ConfigValue("en-US");
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::TTS_SAMPLE_RATE] = ConfigValue(22050);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::TTS_SPEED] = ConfigValue(1.0f);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::TTS_PITCH] = ConfigValue(1.0f);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MAX_MEMORY_MB] = ConfigValue(4096);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::MAX_CPU_USAGE_PERCENT] = ConfigValue(90);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::ENABLE_CACHING] = ConfigValue(true);
    worker_configs_[WorkerType::CPU_TTS][WorkerConfigKey::CACHE_SIZE_MB] = ConfigValue(512);
    
    // 初始化GPU图像工作器默认配置
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::ENABLED] = ConfigValue(true);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_THREADS] = ConfigValue(2);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MIN_THREADS] = ConfigValue(1);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::QUEUE_CAPACITY] = ConfigValue(50);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::BATCH_SIZE] = ConfigValue(2);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_BATCH_SIZE] = ConfigValue(8);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MIN_BATCH_SIZE] = ConfigValue(1);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::BATCH_TIMEOUT_MS] = ConfigValue(200);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_CONCURRENT_TASKS] = ConfigValue(2);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::GPU_ID] = ConfigValue(0);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_GPU_MEMORY_MB] = ConfigValue(4096);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::GPU_UTIL_THRESHOLD] = ConfigValue(0.6f); // 图像生成使用较低的阈值
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::IMAGE_MODEL_PATH] = ConfigValue("models/image/stable_diffusion/");
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::IMAGE_DEFAULT_WIDTH] = ConfigValue(512);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::IMAGE_DEFAULT_HEIGHT] = ConfigValue(512);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::IMAGE_STEPS] = ConfigValue(20);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::IMAGE_GUIDANCE_SCALE] = ConfigValue(7.5f);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_MEMORY_MB] = ConfigValue(8192);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::MAX_CPU_USAGE_PERCENT] = ConfigValue(70);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::ENABLE_CACHING] = ConfigValue(true);
    worker_configs_[WorkerType::GPU_IMAGE][WorkerConfigKey::CACHE_SIZE_MB] = ConfigValue(2048);
    
    // 初始化API服务器默认配置
    api_server_configs_[APIServerConfigKey::ENABLED] = ConfigValue(true);
    api_server_configs_[APIServerConfigKey::PORT] = ConfigValue(8080);
    api_server_configs_[APIServerConfigKey::HOST] = ConfigValue("0.0.0.0");
    api_server_configs_[APIServerConfigKey::MAX_CONNECTIONS] = ConfigValue(100);
    api_server_configs_[APIServerConfigKey::CONNECTION_TIMEOUT_MS] = ConfigValue(30000);
    api_server_configs_[APIServerConfigKey::ENABLE_SSL] = ConfigValue(false);
    api_server_configs_[APIServerConfigKey::SSL_CERT_PATH] = ConfigValue("ssl/cert.pem");
    api_server_configs_[APIServerConfigKey::SSL_KEY_PATH] = ConfigValue("ssl/key.pem");
    api_server_configs_[APIServerConfigKey::ENABLE_COMPRESSION] = ConfigValue(true);
    api_server_configs_[APIServerConfigKey::MAX_REQUEST_SIZE_MB] = ConfigValue(10);
    api_server_configs_[APIServerConfigKey::RATE_LIMIT_PER_SECOND] = ConfigValue(100);
    
    // 初始化监控默认配置
    monitoring_configs_[MonitoringConfigKey::ENABLED] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::COLLECTION_INTERVAL_MS] = ConfigValue(1000);
    monitoring_configs_[MonitoringConfigKey::ENABLE_CPU_MONITORING] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::ENABLE_GPU_MONITORING] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::ENABLE_MEMORY_MONITORING] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::ENABLE_DISK_MONITORING] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::ENABLE_NETWORK_MONITORING] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::METRICS_EXPORT_PORT] = ConfigValue(9090);
    monitoring_configs_[MonitoringConfigKey::ENABLE_PROMETHEUS_EXPORT] = ConfigValue(true);
    monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_CPU] = ConfigValue(90.0f);
    monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_GPU] = ConfigValue(85.0f);
    monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_MEMORY] = ConfigValue(90.0f);
    
    // 初始化优化默认配置
    optimization_configs_[OptimizationConfigKey::ENABLED] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::STRATEGY] = ConfigValue("balanced");
    optimization_configs_[OptimizationConfigKey::AUTO_TUNE_THREADS] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::AUTO_TUNE_BATCH_SIZE] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::ENABLE_MEMORY_OPTIMIZATION] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::ENABLE_TASK_PRIORITIZATION] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::ENABLE_BATCHING] = ConfigValue(true);
    optimization_configs_[OptimizationConfigKey::OPTIMIZATION_INTERVAL_MS] = ConfigValue(5000);
    
    // 初始化全局默认配置
    global_configs_["log_level"] = ConfigValue("info");
    global_configs_["metrics_collection_interval_ms"] = ConfigValue(1000);
    global_configs_["enable_profiling"] = ConfigValue(false);
    global_configs_["enable_statistics"] = ConfigValue(true);
    global_configs_["shutdown_timeout_ms"] = ConfigValue(5000);
    global_configs_["temp_directory"] = ConfigValue("/tmp/ai_scheduler");
    global_configs_["models_directory"] = ConfigValue("models");
    global_configs_["max_concurrent_requests"] = ConfigValue(100);
}

// 辅助方法：从JSON加载工作器配置
void SystemConfig::loadWorkerConfigFromJson(WorkerType worker_type, const nlohmann::json& json) {
    // 通用配置
    if (json.contains("enabled")) worker_configs_[worker_type][WorkerConfigKey::ENABLED] = ConfigValue(json["enabled"].get<bool>());
    if (json.contains("max_threads")) worker_configs_[worker_type][WorkerConfigKey::MAX_THREADS] = ConfigValue(json["max_threads"].get<int64_t>());
    if (json.contains("min_threads")) worker_configs_[worker_type][WorkerConfigKey::MIN_THREADS] = ConfigValue(json["min_threads"].get<int64_t>());
    if (json.contains("queue_capacity")) worker_configs_[worker_type][WorkerConfigKey::QUEUE_CAPACITY] = ConfigValue(json["queue_capacity"].get<int64_t>());
    if (json.contains("batch_size")) worker_configs_[worker_type][WorkerConfigKey::BATCH_SIZE] = ConfigValue(json["batch_size"].get<int64_t>());
    if (json.contains("max_batch_size")) worker_configs_[worker_type][WorkerConfigKey::MAX_BATCH_SIZE] = ConfigValue(json["max_batch_size"].get<int64_t>());
    if (json.contains("min_batch_size")) worker_configs_[worker_type][WorkerConfigKey::MIN_BATCH_SIZE] = ConfigValue(json["min_batch_size"].get<int64_t>());
    if (json.contains("batch_timeout_ms")) worker_configs_[worker_type][WorkerConfigKey::BATCH_TIMEOUT_MS] = ConfigValue(json["batch_timeout_ms"].get<int64_t>());
    if (json.contains("max_concurrent_tasks")) worker_configs_[worker_type][WorkerConfigKey::MAX_CONCURRENT_TASKS] = ConfigValue(json["max_concurrent_tasks"].get<int64_t>());
    
    // GPU特定配置
    if (json.contains("gpu_id")) worker_configs_[worker_type][WorkerConfigKey::GPU_ID] = ConfigValue(json["gpu_id"].get<int64_t>());
    if (json.contains("max_gpu_memory_mb")) worker_configs_[worker_type][WorkerConfigKey::MAX_GPU_MEMORY_MB] = ConfigValue(json["max_gpu_memory_mb"].get<int64_t>());
    if (json.contains("gpu_util_threshold")) worker_configs_[worker_type][WorkerConfigKey::GPU_UTIL_THRESHOLD] = ConfigValue(json["gpu_util_threshold"].get<double>());
    
    // CPU特定配置
    if (json.contains("cpu_affinity")) worker_configs_[worker_type][WorkerConfigKey::CPU_AFFINITY] = ConfigValue(json["cpu_affinity"].get<std::string>());
    if (json.contains("cpu_priority")) worker_configs_[worker_type][WorkerConfigKey::CPU_PRIORITY] = ConfigValue(json["cpu_priority"].get<std::string>());
    
    // LLM特定配置
    if (json.contains("model_path")) worker_configs_[worker_type][WorkerConfigKey::LLM_MODEL_PATH] = ConfigValue(json["model_path"].get<std::string>());
    if (json.contains("context_size")) worker_configs_[worker_type][WorkerConfigKey::LLM_CONTEXT_SIZE] = ConfigValue(json["context_size"].get<int64_t>());
    if (json.contains("temperature")) worker_configs_[worker_type][WorkerConfigKey::LLM_TEMPERATURE] = ConfigValue(json["temperature"].get<double>());
    if (json.contains("max_tokens")) worker_configs_[worker_type][WorkerConfigKey::LLM_MAX_TOKENS] = ConfigValue(json["max_tokens"].get<int64_t>());
    
    // TTS特定配置
    if (json.contains("model_path")) worker_configs_[worker_type][WorkerConfigKey::TTS_MODEL_PATH] = ConfigValue(json["model_path"].get<std::string>());
    if (json.contains("voice")) worker_configs_[worker_type][WorkerConfigKey::TTS_VOICE] = ConfigValue(json["voice"].get<std::string>());
    if (json.contains("sample_rate")) worker_configs_[worker_type][WorkerConfigKey::TTS_SAMPLE_RATE] = ConfigValue(json["sample_rate"].get<int64_t>());
    if (json.contains("speed")) worker_configs_[worker_type][WorkerConfigKey::TTS_SPEED] = ConfigValue(json["speed"].get<double>());
    if (json.contains("pitch")) worker_configs_[worker_type][WorkerConfigKey::TTS_PITCH] = ConfigValue(json["pitch"].get<double>());
    
    // 图像特定配置
    if (json.contains("model_path")) worker_configs_[worker_type][WorkerConfigKey::IMAGE_MODEL_PATH] = ConfigValue(json["model_path"].get<std::string>());
    if (json.contains("default_width")) worker_configs_[worker_type][WorkerConfigKey::IMAGE_DEFAULT_WIDTH] = ConfigValue(json["default_width"].get<int64_t>());
    if (json.contains("default_height")) worker_configs_[worker_type][WorkerConfigKey::IMAGE_DEFAULT_HEIGHT] = ConfigValue(json["default_height"].get<int64_t>());
    if (json.contains("steps")) worker_configs_[worker_type][WorkerConfigKey::IMAGE_STEPS] = ConfigValue(json["steps"].get<int64_t>());
    if (json.contains("guidance_scale")) worker_configs_[worker_type][WorkerConfigKey::IMAGE_GUIDANCE_SCALE] = ConfigValue(json["guidance_scale"].get<double>());
    
    // 资源限制
    if (json.contains("max_memory_mb")) worker_configs_[worker_type][WorkerConfigKey::MAX_MEMORY_MB] = ConfigValue(json["max_memory_mb"].get<int64_t>());
    if (json.contains("max_cpu_usage_percent")) worker_configs_[worker_type][WorkerConfigKey::MAX_CPU_USAGE_PERCENT] = ConfigValue(json["max_cpu_usage_percent"].get<int64_t>());
    
    // 高级配置
    if (json.contains("enable_caching")) worker_configs_[worker_type][WorkerConfigKey::ENABLE_CACHING] = ConfigValue(json["enable_caching"].get<bool>());
    if (json.contains("cache_size_mb")) worker_configs_[worker_type][WorkerConfigKey::CACHE_SIZE_MB] = ConfigValue(json["cache_size_mb"].get<int64_t>());
}

// 辅助方法：从JSON加载API服务器配置
void SystemConfig::loadAPIServerConfigFromJson(const nlohmann::json& json) {
    if (json.contains("enabled")) api_server_configs_[APIServerConfigKey::ENABLED] = ConfigValue(json["enabled"].get<bool>());
    if (json.contains("port")) api_server_configs_[APIServerConfigKey::PORT] = ConfigValue(json["port"].get<int64_t>());
    if (json.contains("host")) api_server_configs_[APIServerConfigKey::HOST] = ConfigValue(json["host"].get<std::string>());
    if (json.contains("max_connections")) api_server_configs_[APIServerConfigKey::MAX_CONNECTIONS] = ConfigValue(json["max_connections"].get<int64_t>());
    if (json.contains("connection_timeout_ms")) api_server_configs_[APIServerConfigKey::CONNECTION_TIMEOUT_MS] = ConfigValue(json["connection_timeout_ms"].get<int64_t>());
    if (json.contains("enable_ssl")) api_server_configs_[APIServerConfigKey::ENABLE_SSL] = ConfigValue(json["enable_ssl"].get<bool>());
    if (json.contains("ssl_cert_path")) api_server_configs_[APIServerConfigKey::SSL_CERT_PATH] = ConfigValue(json["ssl_cert_path"].get<std::string>());
    if (json.contains("ssl_key_path")) api_server_configs_[APIServerConfigKey::SSL_KEY_PATH] = ConfigValue(json["ssl_key_path"].get<std::string>());
    if (json.contains("enable_compression")) api_server_configs_[APIServerConfigKey::ENABLE_COMPRESSION] = ConfigValue(json["enable_compression"].get<bool>());
    if (json.contains("max_request_size_mb")) api_server_configs_[APIServerConfigKey::MAX_REQUEST_SIZE_MB] = ConfigValue(json["max_request_size_mb"].get<int64_t>());
    if (json.contains("rate_limit_per_second")) api_server_configs_[APIServerConfigKey::RATE_LIMIT_PER_SECOND] = ConfigValue(json["rate_limit_per_second"].get<int64_t>());
}

// 辅助方法：从JSON加载监控配置
void SystemConfig::loadMonitoringConfigFromJson(const nlohmann::json& json) {
    if (json.contains("enabled")) monitoring_configs_[MonitoringConfigKey::ENABLED] = ConfigValue(json["enabled"].get<bool>());
    if (json.contains("collection_interval_ms")) monitoring_configs_[MonitoringConfigKey::COLLECTION_INTERVAL_MS] = ConfigValue(json["collection_interval_ms"].get<int64_t>());
    if (json.contains("enable_cpu_monitoring")) monitoring_configs_[MonitoringConfigKey::ENABLE_CPU_MONITORING] = ConfigValue(json["enable_cpu_monitoring"].get<bool>());
    if (json.contains("enable_gpu_monitoring")) monitoring_configs_[MonitoringConfigKey::ENABLE_GPU_MONITORING] = ConfigValue(json["enable_gpu_monitoring"].get<bool>());
    if (json.contains("enable_memory_monitoring")) monitoring_configs_[MonitoringConfigKey::ENABLE_MEMORY_MONITORING] = ConfigValue(json["enable_memory_monitoring"].get<bool>());
    if (json.contains("enable_disk_monitoring")) monitoring_configs_[MonitoringConfigKey::ENABLE_DISK_MONITORING] = ConfigValue(json["enable_disk_monitoring"].get<bool>());
    if (json.contains("enable_network_monitoring")) monitoring_configs_[MonitoringConfigKey::ENABLE_NETWORK_MONITORING] = ConfigValue(json["enable_network_monitoring"].get<bool>());
    if (json.contains("metrics_export_port")) monitoring_configs_[MonitoringConfigKey::METRICS_EXPORT_PORT] = ConfigValue(json["metrics_export_port"].get<int64_t>());
    if (json.contains("enable_prometheus_export")) monitoring_configs_[MonitoringConfigKey::ENABLE_PROMETHEUS_EXPORT] = ConfigValue(json["enable_prometheus_export"].get<bool>());
    if (json.contains("alert_threshold_cpu")) monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_CPU] = ConfigValue(json["alert_threshold_cpu"].get<double>());
    if (json.contains("alert_threshold_gpu")) monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_GPU] = ConfigValue(json["alert_threshold_gpu"].get<double>());
    if (json.contains("alert_threshold_memory")) monitoring_configs_[MonitoringConfigKey::ALERT_THRESHOLD_MEMORY] = ConfigValue(json["alert_threshold_memory"].get<double>());
}

// 辅助方法：从JSON加载优化配置
void SystemConfig::loadOptimizationConfigFromJson(const nlohmann::json& json) {
    if (json.contains("enabled")) optimization_configs_[OptimizationConfigKey::ENABLED] = ConfigValue(json["enabled"].get<bool>());
    if (json.contains("strategy")) optimization_configs_[OptimizationConfigKey::STRATEGY] = ConfigValue(json["strategy"].get<std::string>());
    if (json.contains("auto_tune_threads")) optimization_configs_[OptimizationConfigKey::AUTO_TUNE_THREADS] = ConfigValue(json["auto_tune_threads"].get<bool>());
    if (json.contains("auto_tune_batch_size")) optimization_configs_[OptimizationConfigKey::AUTO_TUNE_BATCH_SIZE] = ConfigValue(json["auto_tune_batch_size"].get<bool>());
    if (json.contains("enable_memory_optimization")) optimization_configs_[OptimizationConfigKey::ENABLE_MEMORY_OPTIMIZATION] = ConfigValue(json["enable_memory_optimization"].get<bool>());
    if (json.contains("enable_task_prioritization")) optimization_configs_[OptimizationConfigKey::ENABLE_TASK_PRIORITIZATION] = ConfigValue(json["enable_task_prioritization"].get<bool>());
    if (json.contains("enable_batching")) optimization_configs_[OptimizationConfigKey::ENABLE_BATCHING] = ConfigValue(json["enable_batching"].get<bool>());
    if (json.contains("optimization_interval_ms")) optimization_configs_[OptimizationConfigKey::OPTIMIZATION_INTERVAL_MS] = ConfigValue(json["optimization_interval_ms"].get<int64_t>());
}

// 辅助方法：导出工作器配置为JSON
nlohmann::json SystemConfig::exportWorkerConfigToJson(WorkerType worker_type) const {
    nlohmann::json json;
    
    auto worker_it = worker_configs_.find(worker_type);
    if (worker_it != worker_configs_.end()) {
        const auto& configs = worker_it->second;
        
        // 导出所有配置项
        for (const auto& [key, value] : configs) {
            if (value.isValid()) {
                std::string key_name = getWorkerConfigKeyString(key);
                
                // 根据值类型导出
                if (key_name == "enabled" || key_name == "enable_caching") {
                    json[key_name] = value.asBool();
                } else if (key_name == "gpu_util_threshold" || 
                          key_name == "temperature" || 
                          key_name == "speed" || 
                          key_name == "pitch" || 
                          key_name == "guidance_scale") {
                    json[key_name] = value.asDouble();
                } else if (key_name == "model_path" || 
                          key_name == "voice" || 
                          key_name == "cpu_affinity" || 
                          key_name == "cpu_priority") {
                    json[key_name] = value.asString();
                } else {
                    // 其他为整数类型
                    json[key_name] = value.asInt();
                }
            }
        }
    }
    
    return json;
}

// 辅助方法：导出API服务器配置为JSON
nlohmann::json SystemConfig::exportAPIServerConfigToJson() const {
    nlohmann::json json;
    
    for (const auto& [key, value] : api_server_configs_) {
        if (value.isValid()) {
            std::string key_name = getAPIServerConfigKeyString(key);
            
            if (key_name == "enabled" || key_name == "enable_ssl" || key_name == "enable_compression") {
                json[key_name] = value.asBool();
            } else if (key_name == "host" || key_name == "ssl_cert_path" || key_name == "ssl_key_path") {
                json[key_name] = value.asString();
            } else {
                json[key_name] = value.asInt();
            }
        }
    }
    
    return json;
}

// 辅助方法：导出监控配置为JSON
nlohmann::json SystemConfig::exportMonitoringConfigToJson() const {
    nlohmann::json json;
    
    for (const auto& [key, value] : monitoring_configs_) {
        if (value.isValid()) {
            std::string key_name = getMonitoringConfigKeyString(key);
            
            if (key_name == "enabled" || 
                key_name == "enable_cpu_monitoring" || 
                key_name == "enable_gpu_monitoring" || 
                key_name == "enable_memory_monitoring" || 
                key_name == "enable_disk_monitoring" || 
                key_name == "enable_network_monitoring" || 
                key_name == "enable_prometheus_export") {
                json[key_name] = value.asBool();
            } else if (key_name == "alert_threshold_cpu" || 
                      key_name == "alert_threshold_gpu" || 
                      key_name == "alert_threshold_memory") {
                json[key_name] = value.asDouble();
            } else {
                json[key_name] = value.asInt();
            }
        }
    }
    
    return json;
}

// 辅助方法：导出优化配置为JSON
nlohmann::json SystemConfig::exportOptimizationConfigToJson() const {
    nlohmann::json json;
    
    for (const auto& [key, value] : optimization_configs_) {
        if (value.isValid()) {
            std::string key_name = getOptimizationConfigKeyString(key);
            
            if (key_name == "enabled" || 
                key_name == "auto_tune_threads" || 
                key_name == "auto_tune_batch_size" || 
                key_name == "enable_memory_optimization" || 
                key_name == "enable_task_prioritization" || 
                key_name == "enable_batching") {
                json[key_name] = value.asBool();
            } else if (key_name == "strategy") {
                json[key_name] = value.asString();
            } else {
                json[key_name] = value.asInt();
            }
        }
    }
    
    return json;
}

// 辅助方法：获取工作器类型字符串
std::string SystemConfig::getWorkerConfigKeyString(WorkerType worker_type) {
    switch (worker_type) {
        case WorkerType::GPU_LLM:
            return "gpu_llm";
        case WorkerType::CPU_TTS:
            return "cpu_tts";
        case WorkerType::GPU_IMAGE:
            return "gpu_image";
        default:
            return "unknown";
    }
}

// 辅助方法：获取工作器配置键字符串
std::string SystemConfig::getWorkerConfigKeyString(WorkerConfigKey key) {
    switch (key) {
        case WorkerConfigKey::ENABLED:
            return "enabled";
        case WorkerConfigKey::MAX_THREADS:
            return "max_threads";
        case WorkerConfigKey::MIN_THREADS:
            return "min_threads";
        case WorkerConfigKey::QUEUE_CAPACITY:
            return "queue_capacity";
        case WorkerConfigKey::BATCH_SIZE:
            return "batch_size";
        case WorkerConfigKey::MAX_BATCH_SIZE:
            return "max_batch_size";
        case WorkerConfigKey::MIN_BATCH_SIZE:
            return "min_batch_size";
        case WorkerConfigKey::BATCH_TIMEOUT_MS:
            return "batch_timeout_ms";
        case WorkerConfigKey::MAX_CONCURRENT_TASKS:
            return "max_concurrent_tasks";
        case WorkerConfigKey::GPU_ID:
            return "gpu_id";
        case WorkerConfigKey::MAX_GPU_MEMORY_MB:
            return "max_gpu_memory_mb";
        case WorkerConfigKey::GPU_UTIL_THRESHOLD:
            return "gpu_util_threshold";
        case WorkerConfigKey::CPU_AFFINITY:
            return "cpu_affinity";
        case WorkerConfigKey::CPU_PRIORITY:
            return "cpu_priority";
        case WorkerConfigKey::LLM_MODEL_PATH:
        case WorkerConfigKey::TTS_MODEL_PATH:
        case WorkerConfigKey::IMAGE_MODEL_PATH:
            return "model_path";
        case WorkerConfigKey::LLM_CONTEXT_SIZE:
            return "context_size";
        case WorkerConfigKey::LLM_TEMPERATURE:
            return "temperature";
        case WorkerConfigKey::LLM_MAX_TOKENS:
            return "max_tokens";
        case WorkerConfigKey::TTS_VOICE:
            return "voice";
        case WorkerConfigKey::TTS_SAMPLE_RATE:
            return "sample_rate";
        case WorkerConfigKey::TTS_SPEED:
            return "speed";
        case WorkerConfigKey::TTS_PITCH:
            return "pitch";
        case WorkerConfigKey::IMAGE_DEFAULT_WIDTH:
            return "default_width";
        case WorkerConfigKey::IMAGE_DEFAULT_HEIGHT:
            return "default_height";
        case WorkerConfigKey::IMAGE_STEPS:
            return "steps";
        case WorkerConfigKey::IMAGE_GUIDANCE_SCALE:
            return "guidance_scale";
        case WorkerConfigKey::MAX_MEMORY_MB:
            return "max_memory_mb";
        case WorkerConfigKey::MAX_CPU_USAGE_PERCENT:
            return "max_cpu_usage_percent";
        case WorkerConfigKey::ENABLE_CACHING:
            return "enable_caching";
        case WorkerConfigKey::CACHE_SIZE_MB:
            return "cache_size_mb";
        default:
            return "unknown";
    }
}

// 辅助方法：获取API服务器配置键字符串
std::string SystemConfig::getAPIServerConfigKeyString(APIServerConfigKey key) {
    switch (key) {
        case APIServerConfigKey::ENABLED:
            return "enabled";
        case APIServerConfigKey::PORT:
            return "port";
        case APIServerConfigKey::HOST:
            return "host";
        case APIServerConfigKey::MAX_CONNECTIONS:
            return "max_connections";
        case APIServerConfigKey::CONNECTION_TIMEOUT_MS:
            return "connection_timeout_ms";
        case APIServerConfigKey::ENABLE_SSL:
            return "enable_ssl";
        case APIServerConfigKey::SSL_CERT_PATH:
            return "ssl_cert_path";
        case APIServerConfigKey::SSL_KEY_PATH:
            return "ssl_key_path";
        case APIServerConfigKey::ENABLE_COMPRESSION:
            return "enable_compression";
        case APIServerConfigKey::MAX_REQUEST_SIZE_MB:
            return "max_request_size_mb";
        case APIServerConfigKey::RATE_LIMIT_PER_SECOND:
            return "rate_limit_per_second";
        default:
            return "unknown";
    }
}

// 辅助方法：获取监控配置键字符串
std::string SystemConfig::getMonitoringConfigKeyString(MonitoringConfigKey key) {
    switch (key) {
        case MonitoringConfigKey::ENABLED:
            return "enabled";
        case MonitoringConfigKey::COLLECTION_INTERVAL_MS:
            return "collection_interval_ms";
        case MonitoringConfigKey::ENABLE_CPU_MONITORING:
            return "enable_cpu_monitoring";
        case MonitoringConfigKey::ENABLE_GPU_MONITORING:
            return "enable_gpu_monitoring";
        case MonitoringConfigKey::ENABLE_MEMORY_MONITORING:
            return "enable_memory_monitoring";
        case MonitoringConfigKey::ENABLE_DISK_MONITORING:
            return "enable_disk_monitoring";
        case MonitoringConfigKey::ENABLE_NETWORK_MONITORING:
            return "enable_network_monitoring";
        case MonitoringConfigKey::METRICS_EXPORT_PORT:
            return "metrics_export_port";
        case MonitoringConfigKey::ENABLE_PROMETHEUS_EXPORT:
            return "enable_prometheus_export";
        case MonitoringConfigKey::ALERT_THRESHOLD_CPU:
            return "alert_threshold_cpu";
        case MonitoringConfigKey::ALERT_THRESHOLD_GPU:
            return "alert_threshold_gpu";
        case MonitoringConfigKey::ALERT_THRESHOLD_MEMORY:
            return "alert_threshold_memory";
        default:
            return "unknown";
    }
}

// 辅助方法：获取优化配置键字符串
std::string SystemConfig::getOptimizationConfigKeyString(OptimizationConfigKey key) {
    switch (key) {
        case OptimizationConfigKey::ENABLED:
            return "enabled";
        case OptimizationConfigKey::STRATEGY:
            return "strategy";
        case OptimizationConfigKey::AUTO_TUNE_THREADS:
            return "auto_tune_threads";
        case OptimizationConfigKey::AUTO_TUNE_BATCH_SIZE:
            return "auto_tune_batch_size";
        case OptimizationConfigKey::ENABLE_MEMORY_OPTIMIZATION:
            return "enable_memory_optimization";
        case OptimizationConfigKey::ENABLE_TASK_PRIORITIZATION:
            return "enable_task_prioritization";
        case OptimizationConfigKey::ENABLE_BATCHING:
            return "enable_batching";
        case OptimizationConfigKey::OPTIMIZATION_INTERVAL_MS:
            return "optimization_interval_ms";
        default:
            return "unknown";
    }
}

// ConfigHelper 实现
bool ConfigHelper::isWorkerEnabled(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::ENABLED, ConfigValue(true)).asBool();
}

int ConfigHelper::getWorkerMaxThreads(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::MAX_THREADS).asInt();
}

int ConfigHelper::getWorkerMinThreads(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::MIN_THREADS).asInt();
}

int ConfigHelper::getWorkerQueueCapacity(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::QUEUE_CAPACITY).asInt();
}

int ConfigHelper::getWorkerBatchSize(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::BATCH_SIZE).asInt();
}

int ConfigHelper::getWorkerGpuId(WorkerType worker_type) {
    return SystemConfig::getInstance()->getWorkerConfig(worker_type, WorkerConfigKey::GPU_ID, ConfigValue(0)).asInt();
}

LogLevel ConfigHelper::getLogLevel() {
    std::string level_str = SystemConfig::getInstance()->getGlobalConfig("log_level", ConfigValue("info")).asString();
    std::transform(level_str.begin(), level_str.end(), level_str.begin(), ::tolower);
    
    if (level_str == "trace") return LogLevel::TRACE;
    if (level_str == "debug") return LogLevel::DEBUG;
    if (level_str == "info") return LogLevel::INFO;
    if (level_str == "warning" || level_str == "warn") return LogLevel::WARNING;
    if (level_str == "error") return LogLevel::ERROR;
    if (level_str == "fatal") return LogLevel::FATAL;
    
    return LogLevel::INFO; // 默认
}

void ConfigHelper::setLogLevel(LogLevel level) {
    std::string level_str;
    switch (level) {
        case LogLevel::TRACE:
            level_str = "trace";
            break;
        case LogLevel::DEBUG:
            level_str = "debug";
            break;
        case LogLevel::INFO:
            level_str = "info";
            break;
        case LogLevel::WARNING:
            level_str = "warning";
            break;
        case LogLevel::ERROR:
            level_str = "error";
            break;
        case LogLevel::FATAL:
            level_str = "fatal";
            break;
    }
    SystemConfig::getInstance()->setGlobalConfig("log_level", ConfigValue(level_str));
}

int ConfigHelper::getApiServerPort() {
    return SystemConfig::getInstance()->getAPIServerConfig(APIServerConfigKey::PORT, ConfigValue(8080)).asInt();
}

std::string ConfigHelper::getApiServerHost() {
    return SystemConfig::getInstance()->getAPIServerConfig(APIServerConfigKey::HOST, ConfigValue("0.0.0.0")).asString();
}

bool ConfigHelper::isMonitoringEnabled() {
    return SystemConfig::getInstance()->getMonitoringConfig(MonitoringConfigKey::ENABLED, ConfigValue(true)).asBool();
}

int ConfigHelper::getMetricsCollectionInterval() {
    return SystemConfig::getInstance()->getMonitoringConfig(MonitoringConfigKey::COLLECTION_INTERVAL_MS, ConfigValue(1000)).asInt();
}

bool ConfigHelper::isOptimizationEnabled() {
    return SystemConfig::getInstance()->getOptimizationConfig(OptimizationConfigKey::ENABLED, ConfigValue(true)).asBool();
}

std::string ConfigHelper::getOptimizationStrategy() {
    return SystemConfig::getInstance()->getOptimizationConfig(OptimizationConfigKey::STRATEGY, ConfigValue("balanced")).asString();
}

bool ConfigHelper::adjustWorkerConfig(WorkerType worker_type, WorkerConfigKey key, const ConfigValue& value) {
    try {
        SystemConfig::getInstance()->setWorkerConfig(worker_type, key, value);
        return true;
    } catch (...) {
        return false;
    }
}

bool ConfigHelper::applyPerformanceSuggestions(const std::vector<std::string>& suggestions) {
    bool success = true;
    
    for (const auto& suggestion : suggestions) {
        // 解析建议字符串并应用相应的配置更改
        // 这里只是一个示例，实际应该根据建议的格式进行解析
        std::cout << "Applying performance suggestion: " << suggestion << std::endl;
        
        // 示例：如果建议是增加LLM工作器的批处理大小
        if (suggestion.find("LLM批处理大小") != std::string::npos && suggestion.find("增加") != std::string::npos) {
            int current_batch = getWorkerBatchSize(WorkerType::GPU_LLM);
            int new_batch = std::min(current_batch + 2, 32); // 最多增加到32
            adjustWorkerConfig(WorkerType::GPU_LLM, WorkerConfigKey::BATCH_SIZE, ConfigValue(new_batch));
        }
        
        // 示例：如果建议是增加CPU工作线程
        if (suggestion.find("TTS任务队列过长") != std::string::npos && suggestion.find("增加CPU工作线程") != std::string::npos) {
            int current_threads = getWorkerMaxThreads(WorkerType::CPU_TTS);
            int new_threads = current_threads + 2;
            adjustWorkerConfig(WorkerType::CPU_TTS, WorkerConfigKey::MAX_THREADS, ConfigValue(new_threads));
        }
    }
    
    return success;
}

bool ConfigHelper::generateDefaultConfigFile(const std::string& file_path) {
    auto config = SystemConfig::getInstance();
    config->resetToDefaults();
    return config->saveToFile(file_path);
}

} // namespace ai_scheduler::config