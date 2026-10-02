#include "llama_model_impl.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>

#include "llama.h"

namespace ai_scheduler {

std::string LlamaCppModel::kvSwapPathForConversation(
    const std::string& conversationId
) const {
    const std::string base = config_.kvSwapDir;
    if (base.empty()) {
        return std::string();
    }
    std::filesystem::path path(base);
    std::string safe = conversationId;
    for (char& value : safe) {
        if ((value >= 'a' && value <= 'z')
            || (value >= 'A' && value <= 'Z')
            || (value >= '0' && value <= '9')
            || value == '-'
            || value == '_') {
            continue;
        }
        value = '_';
    }
    path /= safe + ".kvswap";
    return path.string();
}

bool LlamaCppModel::saveTokensToSwap(
    const std::string& conversationId,
    const std::vector<int>& tokens
) {
    if (!config_.enableKvSwap || tokens.empty()) {
        return false;
    }
    const std::string path = kvSwapPathForConversation(conversationId);
    if (path.empty()) {
        return false;
    }
    try {
        std::filesystem::create_directories(
            std::filesystem::path(path).parent_path());
    } catch (...) {
        return false;
    }

    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        return false;
    }
    const uint32_t count = (uint32_t)tokens.size();
    output.write(reinterpret_cast<const char*>(&count), sizeof(uint32_t));
    output.write(
        reinterpret_cast<const char*>(tokens.data()),
        sizeof(int) * tokens.size());
    if (!output.good()) {
        return false;
    }
    output.close();
    conv_to_swap_path_[conversationId] = path;
    return true;
}

bool LlamaCppModel::loadTokensFromSwap(
    const std::string& conversationId,
    std::vector<int>& outTokens
) {
    if (!config_.enableKvSwap) {
        return false;
    }
    const auto path_it = conv_to_swap_path_.find(conversationId);
    const std::string path = path_it != conv_to_swap_path_.end()
        ? path_it->second
        : kvSwapPathForConversation(conversationId);
    if (path.empty()) {
        return false;
    }

    std::ifstream input(path, std::ios::binary);
    if (!input.is_open()) {
        return false;
    }
    uint32_t count = 0;
    input.read(reinterpret_cast<char*>(&count), sizeof(uint32_t));
    if (!input.good() || count == 0) {
        return false;
    }
    outTokens.resize((size_t)count);
    input.read(
        reinterpret_cast<char*>(outTokens.data()),
        sizeof(int) * outTokens.size());
    if (!input.good()) {
        outTokens.clear();
        return false;
    }
    conv_to_swap_path_[conversationId] = path;
    return true;
}

void LlamaCppModel::swapOutConversationIfNeeded(
    const std::string& conversationId,
    int32_t seqId
) {
    if (!config_.enableKvSwap || conversationId.empty() || !ctx_) {
        return;
    }
    auto tokens_it = seq_tokens_.find(seqId);
    if (tokens_it == seq_tokens_.end()) {
        return;
    }
    const size_t trigger = config_.kvSwapTriggerTokens > 0
        ? config_.kvSwapTriggerTokens
        : 2048;
    if (tokens_it->second.size() < trigger
        || !saveTokensToSwap(conversationId, tokens_it->second)) {
        return;
    }
    llama_memory_seq_rm(
        llama_get_memory(ctx_), (llama_seq_id)seqId, 0, -1);
    tokens_it->second.clear();
    tokens_it->second.shrink_to_fit();
    seq_kv_loaded_[seqId] = false;
}

