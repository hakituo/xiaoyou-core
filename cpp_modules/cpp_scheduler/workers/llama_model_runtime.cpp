#include "llama_model_impl.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <future>
#include <iostream>
#include <random>
#include <thread>

#include "llama.h"

namespace ai_scheduler {

int LlamaCppModel::decodeWithTimeout(
    llama_context* context,
    llama_batch& batch,
    int timeoutMs,
    const std::function<bool()>& shouldStop
) {
    std::promise<int> result_promise;
    std::future<int> result_future = result_promise.get_future();
    std::thread decode_thread([&]() {
        result_promise.set_value(llama_decode(context, batch));
    });

    const auto status = result_future.wait_for(
        std::chrono::milliseconds(timeoutMs));
    if (status == std::future_status::timeout) {
        std::cerr << "llama_decode超时（" << timeoutMs
                  << "ms），GPU可能卡死" << std::endl;
        decode_thread.detach();
        return shouldStop && shouldStop() ? -2 : -1;
    }

    decode_thread.join();
    return result_future.get();
}

void LlamaCppModel::clearBatch(llama_batch& batch) {
    batch.n_tokens = 0;
}

void LlamaCppModel::addBatchToken(
    llama_batch& batch,
    llama_token token,
    llama_pos position,
    const std::vector<llama_seq_id>& sequenceIds,
    bool logits
) {
    batch.token[batch.n_tokens] = token;
    batch.pos[batch.n_tokens] = position;
    batch.n_seq_id[batch.n_tokens] = (int32_t)sequenceIds.size();
    for (size_t index = 0; index < sequenceIds.size(); ++index) {
        batch.seq_id[batch.n_tokens][index] = sequenceIds[index];
    }
    batch.logits[batch.n_tokens] = logits ? 1 : 0;
    ++batch.n_tokens;
}

llama_token LlamaCppModel::sampleToken(
    const float* logits,
    int vocabularySize,
    int topK,
    float topP,
    float temperature
) {
    if (!logits || vocabularySize <= 0) {
        return 0;
    }
    if (temperature <= 0.0f) {
        int best = 0;
        for (int index = 1; index < vocabularySize; ++index) {
            if (logits[index] > logits[best]) {
                best = index;
            }
        }
        return (llama_token)best;
    }

    int selected_top_k = topK > 0 ? topK : 40;
    selected_top_k = (std::min)(selected_top_k, vocabularySize);
    const float selected_top_p = (std::min)(topP > 0.0f ? topP : 1.0f, 1.0f);

    std::vector<int> indices(vocabularySize);
    for (int index = 0; index < vocabularySize; ++index) {
        indices[index] = index;
    }
    if (selected_top_k < vocabularySize) {
        std::nth_element(
            indices.begin(),
            indices.begin() + selected_top_k,
            indices.end(),
            [logits](int left, int right) {
                return logits[left] > logits[right];
            });
    }
    indices.resize(selected_top_k);
    std::sort(
        indices.begin(),
        indices.end(),
        [logits](int left, int right) { return logits[left] > logits[right]; });

    const float max_logit = logits[indices.front()] / temperature;
    std::vector<float> probabilities;
    probabilities.reserve(indices.size());
    float sum = 0.0f;
    for (const int token : indices) {
        const float probability = std::exp(
            logits[token] / temperature - max_logit);
        probabilities.push_back(probability);
        sum += probability;
    }
    if (sum <= 0.0f) {
        return (llama_token)indices.front();
    }
    for (float& probability : probabilities) {
        probability /= sum;
    }

    if (selected_top_p < 1.0f) {
        float cumulative = 0.0f;
        size_t keep = 0;
        for (const float probability : probabilities) {
            cumulative += probability;
            ++keep;
            if (cumulative >= selected_top_p) {
                break;
            }
        }
        probabilities.resize(keep);
        indices.resize(keep);
    }

    std::random_device random_device;
    std::mt19937 generator(random_device());
    std::discrete_distribution<> distribution(
        probabilities.begin(), probabilities.end());
    return (llama_token)indices[distribution(generator)];
}

size_t LlamaCppModel::validUtf8Length(const std::string& text) {
    size_t index = 0;
    size_t last_valid = 0;
    while (index < text.size()) {
        const unsigned char value = (unsigned char)text[index];
        size_t length = 1;
        if ((value & 0xE0) == 0xC0) {
            length = 2;
        } else if ((value & 0xF0) == 0xE0) {
            length = 3;
        } else if ((value & 0xF8) == 0xF0) {
            length = 4;
        }
        if (index + length > text.size()) {
            break;
        }
        index += length;
        last_valid = index;
    }
    return last_valid;
}

}  // namespace ai_scheduler
