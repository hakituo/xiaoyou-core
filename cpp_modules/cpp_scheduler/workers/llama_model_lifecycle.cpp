#include "llama_model_impl.h"

#include <algorithm>
#include <cstring>
#include <iostream>

#include "llama.h"

namespace ai_scheduler {

namespace {

bool g_llama_backend_initialized = false;
bool g_llama_log_installed = false;

void llama_log_callback(
    ggml_log_level level,
    const char* text,
    void* user_data
) {
    (void)user_data;
    if (!text || std::strstr(text, "n_ctx_per_seq") != nullptr) {
        return;
    }
    if (level == GGML_LOG_LEVEL_ERROR || level == GGML_LOG_LEVEL_WARN) {
        std::cerr << text;
        return;
    }
    std::cout << text;
}

}  // namespace

LlamaCppModel::LlamaCppModel() {
    if (!g_llama_backend_initialized) {
        llama_backend_init();
        if (!g_llama_log_installed) {
            llama_log_set(llama_log_callback, nullptr);
            g_llama_log_installed = true;
        }
        g_llama_backend_initialized = true;
    }
}

LlamaCppModel::~LlamaCppModel() {
    shutdown();
}

bool LlamaCppModel::initialize(const LLMModelConfig& config) {
    if (ready_) {
        return true;
    }

    config_ = config;
    std::cout << "Loading llama model from: " << config_.modelPath << std::endl;

    llama_log_set([](ggml_log_level level, const char* text, void* user_data) {
        (void)level;
        (void)user_data;
        if (text && std::strstr(text, "n_ctx_per_seq") != nullptr) {
            return;
        }
        if (text) {
            fprintf(stderr, "%s", text);
        }
    }, nullptr);

    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = config.nGpuLayers >= 0 ? config.nGpuLayers : 999;
    model_params.main_gpu = config.gpuDeviceId >= 0 ? config.gpuDeviceId : 0;

    model_ = llama_model_load_from_file(config.modelPath.c_str(), model_params);
    if (!model_) {
        std::cerr << "Failed to load llama model: " << config_.modelPath << std::endl;
        return false;
    }

    llama_context_params ctx_params = llama_context_default_params();
    ctx_params.n_ctx = config_.maxContextSize > 0
        ? (uint32_t)config_.maxContextSize
        : 4096;
    ctx_params.n_batch = config_.maxBatchSize > 0
        ? (uint32_t)config_.maxBatchSize
        : 512;
    uint32_t safe_batch_limit = ctx_params.n_ctx > 1 ? ctx_params.n_ctx / 2 : 1;
    if (ctx_params.n_batch > safe_batch_limit) {
        ctx_params.n_batch = safe_batch_limit;
    }
    if (ctx_params.n_batch < 1) {
        ctx_params.n_batch = 1;
    }
    if (config_.maxBatchSize <= 0
        || config_.maxBatchSize != (int32_t)ctx_params.n_batch) {
        config_.maxBatchSize = (int32_t)ctx_params.n_batch;
    }

    max_sessions_ = 0;
    conv_to_seq_.clear();
    seq_to_conv_.clear();
    seq_tokens_.clear();
    conv_to_swap_path_.clear();
    seq_kv_loaded_.clear();
    lru_.clear();
    if (config_.enableCache && config_.cacheSize > 0) {
        max_sessions_ = config_.cacheSize;
    }

    uint32_t n_seq_max = max_sessions_ > 0
        ? (uint32_t)(max_sessions_ + 1)
        : 1;
    n_seq_max = (std::min)(n_seq_max, (uint32_t)128);
    uint32_t max_seq_by_batch = ctx_params.n_batch > 0
        ? (std::max)((uint32_t)1, ctx_params.n_ctx / ctx_params.n_batch)
        : 1;
    n_seq_max = (std::max)((uint32_t)1, (std::min)(n_seq_max, max_seq_by_batch));
    if (max_sessions_ > 0) {
        const int32_t allowed_sessions = (int32_t)n_seq_max - 1;
        if ((int32_t)max_sessions_ > allowed_sessions) {
            max_sessions_ = (size_t)(std::max)(allowed_sessions, 0);
        }
    }
    ctx_params.n_seq_max = n_seq_max;

    ctx_ = llama_init_from_model(model_, ctx_params);
    if (!ctx_) {
        std::cerr << "Failed to create llama context" << std::endl;
        llama_model_free(model_);
        model_ = nullptr;
        return false;
    }

    if (!config_.draftModelPath.empty()) {
        std::cout << "Loading draft model from: " << config_.draftModelPath << std::endl;
        llama_model_params draft_params = llama_model_default_params();
        draft_params.n_gpu_layers = config_.draftGpuDeviceId >= 0 ? 999 : 0;
        draft_params.main_gpu = config_.draftGpuDeviceId >= 0
            ? config_.draftGpuDeviceId
            : 0;

        draft_model_ = llama_model_load_from_file(
            config_.draftModelPath.c_str(), draft_params);
        if (draft_model_) {
            llama_context_params draft_ctx_params = llama_context_default_params();
            draft_ctx_params.n_ctx = config_.draftContextSize > 0
                ? (uint32_t)config_.draftContextSize
                : 512;
            draft_ctx_params.n_batch = config_.maxBatchSize > 0
                ? (uint32_t)config_.maxBatchSize
                : 512;
            draft_ctx_params.n_seq_max = 1;

            draft_ctx_ = llama_init_from_model(draft_model_, draft_ctx_params);
            if (!draft_ctx_) {
                std::cerr << "Failed to create draft context" << std::endl;
                llama_model_free(draft_model_);
                draft_model_ = nullptr;
            } else {
                std::cout << "Draft model loaded successfully." << std::endl;
            }
        } else {
            std::cerr << "Failed to load draft model: "
                      << config_.draftModelPath << std::endl;
        }
    }

    ready_ = true;
    std::cout << "Llama model loaded successfully." << std::endl;
    return true;
}

void LlamaCppModel::shutdown() {
    if (ctx_) {
        llama_free(ctx_);
        ctx_ = nullptr;
    }
    if (model_) {
        llama_model_free(model_);
        model_ = nullptr;
    }
    if (draft_ctx_) {
        llama_free(draft_ctx_);
        draft_ctx_ = nullptr;
    }
    if (draft_model_) {
        llama_model_free(draft_model_);
        draft_model_ = nullptr;
    }

    ready_ = false;
    max_sessions_ = 0;
    conv_to_seq_.clear();
    seq_to_conv_.clear();
    seq_tokens_.clear();
    conv_to_swap_path_.clear();
    seq_kv_loaded_.clear();
    lru_.clear();
}

std::string LlamaCppModel::getModelInfo() const {
    char buf[128];
    llama_model_desc(model_, buf, sizeof(buf));
    return std::string("LlamaCppModel: ") + buf;
}

size_t LlamaCppModel::getMemoryUsage() const {
    return llama_model_size(model_);
}

bool LlamaCppModel::isReady() const {
    return ready_;
}

}  // namespace ai_scheduler