bool LlamaCppModel::clearConversationCache(const std::string& conversationId) {
    if (conversationId.empty()) {
        return false;
    }

    auto conversation_it = conv_to_seq_.find(conversationId);
    if (conversation_it != conv_to_seq_.end()) {
        const int32_t seq_id = conversation_it->second;
        if (ctx_ && !llama_memory_seq_rm(
                llama_get_memory(ctx_), (llama_seq_id)seq_id, 0, -1)) {
            return false;
        }
        if (draft_ctx_) {
            llama_memory_seq_rm(llama_get_memory(draft_ctx_), 0, 0, -1);
        }

        conv_to_seq_.erase(conversation_it);
        seq_to_conv_.erase(seq_id);
        seq_tokens_.erase(seq_id);
        seq_kv_loaded_.erase(seq_id);
        lru_.erase(std::remove(lru_.begin(), lru_.end(), seq_id), lru_.end());
    }

    std::error_code remove_error;
    const auto swap_it = conv_to_swap_path_.find(conversationId);
    const std::string swap_path = swap_it != conv_to_swap_path_.end()
        ? swap_it->second
        : kvSwapPathForConversation(conversationId);
    if (!swap_path.empty()) {
        std::filesystem::remove(swap_path, remove_error);
    }
    conv_to_swap_path_.erase(conversationId);
    return true;
}

int32_t LlamaCppModel::getSeqId(const std::string& conversationId) {
    const auto existing = conv_to_seq_.find(conversationId);
    if (existing != conv_to_seq_.end()) {
        return existing->second;
    }

    while (max_sessions_ > 0
           && conv_to_seq_.size() >= max_sessions_
           && !lru_.empty()) {
        const int32_t evict_id = lru_.front();
        lru_.pop_front();
        const auto conversation_it = seq_to_conv_.find(evict_id);
        if (conversation_it != seq_to_conv_.end()) {
            const std::string evict_conversation = conversation_it->second;
            const auto tokens_it = seq_tokens_.find(evict_id);
            if (tokens_it != seq_tokens_.end()) {
                saveTokensToSwap(evict_conversation, tokens_it->second);
            }
            conv_to_seq_.erase(evict_conversation);
            seq_to_conv_.erase(conversation_it);
        }
        seq_tokens_.erase(evict_id);
        seq_kv_loaded_.erase(evict_id);
        if (ctx_) {
            llama_memory_seq_rm(
                llama_get_memory(ctx_), (llama_seq_id)evict_id, 0, -1);
        }
    }

    int32_t max_sequence = (int32_t)llama_n_seq_max(ctx_);
    if (max_sequence <= 0) {
        max_sequence = 1;
    }
    int32_t sequence = -1;
    for (int32_t candidate = 0; candidate < max_sequence; ++candidate) {
        if (seq_to_conv_.find(candidate) == seq_to_conv_.end()) {
            sequence = candidate;
            break;
        }
    }
    if (sequence == -1) {
        sequence = 0;
    }

    conv_to_seq_[conversationId] = sequence;
    seq_to_conv_[sequence] = conversationId;
    lru_.push_back(sequence);
    seq_kv_loaded_[sequence] = false;
    return sequence;
}

void LlamaCppModel::touchSeq(int32_t seqId) {
    lru_.erase(std::remove(lru_.begin(), lru_.end(), seqId), lru_.end());
    lru_.push_back(seqId);
}

void LlamaCppModel::evictIfNeeded() {
    while (max_sessions_ > 0
           && conv_to_seq_.size() > max_sessions_
           && !lru_.empty()) {
        const int32_t evict_id = lru_.front();
        lru_.pop_front();
        const auto conversation_it = seq_to_conv_.find(evict_id);
        if (conversation_it != seq_to_conv_.end()) {
            const std::string evict_conversation = conversation_it->second;
            const auto tokens_it = seq_tokens_.find(evict_id);
            if (tokens_it != seq_tokens_.end()) {
                saveTokensToSwap(evict_conversation, tokens_it->second);
            }
            conv_to_seq_.erase(evict_conversation);
            seq_to_conv_.erase(conversation_it);
        }
        seq_tokens_.erase(evict_id);
        seq_kv_loaded_.erase(evict_id);
        if (ctx_) {
            llama_memory_seq_rm(
                llama_get_memory(ctx_), (llama_seq_id)evict_id, 0, -1);
        }
    }
}

