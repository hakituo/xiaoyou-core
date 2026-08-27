#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <shared_mutex>
#include <cmath>
#include <algorithm>
#include <iostream>
#include <numeric>
#include <omp.h>

// Explicit AVX2 intrinsics for guaranteed vectorization
#ifdef __AVX2__
#include <immintrin.h>
#define USE_AVX2 1
#else
#define USE_AVX2 0
#endif

namespace ai_memory {

struct MemoryRecord {
    std::string id;
    std::vector<float> embedding;
    float norm;       // Pre-computed L2 norm of embedding
    float weight;
    float timestamp;
    std::string source;
    std::vector<std::string> topics;
};

struct SearchResult {
    std::string id;
    float similarity;
    float final_score;
};

class VectorIndexer {
public:
    VectorIndexer() = default;
    
    void addRecord(const std::string& id, const std::vector<float>& embedding, float weight, float timestamp, const std::string& source, const std::vector<std::string>& topics) {
        // Pre-compute L2 norm at insertion time
        float norm = computeNorm(embedding);
        
        std::unique_lock<std::shared_mutex> lock(rw_mutex_);
        
        // Check if record already exists (update case)
        auto it = id_to_index_.find(id);
        if (it != id_to_index_.end()) {
            size_t idx = it->second;
            // Remove old source/topic from inverted indices
            removeFromInvertedIndices(idx);
            // Update flat storage
            flat_records_[idx] = {id, embedding, norm, weight, timestamp, source, topics};
            // Add new source/topic to inverted indices
            addToInvertedIndices(idx);
            return;
        }
        
        // New record: append to flat storage
        size_t new_idx = flat_records_.size();
        flat_records_.push_back({id, embedding, norm, weight, timestamp, source, topics});
        id_to_index_[id] = new_idx;
        alive_.push_back(true);
        addToInvertedIndices(new_idx);
    }
    
    void removeRecord(const std::string& id) {
        std::unique_lock<std::shared_mutex> lock(rw_mutex_);
        auto it = id_to_index_.find(id);
        if (it == id_to_index_.end()) return;
        
        size_t idx = it->second;
        removeFromInvertedIndices(idx);
        alive_[idx] = false;
        id_to_index_.erase(it);
    }
    
    void clear() {
        std::unique_lock<std::shared_mutex> lock(rw_mutex_);
        flat_records_.clear();
        alive_.clear();
        id_to_index_.clear();
        source_index_.clear();
        topic_index_.clear();
    }
    
    // Perform search with weight decay
    // weighted_score = (normalized_weight * 0.4) + (similarity * 0.6)
    std::vector<SearchResult> search(
        const std::vector<float>& query_embedding,
        int top_k,
        float min_similarity,
        float current_time,
        float decay_rate,
        float base_min_weight,
        float absolute_min_weight,
        const std::string& filter_source,
        const std::vector<std::string>& filter_topics
    ) {
        std::vector<SearchResult> results;
        
        // Pre-compute query norm
        float query_norm = computeNorm(query_embedding);
        if (query_norm == 0.0f) return results;
        
        std::shared_lock<std::shared_mutex> read_lock(rw_mutex_);
        
        // Determine candidate set via inverted indices (or full scan if no filters)
        std::vector<size_t> candidates;
        
        if (!filter_source.empty() || !filter_topics.empty()) {
            // Use inverted indices to narrow candidates
            std::unordered_set<size_t> candidate_set;
            
            if (!filter_source.empty()) {
                auto src_it = source_index_.find(filter_source);
                if (src_it != source_index_.end()) {
                    for (size_t idx : src_it->second) {
                        if (alive_[idx]) candidate_set.insert(idx);
                    }
                }
            }
            
            if (!filter_topics.empty()) {
                // Intersect: candidate must match source AND at least one topic
                std::unordered_set<size_t> topic_candidates;
                bool first_topic = true;
                for (const auto& ft : filter_topics) {
                    auto topic_it = topic_index_.find(ft);
                    if (topic_it != topic_index_.end()) {
                        for (size_t idx : topic_it->second) {
                            if (alive_[idx] && (filter_source.empty() || candidate_set.count(idx))) {
                                topic_candidates.insert(idx);
                            }
                        }
                        if (first_topic && filter_source.empty()) {
                            // If no source filter, first topic seeds the set
                            for (size_t idx : topic_it->second) {
                                if (alive_[idx]) topic_candidates.insert(idx);
                            }
                            first_topic = false;
                        }
                    }
                }
                if (!filter_source.empty()) {
                    // Must match both source and topic
                    candidates.assign(topic_candidates.begin(), topic_candidates.end());
                } else {
                    candidates.assign(topic_candidates.begin(), topic_candidates.end());
                }
            } else {
                // Only source filter
                candidates.assign(candidate_set.begin(), candidate_set.end());
            }
        } else {
            // No filters: scan all alive records
            candidates.reserve(flat_records_.size());
            for (size_t i = 0; i < alive_.size(); ++i) {
                if (alive_[i]) candidates.push_back(i);
            }
        }
        
        // Parallel search using OpenMP & AVX2
        #pragma omp parallel
        {
            std::vector<SearchResult> local_results;
            
            #pragma omp for nowait
            for (int i = 0; i < static_cast<int>(candidates.size()); ++i) {
                const auto& rec = flat_records_[candidates[i]];
                
                // Weight filter
                if (rec.weight < absolute_min_weight) continue;
                
                // Similarity using pre-computed norms (saves ~40% FLOPs)
                float sim = cosineSimilarityWithNorm(query_embedding, rec.embedding, query_norm, rec.norm);
                if (sim < min_similarity) continue;
                
                // Time decay
                float hours_passed = (current_time - rec.timestamp) / 3600.0f;
                float days_passed = hours_passed / 24.0f;
                float decay_factor = std::pow(decay_rate, days_passed);
                
                float current_weight = rec.weight * decay_factor;
                current_weight = std::max(current_weight, base_min_weight * 0.1f);
                
                float normalized_weight = std::min(current_weight / 20.0f, 1.0f);
                float final_score = (normalized_weight * 0.4f) + (sim * 0.6f);
                
                local_results.push_back({rec.id, sim, final_score});
            }
            
            #pragma omp critical
            {
                results.insert(results.end(), local_results.begin(), local_results.end());
            }
        }
        
        // Sort by final_score descending
        std::sort(results.begin(), results.end(), [](const SearchResult& a, const SearchResult& b) {
            return a.final_score > b.final_score;
        });
        
        if (results.size() > static_cast<size_t>(top_k)) {
            results.resize(top_k);
        }
        
        return results;
    }

private:
    std::shared_mutex rw_mutex_;
    
