#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <shared_mutex>
#include <mutex>
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
    
    // 返回 false 表示记录被拒（空向量，或维度与已建立的索引不一致）。
    // 调用方应据此打 warning，而不是让"相似度恒为 0"静默发生。
    bool addRecord(const std::string& id, const std::vector<float>& embedding, float weight, float timestamp, const std::string& source, const std::vector<std::string>& topics) {
        if (embedding.empty()) return false;
        // Pre-compute L2 norm at insertion time（锁外算，避免持锁做 O(dim) 计算）
        float norm = computeNorm(embedding);
        
        std::unique_lock<std::shared_mutex> lock(rw_mutex_);
        if (!acceptDimension(embedding.size())) return false;
        applyRecordLocked(id, embedding, norm, weight, timestamp, source, topics);
        return true;
    }

    // 批量新增/更新：一次取写锁 + 一次维度校验，避免逐条调用反复取锁、
    // 反复维护倒排索引（加载数千条记忆时是主要开销之一）。
    // 返回实际写入（新增 + 更新）的记录数；被拒条数 = 入参条数 - 返回值。
    size_t addRecords(
        const std::vector<std::string>& ids,
        const std::vector<std::vector<float>>& embeddings,
        const std::vector<float>& weights,
        const std::vector<float>& timestamps,
        const std::vector<std::string>& sources,
        const std::vector<std::vector<std::string>>& topics_list
    ) {
        // 各数组长度不一致时按最短截断，绝不越界读
        const size_t count = std::min(
            {ids.size(), embeddings.size(), weights.size(),
             timestamps.size(), sources.size(), topics_list.size()}
        );
        if (count == 0) return 0;

        std::vector<size_t> accepted;
        accepted.reserve(count);
        for (size_t i = 0; i < count; ++i) {
            if (embeddings[i].empty()) continue;
            accepted.push_back(i);
        }
        if (accepted.empty()) return 0;

        // 锁外先算好所有 norm
        std::vector<float> norms(accepted.size());
        for (size_t k = 0; k < accepted.size(); ++k) {
            norms[k] = computeNorm(embeddings[accepted[k]]);
        }

        std::unique_lock<std::shared_mutex> lock(rw_mutex_);
        size_t written = 0;
        for (size_t k = 0; k < accepted.size(); ++k) {
            const size_t i = accepted[k];
            if (!acceptDimension(embeddings[i].size())) continue;
            applyRecordLocked(ids[i], embeddings[i], norms[k], weights[i],
                              timestamps[i], sources[i], topics_list[i]);
            ++written;
        }
        return written;
    }

    // 当前索引已建立的向量维度；0 表示尚未建立
    // 与 search 一致保持非 const：shared_lock 需要非 const 的 mutex
    size_t dimension() {
        std::shared_lock<std::shared_mutex> lock(rw_mutex_);
        return expected_dim_;
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
        expected_dim_ = 0;
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
        
        // 打分逻辑抽成 lambda，串行/并行两条路径复用同一套计算
        auto score_candidate = [&](size_t idx, std::vector<SearchResult>& sink) {
            const auto& rec = flat_records_[idx];
            
            // Weight filter
            if (rec.weight < absolute_min_weight) return;
            
            // Similarity using pre-computed norms (saves ~40% FLOPs)
            float sim = cosineSimilarityWithNorm(query_embedding, rec.embedding, query_norm, rec.norm);
            if (sim < min_similarity) return;
            
            // Time decay
            float hours_passed = (current_time - rec.timestamp) / 3600.0f;
            float days_passed = hours_passed / 24.0f;
            float decay_factor = std::pow(decay_rate, days_passed);
            
            float current_weight = rec.weight * decay_factor;
            current_weight = std::max(current_weight, base_min_weight * 0.1f);
            
            float normalized_weight = std::min(current_weight / 20.0f, 1.0f);
            float final_score = (normalized_weight * 0.4f) + (sim * 0.6f);
            
            sink.push_back({rec.id, sim, final_score});
        };

        // 候选少时 OpenMP 的 fork/join 开销远大于收益：实测 512 维下 1 条候选
        // 0.136ms vs 串行 0.0003ms，1024 条仍打平（0.89x），2048 条起 OMP 才有
        // 1.14x、16384 条 1.41x。因此低于阈值走串行。
        const size_t kParallelThreshold = 2048;
        if (candidates.size() >= kParallelThreshold) {
            // Parallel search using OpenMP & AVX2
            #pragma omp parallel
            {
                std::vector<SearchResult> local_results;
                
                #pragma omp for nowait
                for (int i = 0; i < static_cast<int>(candidates.size()); ++i) {
                    score_candidate(candidates[i], local_results);
                }
                
                #pragma omp critical
                {
                    results.insert(results.end(), local_results.begin(), local_results.end());
                }
            }
        } else {
            results.reserve(candidates.size());
            for (size_t idx : candidates) {
                score_candidate(idx, results);
            }
        }
        
        // 只需要 top_k 条：full sort 的复杂度与 top_k 无关，实测 2 万候选 / top_k=5
        // 从 1.55ms 降到 0.0087ms（约 180x）。top_k 为负或 >= 命中数时退回全排序，
        // 与改动前语义一致。
        const bool need_trim =
            (top_k >= 0) && (results.size() > static_cast<size_t>(top_k));
        if (!need_trim) {
            std::sort(results.begin(), results.end(), [](const SearchResult& a, const SearchResult& b) {
                return a.final_score > b.final_score;
            });
            return results;
        }
        
        const size_t keep = static_cast<size_t>(top_k);
        if (keep == 0) {
            results.clear();
            return results;
        }
        std::partial_sort(
            results.begin(), results.begin() + keep, results.end(),
            [](const SearchResult& a, const SearchResult& b) {
                return a.final_score > b.final_score;
            });
        results.resize(keep);
        
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

    // 已建立的向量维度；0 表示尚未建立。用于拒绝维度不一致的记录——
    // 此前 mismatch 会静默留下一条"相似度恒为 0"的僵尸记录。
    size_t expected_dim_ = 0;

    // 必须在持有写锁时调用
    bool acceptDimension(size_t dim) {
        if (dim == 0) return false;
        if (expected_dim_ == 0) {
            expected_dim_ = dim;
            return true;
        }
        return dim == expected_dim_;
    }

    // 必须在持有写锁时调用（新增或就地更新一条记录）
    void applyRecordLocked(const std::string& id, const std::vector<float>& embedding, float norm, float weight, float timestamp, const std::string& source, const std::vector<std::string>& topics) {
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