bool LlamaCppModel::ensureSeqKvLoaded(llama_seq_id seqId, const std::vector<int>& tokens) {
    if (!ctx_) {
        return false;
    }
    auto it = seq_kv_loaded_.find((int32_t)seqId);
    const bool already = (it != seq_kv_loaded_.end() && it->second);
    if (already) {
        return true;
    }
    if (tokens.empty()) {
        seq_kv_loaded_[(int32_t)seqId] = true;
        return true;
    }

    llama_memory_seq_rm(llama_get_memory(ctx_), seqId, 0, -1);
    const int config_batch_size = (int)(config_.maxBatchSize > 0 ? config_.maxBatchSize : 512);
    int ctx_size = llama_n_ctx(ctx_);
    if (ctx_size <= 0) {
        ctx_size = (int)(config_.maxContextSize > 0 ? config_.maxContextSize : 4096);
    }
    int seq_max = llama_n_seq_max(ctx_);
    if (seq_max <= 0) {
        seq_max = 1;
    }
    int slot_size = ctx_size / seq_max;
    if (slot_size < 1) {
        slot_size = 1;
    }
    if (config_.enableCache && config_.cacheSize > 0) {
        int cache_seq_limit = (int)config_.cacheSize + 1;
        if (cache_seq_limit < 1) {
            cache_seq_limit = 1;
        }
        int cache_slot_size = ctx_size / cache_seq_limit;
        if (cache_slot_size > 0 && cache_slot_size < slot_size) {
            slot_size = cache_slot_size;
        }
    }
    if (slot_size > 0) {
        int max_tokens_in_slot = slot_size - 1;
        if (max_tokens_in_slot < 1) {
            return false;
        }
        if (tokens.size() > (size_t)max_tokens_in_slot) {
            return false;
        }
    }
    int batch_size = config_batch_size;
    if (slot_size > 0) {
        int safe_limit = slot_size - 1;
        int half_ctx = ctx_size > 1 ? (ctx_size / 2) : 1;
        if (half_ctx < 1) {
            half_ctx = 1;
        }
        if (safe_limit > half_ctx) {
            safe_limit = half_ctx;
        }
        if (safe_limit < 1) {
            safe_limit = 1;
        }
        if (batch_size > safe_limit) {
            batch_size = safe_limit;
        }
    }
    if (batch_size < 1) {
        batch_size = 1;
    }
    llama_batch batch = llama_batch_init(batch_size, 0, 1);

    for (size_t i = 0; i < tokens.size();) {
        clearBatch(batch);
        const size_t remaining = tokens.size() - i;
        int slot_remaining = slot_size - (int)i - 1;
        if (slot_remaining < 1) {
            llama_batch_free(batch);
            return false;
        }
        size_t chunk = remaining;
        if (chunk > (size_t)batch_size) {
            chunk = (size_t)batch_size;
        }
        if (chunk > (size_t)slot_remaining) {
            chunk = (size_t)slot_remaining;
        }
        for (size_t j = 0; j < chunk; j++) {
            const size_t pos = i + j;
            addBatchToken(batch, (llama_token)tokens[pos], (llama_pos)pos, { seqId }, false);
        }
        if (i + chunk == tokens.size() && batch.n_tokens > 0) {
            batch.logits[batch.n_tokens - 1] = true;
        }
        int decode_result = decodeWithTimeout(ctx_, batch, 30000, nullptr);
        if (decode_result != 0) {
            llama_batch_free(batch);
            if (decode_result == -1) {
                std::cerr << "ensureSeqKvLoaded: llama_decode超时" << std::endl;
            }
            return false;
        }
        i += chunk;
    }
    llama_batch_free(batch);
    seq_kv_loaded_[(int32_t)seqId] = true;
    return true;
}

}  // namespace ai_scheduler