    // Flat contiguous storage for cache-friendly iteration
    std::vector<MemoryRecord> flat_records_;
    std::vector<bool> alive_;  // Mark deleted records (lazy deletion)
    std::unordered_map<std::string, size_t> id_to_index_;
    
    // Inverted indices for fast source/topic filtering
    std::unordered_map<std::string, std::vector<size_t>> source_index_;
    std::unordered_map<std::string, std::vector<size_t>> topic_index_;
    
    void addToInvertedIndices(size_t idx) {
        const auto& rec = flat_records_[idx];
        if (!rec.source.empty()) {
            source_index_[rec.source].push_back(idx);
        }
        for (const auto& topic : rec.topics) {
            topic_index_[topic].push_back(idx);
        }
    }
    
    void removeFromInvertedIndices(size_t idx) {
        const auto& rec = flat_records_[idx];
        if (!rec.source.empty()) {
            auto it = source_index_.find(rec.source);
            if (it != source_index_.end()) {
                auto& vec = it->second;
                vec.erase(std::remove(vec.begin(), vec.end(), idx), vec.end());
            }
        }
        for (const auto& topic : rec.topics) {
            auto it = topic_index_.find(topic);
            if (it != topic_index_.end()) {
                auto& vec = it->second;
                vec.erase(std::remove(vec.begin(), vec.end(), idx), vec.end());
            }
        }
    }
    
    // Compute L2 norm of a vector
    static float computeNorm(const std::vector<float>& v) {
        if (v.empty()) return 0.0f;
        float sum = 0.0f;
#if USE_AVX2
        __m256 acc = _mm256_setzero_ps();
        int i = 0;
        int n = static_cast<int>(v.size());
        for (; i <= n - 8; i += 8) {
            __m256 val = _mm256_loadu_ps(&v[i]);
            acc = _mm256_fmadd_ps(val, val, acc);
        }
        // Horizontal sum
        __m128 hi = _mm256_extractf128_ps(acc, 1);
        __m128 lo = _mm256_castps256_ps128(acc);
        __m128 sum128 = _mm_add_ps(hi, lo);
        sum128 = _mm_hadd_ps(sum128, sum128);
        sum128 = _mm_hadd_ps(sum128, sum128);
        sum = _mm_cvtss_f32(sum128);
        // Handle remaining elements
        for (; i < n; ++i) {
            sum += v[i] * v[i];
        }
#else
        #pragma omp simd reduction(+:sum)
        for (int i = 0; i < static_cast<int>(v.size()); ++i) {
            sum += v[i] * v[i];
        }
#endif
        return std::sqrt(sum);
    }
    
    // Cosine similarity using pre-computed norms (avoids redundant norm computation)
    float cosineSimilarityWithNorm(const std::vector<float>& a, const std::vector<float>& b, float norm_a, float norm_b) const {
        if (a.empty() || a.size() != b.size() || norm_a == 0.0f || norm_b == 0.0f) return 0.0f;
        
        float dot = 0.0f;
#if USE_AVX2
        __m256 dot_acc = _mm256_setzero_ps();
        int i = 0;
        int n = static_cast<int>(a.size());
        for (; i <= n - 8; i += 8) {
            __m256 va = _mm256_loadu_ps(&a[i]);
            __m256 vb = _mm256_loadu_ps(&b[i]);
            dot_acc = _mm256_fmadd_ps(va, vb, dot_acc);
        }
        // Horizontal sum
        __m128 hi = _mm256_extractf128_ps(dot_acc, 1);
        __m128 lo = _mm256_castps256_ps128(dot_acc);
        __m128 sum128 = _mm_add_ps(hi, lo);
        sum128 = _mm_hadd_ps(sum128, sum128);
        sum128 = _mm_hadd_ps(sum128, sum128);
        dot = _mm_cvtss_f32(sum128);
        // Handle remaining elements
        for (; i < n; ++i) {
            dot += a[i] * b[i];
        }
#else
        #pragma omp simd reduction(+:dot)
        for (int i = 0; i < static_cast<int>(a.size()); ++i) {
            dot += a[i] * b[i];
        }
#endif
        return dot / (norm_a * norm_b);
    }
};

} // namespace ai_memory
