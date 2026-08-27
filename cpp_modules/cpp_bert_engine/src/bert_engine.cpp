#include "bert_engine.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <algorithm>
#include <cctype>

namespace xiaoyou {
namespace bert {

// --- Basic WordPiece Tokenizer for Chinese ---
BertTokenizer::BertTokenizer(const std::string& vocab_path) {
    std::ifstream infile(vocab_path);
    if (!infile.is_open()) {
        throw std::runtime_error("Could not open vocab file: " + vocab_path);
    }
    std::string line;
    int64_t idx = 0;
    while (std::getline(infile, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        vocab_[line] = idx++;
    }
    
    if (vocab_.count("[UNK]")) unk_id_ = vocab_["[UNK]"];
    if (vocab_.count("[CLS]")) cls_id_ = vocab_["[CLS]"];
    if (vocab_.count("[SEP]")) sep_id_ = vocab_["[SEP]"];
    if (vocab_.count("[PAD]")) pad_id_ = vocab_["[PAD]"];
}

// Basic UTF-8 Chinese tokenizer: Splits every Chinese char as a token, keeps English words.
std::vector<int64_t> BertTokenizer::tokenize(const std::string& text, int max_length) {
    std::vector<int64_t> token_ids;
    token_ids.push_back(cls_id_);
    
    // Very simplified UTF-8 iteration (For production, consider a robust utf8 lib)
    for (size_t i = 0; i < text.size(); ) {
        unsigned char c = text[i];
        std::string token;
        int char_len = 1;
        
        if ((c & 0x80) == 0) { char_len = 1; }
        else if ((c & 0xE0) == 0xC0) { char_len = 2; }
        else if ((c & 0xF0) == 0xE0) { char_len = 3; }
        else if ((c & 0xF8) == 0xF0) { char_len = 4; }
        
        token = text.substr(i, char_len);
        // Simple lowercase for ascii
        if (char_len == 1 && std::isalpha(c)) {
            token[0] = std::tolower(c);
        }
        
        if (token != " " && token != "\t" && token != "\n") {
            auto it = vocab_.find(token);
            if (it != vocab_.end()) {
                token_ids.push_back(it->second);
            } else {
                token_ids.push_back(unk_id_);
            }
        }
        
        i += char_len;
        if (token_ids.size() >= max_length - 1) break; // Leave room for [SEP]
    }
    
    token_ids.push_back(sep_id_);
    return token_ids;
}

// --- Bert Engine ---
std::wstring BertEngine::utf8_to_wide(const std::string& utf8_str) {
    if (utf8_str.empty()) return L"";
#ifdef _WIN32
    int len = MultiByteToWideChar(CP_UTF8, 0, utf8_str.c_str(), -1, nullptr, 0);
    if (len <= 0) return L"";
    std::wstring wide(len - 1, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8_str.c_str(), -1, &wide[0], len);
    return wide;
#else
    // On non-Windows, just do a basic conversion (paths are typically ASCII)
    return std::wstring(utf8_str.begin(), utf8_str.end());
#endif
}

BertEngine::BertEngine(const std::string& model_path, const std::string& vocab_path) {
    env_ = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, "XiaoyouBert");
    Ort::SessionOptions session_options;
    session_options.SetIntraOpNumThreads(4);
    session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    
    // Correctly convert UTF-8 path to wide string (handles Chinese characters)
    std::wstring widestr = utf8_to_wide(model_path);
    session_ = std::make_unique<Ort::Session>(*env_, widestr.c_str(), session_options);
    
    tokenizer_ = std::make_unique<BertTokenizer>(vocab_path);
    memory_info_ = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

    // Pre-allocate inference buffers for max sequence length
    input_ids_.resize(128);
    attention_mask_.resize(128);
    token_type_ids_.resize(128);
}

std::vector<float> BertEngine::predict(const std::string& text) {
    auto tokenized = tokenizer_->tokenize(text, 128);
    size_t seq_len = tokenized.size();
    
    // Reuse pre-allocated buffers (avoid heap allocation per call)
    input_ids_.assign(tokenized.begin(), tokenized.end());
    attention_mask_.assign(seq_len, 1);
    token_type_ids_.assign(seq_len, 0);
    
    std::vector<int64_t> input_shape = {1, static_cast<int64_t>(seq_len)};
    
    auto id_tensor = Ort::Value::CreateTensor<int64_t>(
        memory_info_, input_ids_.data(), seq_len, input_shape.data(), input_shape.size());
    auto mask_tensor = Ort::Value::CreateTensor<int64_t>(
        memory_info_, attention_mask_.data(), seq_len, input_shape.data(), input_shape.size());
    auto type_tensor = Ort::Value::CreateTensor<int64_t>(
        memory_info_, token_type_ids_.data(), seq_len, input_shape.data(), input_shape.size());
        
    const char* input_names[] = {"input_ids", "attention_mask", "token_type_ids"};
    Ort::Value input_tensors[] = {std::move(id_tensor), std::move(mask_tensor), std::move(type_tensor)};
    const char* output_names[] = {"logits"}; // Check your ONNX model's exact output name!
    
    auto output_tensors = session_->Run(Ort::RunOptions{nullptr}, 
                                        input_names, input_tensors, 3, 
                                        output_names, 1);
                                        
    float* floatarr = output_tensors[0].GetTensorMutableData<float>();
    size_t out_count = output_tensors[0].GetTensorTypeAndShapeInfo().GetElementCount();
    
    return std::vector<float>(floatarr, floatarr + out_count);
}

} // namespace bert
} // namespace xiaoyou
