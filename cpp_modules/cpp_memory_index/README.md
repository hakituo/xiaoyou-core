# cpp_memory_index

C++ 高性能向量索引与搜索模块，支持权重衰减、来源/主题过滤和 OpenMP 并行，通过 pybind11 暴露为 Python 模块 `memory_index_py`。

## 功能

- **向量索引管理**：增删查改 embedding 记录，线程安全（读写锁 `shared_mutex`）
- **余弦相似度搜索**：支持 top-k、最低相似度阈值、来源/主题过滤
- **权重衰减**：基于时间差自动衰减记忆权重，公式：`weight × decay_rate^days_passed`
- **综合评分**：`final_score = normalized_weight × 0.4 + similarity × 0.6`
- **OpenMP 并行**：搜索阶段多线程并行计算相似度，SIMD 自动向量化余弦内积

## 架构

```
cpp_memory_index/
├── CMakeLists.txt              # CMake 构建配置（OpenMP + AVX2）
├── setup.py                    # setuptools CMakeExtension 构建（pip installable）
├── core/
│   └── vector_indexer.h        # MemoryRecord / SearchResult / VectorIndexer（header-only）
├── bindings/
│   └── python_bindings.cpp     # pybind11 绑定，暴露为 VectorIndexer + SearchResult
└── dist/                       # 构建产物
```

## 核心 API

### C++ (`ai_memory::VectorIndexer`)

| 方法 | 说明 |
|------|------|
| `addRecord(id, embedding, weight, timestamp, source, topics)` | 添加/更新一条记忆记录 |
| `removeRecord(id)` | 删除记录 |
| `clear()` | 清空所有记录 |
| `search(query_embedding, top_k, min_similarity, current_time, decay_rate, base_min_weight, absolute_min_weight, filter_source, filter_topics)` | 带衰减的向量搜索 |

### Python (`memory_index_py.VectorIndexer`)

```python
import memory_index_py

indexer = memory_index_py.VectorIndexer()

# 添加记录
indexer.addRecord(
    id="mem_001",
    embedding=[0.1, 0.2, 0.3, ...],  # float list
    weight=10.0,
    timestamp=1713800000.0,           # Unix timestamp
    source="chat",
    topics=["学习", "数学"]
)

# 搜索
results = indexer.search(
    query_embedding=[0.1, 0.2, 0.3, ...],
    top_k=5,
    min_similarity=0.5,
    current_time=1713866400.0,
    decay_rate=0.95,
    base_min_weight=1.0,
    absolute_min_weight=0.1,
    filter_source="chat",
    filter_topics=["学习"]
)

for r in results:
    print(f"id={r.id}, similarity={r.similarity:.3f}, final_score={r.final_score:.3f}")
```

## 构建

### 方式一：直接 CMake

```bash
mkdir build && cd build
cmake ..
cmake --build . --config Release
```

### 方式二：pip install（推荐）

```bash
pip install .          # 自动通过 setup.py 调用 CMake 构建
```

## 依赖

- **C++17** 编译器
- **OpenMP**（**必需**，`CMakeLists.txt` 中 `find_package(OpenMP REQUIRED)`）
- **pybind11**（CMake 自动从 GitHub FetchContent 拉取 v2.11.1）
- **CMake ≥ 3.14**
- 编译优化：AVX2 + OpenMP SIMD + 快速浮点（`/arch:AVX2 /O2 /fp:fast /openmp:experimental` on MSVC）

## 性能优化

| 优化项 | 说明 |
|--------|------|
| **预计算向量范数** | `addRecord` 时计算并存储 `norm`，搜索时余弦相似度简化为 `dot / (query_norm × rec.norm)`，减少约 40% 浮点运算 |
| **扁平连续存储** | 使用 `vector<MemoryRecord>` 替代 `unordered_map<string, MemoryRecord>`，连续内存布局大幅提升缓存命中率；另维护 `unordered_map<string, size_t>` 做 ID 索引 |
| **显式 AVX2 内联** | 余弦内积和范数计算使用 `_mm256_fmadd_ps` 显式 AVX2 指令，一次处理 8 个 float，确保向量化不依赖编译器能力；非 AVX2 平台回退到 `#pragma omp simd` |
| **倒排索引过滤** | 维护 `source_index_` / `topic_index_` 倒排索引，有 source/topic 过滤时先缩小候选集再算相似度，避免全量扫描 |
| **延迟删除** | `removeRecord` 使用 `alive_[idx] = false` 标记删除，避免 vector 移动开销 |

## 性能特性

- **读写锁**：搜索使用共享读锁，允许多线程并发搜索；写入使用独占写锁
- **OpenMP 并行搜索**：`#pragma omp parallel for` 并行遍历候选集计算相似度
- **AVX2 显式向量化**：余弦内积和范数计算使用 `_mm256_fmadd_ps` 确保向量化（非 AVX2 回退到 `#pragma omp simd`）
