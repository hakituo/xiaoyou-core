#include "llama_model_impl.h"
#include <iostream>
#include <algorithm>
#include <thread>
#include <cstring>
#include <cmath>
#include <random>
#include <vector>
#include <filesystem>
#include <fstream>
#include <future>
#include <chrono>
#include "llama.h"

namespace ai_scheduler {

std::vector<int> LlamaCppModel::tokenize(const std::string& text, bool add_bos) {
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    // Calculate required size
    int n_tokens = text.length() + 2; // approximation
    std::vector<llama_token> tokens(n_tokens);
    
    int32_t n = llama_tokenize(vocab, text.c_str(), (int32_t)text.length(), tokens.data(), (int32_t)tokens.size(), add_bos, false);
    
    if (n < 0) {
        // Resize and try again
        tokens.resize(-n);
        n = llama_tokenize(vocab, text.c_str(), (int32_t)text.length(), tokens.data(), (int32_t)tokens.size(), add_bos, false);
    }
    
    std::vector<int> result;
    if (n > 0) {
        result.reserve(n);
        for (int i = 0; i < n; i++) {
            result.push_back(tokens[i]);
        }
    }
    return result;
}

std::string LlamaCppModel::detokenize(const std::vector<int>& tokens) {
    if (tokens.empty()) return "";
    
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    std::string result;
    for (int token : tokens) {
        char buf[256];
        int n = llama_token_to_piece(vocab, token, buf, sizeof(buf), 0, true);
        if (n < 0) {
            // Buffer too small?
            n = llama_token_to_piece(vocab, token, buf, sizeof(buf), 0, true);
        }
        if (n > 0) {
            result.append(buf, n);
        }
    }
    return result;
}

LLMInferenceResponse LlamaCppModel::generate(const LLMInferenceRequest& request) {
    std::string pending_stream_buffer;
    if (!ready_) {
        return { "", 0, 0.0f, false, "Model not ready" };
    }

    if (request.shouldStop && request.shouldStop()) {
        return { "", 0, 0.0f, false, "Cancelled" };
    }

    auto start_time = std::chrono::high_resolution_clock::now();

    const bool use_cache =
        max_sessions_ > 0 && config_.enableCache && !request.conversationId.empty();

    llama_seq_id seq_id = 0;
    std::vector<int>* cached_tokens = nullptr;
    if (use_cache) {
        int32_t sid = getSeqId(request.conversationId);
        seq_id = (llama_seq_id)sid;
        touchSeq(sid);
        cached_tokens = &seq_tokens_[sid];

        if (config_.enableKvSwap && cached_tokens && cached_tokens->empty()) {
            std::vector<int> restored;
            if (loadTokensFromSwap(request.conversationId, restored)) {
                *cached_tokens = std::move(restored);
                seq_kv_loaded_[sid] = false;
            }
        }
        if (cached_tokens && !cached_tokens->empty()) {
            if (!ensureSeqKvLoaded(seq_id, *cached_tokens)) {
                // If we failed to ensure KV is loaded (e.g. OOM or batch size issues),
                // we must invalidate the cache for this sequence to avoid "Y = X + 1" position errors.
                // The model state might be inconsistent, so we clear it.
                std::cerr << "Warning: ensureSeqKvLoaded failed for seq " << seq_id 
                          << ". Clearing cache and forcing full re-evaluation." << std::endl;
                
                // Remove from VRAM explicitly to be safe
                llama_memory_seq_rm(llama_get_memory(ctx_), seq_id, 0, -1);
                
                // Clear local cache reference so we start with n_past = 0
                cached_tokens->clear();
                seq_kv_loaded_[sid] = false;
            }
        }
    } else {
        seq_id = 0;
        llama_memory_seq_rm(llama_get_memory(ctx_), seq_id, 0, -1);
    }

    prompt_tokens_ = tokenize(request.prompt, true);

    int n_ctx = llama_n_ctx(ctx_);
    int ctx_size = n_ctx > 0 ? n_ctx : (config_.maxContextSize > 0 ? (int)config_.maxContextSize : 4096);
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

    int slot_ctx_limit = ctx_size - 4;
    if (slot_size > 0) {
        int slot_limit = slot_size - 4;
        if (slot_limit < slot_ctx_limit) {
            slot_ctx_limit = slot_limit;
        }
    }
    if (slot_ctx_limit < 1) {
        slot_ctx_limit = 1;
    }
    if ((int)prompt_tokens_.size() > slot_ctx_limit) {
        return { "", 0, 0.0f, false, "Prompt too long for context" };
    }

    const size_t max_tokens = request.maxTokens > 0 ? request.maxTokens : 512;
    const float temperature = request.temperature > 0.0f ? request.temperature : config_.temperature;
    const int top_k = request.topK > 0 ? request.topK : config_.topK;
    const float top_p = request.topP > 0.0f ? request.topP : config_.topP;

    int batch_size = (int)(config_.maxBatchSize > 0 ? config_.maxBatchSize : 512);
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
    
    llama_batch draft_batch = llama_batch_init(batch_size, 0, 1);

    // Draft model check
    bool use_speculative = (draft_ctx_ != nullptr) && (temperature < 0.3f); 
    
    // For speculative, we use a fixed draft count for now
    const int n_draft = 5;

    int n_past = 0;
    if (use_cache && cached_tokens) {
        size_t common = 0;
        const size_t max_common = (std::min)(cached_tokens->size(), prompt_tokens_.size());
        while (common < max_common && (*cached_tokens)[common] == prompt_tokens_[common]) {
            common += 1;
        }
        if (common < cached_tokens->size()) {
            const bool partial_removed = llama_memory_seq_rm(
                llama_get_memory(ctx_), seq_id, (llama_pos)common, -1);
            if (partial_removed) {
                cached_tokens->resize(common);
            } else {
                // M-RoPE 等后端可能不支持局部裁剪；必须整条清空并从 0 重新 prefill。
                llama_memory_seq_rm(llama_get_memory(ctx_), seq_id, 0, -1);
                cached_tokens->clear();
                seq_kv_loaded_[(int32_t)seq_id] = false;
                common = 0;
            }
        }
        n_past = (int)common;
        
        // Draft cache management
        if (use_speculative) {
             // For simplicity, we just clear draft cache on context switch or non-match
             // A real implementation would track draft cache too
             llama_memory_seq_rm(llama_get_memory(draft_ctx_), 0, 0, -1);
        }
    } else {
        if (use_speculative) {
             llama_memory_seq_rm(llama_get_memory(draft_ctx_), 0, 0, -1);
        }
    }

    // Prefill Target Model
    for (size_t i = (size_t)n_past; i < prompt_tokens_.size();) {
        if (request.shouldStop && request.shouldStop()) {
            llama_batch_free(batch);
            llama_batch_free(draft_batch);
            return { "", 0, 0.0f, false, "Cancelled" };
        }
        clearBatch(batch);
        const size_t remaining = prompt_tokens_.size() - i;
        int slot_remaining = slot_size - (int)i - 1;
        if (slot_remaining < 1) {
            llama_batch_free(batch);
            llama_batch_free(draft_batch);
            return { "", 0, 0.0f, false, "Prompt too long for context" };
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
            addBatchToken(batch, (llama_token)prompt_tokens_[pos], (llama_pos)pos, { seq_id }, false);
        }
        if (i + chunk == prompt_tokens_.size() && batch.n_tokens > 0) {
            batch.logits[batch.n_tokens - 1] = true;
        }

        int decode_result = decodeWithTimeout(ctx_, batch, 30000, request.shouldStop);
        if (decode_result != 0) {
            llama_batch_free(batch);
            llama_batch_free(draft_batch);
            if (decode_result == -1) {
                return { "", 0, 0.0f, false, "GPU推理超时（llama_decode卡死）" };
            } else if (decode_result == -2) {
                return { "", 0, 0.0f, false, "Cancelled" };
            }
            return { "", 0, 0.0f, false, "Failed to decode prompt" };
        }
        if (request.shouldStop && request.shouldStop()) {
            llama_batch_free(batch);
            llama_batch_free(draft_batch);
            return { "", 0, 0.0f, false, "Cancelled" };
        }
        
        // Prefill Draft Model
        if (use_speculative) {
             clearBatch(draft_batch);
             for (size_t j = 0; j < chunk; j++) {
                 const size_t pos = i + j; // Draft uses same pos?
                 // Draft model typically uses seq_id 0
                 // Note: Draft context might have different n_past if not synced.
                 // Here we assume we feed same tokens.
                 addBatchToken(draft_batch, (llama_token)prompt_tokens_[pos], (llama_pos)pos, { 0 }, j == chunk - 1);
             }
             if (llama_decode(draft_ctx_, draft_batch) != 0) {
                 use_speculative = false; // Disable if draft fails
             }
        }

        i += chunk;
    }

    int n_cur = (int)prompt_tokens_.size();
    if (use_cache && cached_tokens) {
        cached_tokens->assign(prompt_tokens_.begin(), prompt_tokens_.end());
    }

    int n_decode = 0;
    std::string generated_text;
    std::vector<int> output_tokens;
    
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    const llama_vocab* draft_vocab = use_speculative ? llama_model_get_vocab(draft_model_) : nullptr;

    const size_t max_tokens_by_ctx =
        n_ctx > n_cur + 1 ? (size_t)(n_ctx - n_cur - 1) : (size_t)0;
    const size_t max_tokens_effective = (std::min)(max_tokens, max_tokens_by_ctx);

    // Generation loop
    while ((size_t)n_decode < max_tokens_effective) { 
        if (request.shouldStop && request.shouldStop()) {
            break;
        }

        if (use_speculative) {
            // 1. Generate K draft tokens
            std::vector<llama_token> drafts;
            drafts.reserve(n_draft);
            
            for (int i = 0; i < n_draft; ++i) {
                if (request.shouldStop && request.shouldStop()) {
                    break;
                }
                auto* logits = llama_get_logits(draft_ctx_);
                int n_vocab_draft = llama_vocab_n_tokens(draft_vocab);
                llama_token draft_token = sampleToken(logits, n_vocab_draft, top_k, top_p, temperature);
                
                // Safety check: ensure token is valid for target model if we have it
                int n_vocab_target = llama_vocab_n_tokens(vocab);
                if (draft_token >= n_vocab_target) {
                    // Incompatible vocabulary, stop speculative for this step
                    use_speculative = false;
                    break;
                }

                drafts.push_back(draft_token);
                
                clearBatch(draft_batch);
                addBatchToken(draft_batch, draft_token, n_cur + i, { 0 }, true);
                if (llama_decode(draft_ctx_, draft_batch) != 0) {
                    use_speculative = false;
                    break;
                }
            }
            if (request.shouldStop && request.shouldStop()) {
                break;
            }
            
            if (!use_speculative) continue; // Fallback to normal
            
            // 2. Verify with target model
            clearBatch(batch);
            // Add draft tokens to target batch
            // We need to verify drafts[0]...drafts[K-1]
            // Input to target for drafts[0] is current state (already processed) -> we just need to decode drafts[0] to see if it produces next?
            // Wait, standard speculative:
            // Input to target: [last_token] -> predicts T1
            // We already ran target for last_token.
            // So we need to feed drafts[0] to target, it predicts T2.
            // But we need to check if T1 == drafts[0].
            // We have logits from previous step of target.
            
            // Current state of target: processed up to n_cur-1. Logits available for n_cur.
            auto* logits = llama_get_logits(ctx_);
            int n_vocab_target = llama_vocab_n_tokens(vocab);
            
            // Sample T1 from target logits
            llama_token target_token = sampleToken(logits, n_vocab_target, top_k, top_p, temperature);
            
            std::vector<llama_token> accepted;
            bool mismatched = false;
            
            // Check first token
            if (target_token == drafts[0]) {
                accepted.push_back(target_token);
                // Now we need to verify drafts[1]...
                // We need to run target on drafts[0] to get logits for T2.
                // We can batch this!
                
                // Construct batch: drafts[0], drafts[1], ... drafts[K-1]
                // Their output logits will predict T2, T3...
                
                clearBatch(batch);
                for (size_t i = 0; i < drafts.size(); ++i) {
                     // We input drafts[i] at pos n_cur + i
                     // We want logits for all of them
                     addBatchToken(batch, drafts[i], n_cur + i, { seq_id }, true);
                }
                
                int decode_result = decodeWithTimeout(ctx_, batch, 30000, request.shouldStop);
                if (decode_result != 0) {
                     // Error or timeout
                     if (decode_result == -1) {
                         std::cerr << "Speculative decode: llama_decode超时" << std::endl;
                     }
                     break; 
                }
                
                // Now check results
                for (size_t i = 0; i < drafts.size(); ++i) {
                     if (request.shouldStop && request.shouldStop()) {
                         break;
                     }
                     // Logic:
                     // i=0: Input drafts[0], Output Logits -> Predict T2. Check if T2 == drafts[1].
                     // (If i is last, Predict T_{K+1})
                     
                     // Get logits for the i-th token in batch
                     // In llama_batch, we can find where the logits are.
                     // batch.logits[i] is true, so logits are stored sequentially?
                     // llama_get_logits_ith(ctx, i)
                     
                     float* ith_logits = llama_get_logits_ith(ctx_, (int32_t)i);
                     llama_token next_pred = sampleToken(ith_logits, n_vocab_target, top_k, top_p, temperature);
                     
                     if (i < drafts.size() - 1) {
                         if (next_pred == drafts[i+1]) {
                             accepted.push_back(next_pred);
                         } else {
                             // Mismatch at i+1
                             // drafts[i+1] is wrong. next_pred is the correct one.
                             // We accept up to drafts[i] (which is accepted[i])
                             // And we add next_pred as the corrected token.
                             accepted.push_back(next_pred); // This is the first rejected token corrected
                             mismatched = true;
                             
                             // We need to rollback draft KV to n_cur + i + 1
                             llama_memory_seq_rm(llama_get_memory(draft_ctx_), 0, n_cur + i + 1, -1);
                             // Also need to rollback target KV?
                             // We fed [0...K-1]. 
                             // We accepted 0...i. (i+1 tokens total).
                             // The batch processing added KV for 0...K-1.
                             // We need to remove KV for i+1...K-1.
                             llama_memory_seq_rm(llama_get_memory(ctx_), seq_id, n_cur + i + 1, -1);
                             
                             break;
                         }
                     } else {
                         // Last draft token. next_pred is the extra token!
                         accepted.push_back(next_pred);
                     }
                }
                if (request.shouldStop && request.shouldStop()) {
                    break;
                }
                
            } else {
                // First token mismatch
                accepted.push_back(target_token);
                mismatched = true;
                // Rollback draft
                llama_memory_seq_rm(llama_get_memory(draft_ctx_), 0, n_cur, -1);
                // Target KV is fine (we didn't feed anything yet)
            }
            
            // Process accepted tokens
            for (llama_token t : accepted) {
                output_tokens.push_back(t);
                 char buf[256];
                int n = llama_token_to_piece(vocab, t, buf, sizeof(buf), 0, true);
                if (n > 0) {
                    generated_text.append(buf, n);
                    if (request.streamOutput && request.onTokenGenerated) {
                        pending_stream_buffer.append(buf, n);
                        size_t valid_len = validUtf8Length(pending_stream_buffer);
                        if (valid_len > 0) {
                            request.onTokenGenerated(pending_stream_buffer.substr(0, valid_len));
                            pending_stream_buffer = pending_stream_buffer.substr(valid_len);
                        }
                    }
                }
                
                // Check EOS
                if (llama_vocab_is_eog(vocab, t) || t == llama_vocab_eos(vocab)) {
                    n_decode = max_tokens_effective; // Force break outer
                    break;
                }
            }
            
            n_cur += accepted.size();
            n_decode += accepted.size();
            
            // Prepare for next loop
            // If we ended with mismatch, we already have the corrected token in KV?
            // Wait, if mismatch at first token:
            // We accepted target_token. We need to feed it to target to update logits for next loop.
            // If mismatch later:
            // We accepted drafts[0...i] and next_pred.
            // We fed drafts[0...i]. We did NOT feed next_pred (it was the output of drafts[i]).
            // So we need to feed the LAST accepted token to get logits for next step.
            
            llama_token last_accepted = accepted.back();
            clearBatch(batch);
            addBatchToken(batch, last_accepted, n_cur - 1, { seq_id }, true);
            int decode_result = decodeWithTimeout(ctx_, batch, 30000, request.shouldStop);
            if (decode_result != 0) {
                if (decode_result == -1) {
                    std::cerr << "Speculative decode (sync): llama_decode超时" << std::endl;
                }
                break;
            }
            
            // Sync draft with last accepted
            // Draft KV is at n_cur - 1. We need to feed last_accepted to it.
            clearBatch(draft_batch);
            addBatchToken(draft_batch, last_accepted, n_cur - 1, { 0 }, true);
            llama_decode(draft_ctx_, draft_batch);
            
        } else {
            // Normal decoding
            auto logits = llama_get_logits(ctx_);
            int n_vocab_target = llama_vocab_n_tokens(vocab);

            llama_token new_token_id = sampleToken(logits, n_vocab_target, top_k, top_p, temperature);
            
            if (llama_vocab_is_eog(vocab, new_token_id) || new_token_id == llama_vocab_eos(vocab)) {
                break;
            }

            output_tokens.push_back(new_token_id);
            
            char buf[256];
            int n = llama_token_to_piece(vocab, new_token_id, buf, sizeof(buf), 0, true);
            if (n > 0) {
                generated_text.append(buf, n);
                if (request.streamOutput && request.onTokenGenerated) {
                    pending_stream_buffer.append(buf, n);
                    size_t valid_len = validUtf8Length(pending_stream_buffer);
                    if (valid_len > 0) {
                        request.onTokenGenerated(pending_stream_buffer.substr(0, valid_len));
                        pending_stream_buffer = pending_stream_buffer.substr(valid_len);
                    }
                }
            }

            clearBatch(batch);
            addBatchToken(batch, new_token_id, n_cur, { seq_id }, true);
            
            n_cur++;
            n_decode++;

            int decode_result = decodeWithTimeout(ctx_, batch, 30000, request.shouldStop);
            if (decode_result != 0) {
                if (decode_result == -1) {
                    std::cerr << "Normal decode: llama_decode超时" << std::endl;
                }
                break;
            }
        }
    }

    llama_batch_free(batch);
    llama_batch_free(draft_batch);
    
    auto end_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<float> duration = end_time - start_time;

    if (use_cache && cached_tokens) {
        if (!output_tokens.empty()) {
            cached_tokens->insert(cached_tokens->end(), output_tokens.begin(), output_tokens.end());
        }
        touchSeq((int32_t)seq_id);
        evictIfNeeded();

        swapOutConversationIfNeeded(request.conversationId, (int32_t)seq_id);
    }

    // Ensure generated_text is valid UTF-8 before returning to Python
    {
        size_t valid_len = validUtf8Length(generated_text);
        if (valid_len < generated_text.size()) {
            generated_text.resize(valid_len);
        }
    }

    if (request.shouldStop && request.shouldStop()) {
        return { generated_text, (size_t)n_decode, duration.count(), false, "Cancelled" };
    }

    return { generated_text, (size_t)n_decode, duration.count(), true, "" };
}

} // namespace ai_scheduler
