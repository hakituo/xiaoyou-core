#pragma once
#include "gpu_llm_worker.h"
#include "llama.h"
#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <deque>
#include <cstdint>

// Forward declarations for llama.cpp types
struct llama_model;
struct llama_context;
struct llama_token_data;
struct llama_sampler;
struct llama_batch;

namespace ai_scheduler {

class LlamaCppModel : public ILLMModel {
public:
    LlamaCppModel();
    ~LlamaCppModel() override;

    bool initialize(const LLMModelConfig& config) override;
    void shutdown() override;
    LLMInferenceResponse generate(const LLMInferenceRequest& request) override;
    std::string getModelInfo() const override;
    size_t getMemoryUsage() const override;
    bool isReady() const override;
    bool clearConversationCache(const std::string& conversationId) override;

private:
    // Internal helper methods
    static int decodeWithTimeout(
        llama_context* context,
        llama_batch& batch,
        int timeoutMs,
        const std::function<bool()>& shouldStop
    );
    static void clearBatch(llama_batch& batch);
    static void addBatchToken(
        llama_batch& batch,
        llama_token token,
        llama_pos position,
        const std::vector<llama_seq_id>& sequenceIds,
        bool logits
    );
    static llama_token sampleToken(
        const float* logits,
        int vocabularySize,
        int topK,
        float topP,
        float temperature
    );
    static size_t validUtf8Length(const std::string& text);

    std::vector<int> tokenize(const std::string& text, bool add_bos);
    std::string detokenize(const std::vector<int>& tokens);

    int32_t getSeqId(const std::string& conversationId);
    void touchSeq(int32_t seqId);
    void evictIfNeeded();

    bool loadTokensFromSwap(const std::string& conversationId, std::vector<int>& outTokens);
    bool saveTokensToSwap(const std::string& conversationId, const std::vector<int>& tokens);
    void swapOutConversationIfNeeded(const std::string& conversationId, int32_t seqId);
    bool ensureSeqKvLoaded(llama_seq_id seqId, const std::vector<int>& tokens);
    std::string kvSwapPathForConversation(const std::string& conversationId) const;
    
    // Llama.cpp context
    llama_model* model_ = nullptr;
    llama_context* ctx_ = nullptr;
    
    // Draft model for speculative decoding
    llama_model* draft_model_ = nullptr;
    llama_context* draft_ctx_ = nullptr;

    // llama_sampler* sampler_ = nullptr; // Removed for compatibility with older llama.cpp
    
    // Configuration
    LLMModelConfig config_;
    bool ready_ = false;

    size_t max_sessions_ = 0;
    std::unordered_map<std::string, int32_t> conv_to_seq_;
    std::unordered_map<int32_t, std::string> seq_to_conv_;
    std::unordered_map<int32_t, std::vector<int>> seq_tokens_;
    std::unordered_map<std::string, std::string> conv_to_swap_path_;
    std::unordered_map<int32_t, bool> seq_kv_loaded_;
    std::deque<int32_t> lru_;
    
    // Buffers
    std::vector<int> prompt_tokens_;
    std::vector<int> generated_tokens_;
};

} // namespace ai_scheduler
