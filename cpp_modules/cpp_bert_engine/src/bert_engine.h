#pragma once

#include <string>
#include <vector>
#include <unordered_map>
#include <memory>
#include <onnxruntime_cxx_api.h>

#ifdef _WIN32
#include <windows.h>
#endif

namespace xiaoyou {
namespace bert {

class BertTokenizer {
public:
    explicit BertTokenizer(const std::string& vocab_path);
    std::vector<int64_t> tokenize(const std::string& text, int max_length = 128);

private:
    std::unordered_map<std::string, int64_t> vocab_;
    int64_t unk_id_ = 100;
    int64_t cls_id_ = 101;
    int64_t sep_id_ = 102;
    int64_t pad_id_ = 0;
};

class BertEngine {
public:
    BertEngine(const std::string& model_path, const std::string& vocab_path);
    ~BertEngine() = default;

    // Returns a 1D vector containing the probabilities/logits
    std::vector<float> predict(const std::string& text);

private:
    std::unique_ptr<Ort::Env> env_;
    std::unique_ptr<Ort::Session> session_;
    Ort::MemoryInfo memory_info_{nullptr};
    
    std::unique_ptr<BertTokenizer> tokenizer_;

    // Pre-allocated inference buffers (reused across predict() calls)
    std::vector<int64_t> input_ids_;
    std::vector<int64_t> attention_mask_;
    std::vector<int64_t> token_type_ids_;

    // Convert UTF-8 string to wide string (correctly handles Chinese paths on Windows)
    static std::wstring utf8_to_wide(const std::string& utf8_str);
};

} // namespace bert
} // namespace xiaoyou
