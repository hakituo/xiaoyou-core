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

> ⚠️ 本节命令在 Windows + VS 2026 上实测通过（2026-09-17）。踩坑记录见每步下面的「坑」。

### 关键前提：Python 只从 site-packages 加载扩展

运行时是裸 `import memory_index_py`（`memory/weighted_memory_manager.py`），**没有任何 `sys.path` 注入**。
所以编完必须把 `.pyd` 拷进 venv：

```
D:\projects\xiaoyou\venv_core\Lib\site-packages\
```

模块目录下那份 `memory_index_py.cp310-win_amd64.pyd` **不是**加载目标；它只会在你把当前目录设成
工作目录时通过 `sys.path[0]` 抢先命中，导致"明明编了新版本却还是旧行为"。

### 推荐：直接 CMake（离线可用，复用已下载的 pybind11）

```bat
cd /d D:\projects\xiaoyou\cpp_modules\cpp_memory_index

rem 必须用 VS 自带的 CMake：PATH 上的 cmake 3.29 不认识 "Visual Studio 18 2026" 生成器
set CMAKE="C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

%CMAKE% -S . -B build_vs18 -G "Visual Studio 18 2026" -A x64 ^
  -DFETCHCONTENT_SOURCE_DIR_PYBIND11=D:/AI/xiaoyou-core/cpp_modules/cpp_memory_index/build/_deps/pybind11-src ^
  -DPYTHON_EXECUTABLE=D:/AI/xiaoyou-core/venv_core/Scripts/python.exe

%CMAKE% --build build_vs18 --config Release

copy /Y build_vs18\Release\memory_index_py.cp310-win_amd64.pyd ..\..\venv_core\Lib\site-packages\
```

验证（**必须在仓库根目录跑**，否则会被模块目录下那份旧 `.pyd` 遮蔽）：

```bat
cd /d D:\projects\xiaoyou
venv_core\Scripts\python.exe -c "import memory_index_py as m; print(m.__file__); print(hasattr(m.VectorIndexer,'addRecords'), hasattr(m.VectorIndexer,'dimension'))"
```

预期 `... True True`。

#### 坑 1：不要复用仓库里那份 `build/`

`build/CMakeCache.txt` 是模块**还在仓库根目录**（`D:/AI/xiaoyou-core/cpp_memory_index/`）时生成的，
后来模块整体移进 `cpp_modules/`，缓存里的源路径没跟着更新。直接复用会报：

```
CMake Error: The source ".../cpp_modules/cpp_memory_index/CMakeLists.txt" does not match
the source "D:/AI/xiaoyou-core/cpp_memory_index/CMakeLists.txt" used to generate cache.
```

→ **换一个新目录**（如 `build_vs18`）。旧 `build/` 里唯一有价值的是 `_deps/pybind11-src`，
上面用 `-DFETCHCONTENT_SOURCE_DIR_PYBIND11` 指过去，既避开坏缓存又不用联网重新 clone。

#### 坑 2：环境里同时存在 `http_proxy` 和 `HTTP_PROXY` 会让 MSBuild 直接崩

MSBuild 的 `ToolTask` 用 .NET `Hashtable` 装子进程环境变量，而 Hashtable 区分大小写、Windows 环境变量不区分，
于是同名不同大小写的两个变量会撞车：

```
error MSB6001: "CL.exe" 的命令行开关无效。
System.ArgumentException: 已添加项。字典中的关键字:"https_proxy"所添加的关键字:"HTTPS_PROXY"
```

现象是 CMake 报 `The CXX compiler identification is unknown` / `No CMAKE_CXX_COMPILER could be found`，
**看起来像编译器没装，其实是环境变量撞名**。构建前清掉小写那两个即可（只影响当前会话）：

```bat
set http_proxy=
set https_proxy=
```

#### 坑 3：CMake 版本

`Visual Studio 18 2026` 生成器只有 VS 自带的 CMake 4.1.1 认识；PATH 上的 3.29.2 只认到 `Visual Studio 17 2022`，
而且读不了 4.x 写的 `CMakeCache.txt`。要么用上面的全路径，要么改用 `-G "Visual Studio 17 2022"`
（配合 VS 2022 Build Tools，本机 `VC/Tools/MSVC/14.44.35207` 也在）。

### 方式二：pip install（会重新联网拉 pybind11）

```bash
cd D:\projects\xiaoyou
venv_core\Scripts\python.exe -m pip install cpp_modules\cpp_memory_index --no-deps --force-reinstall
```

`setup.py` 的 `build_temp`（`build/temp.win-amd64-cpython-310/`）里没有 `_deps`，
FetchContent 会从 GitHub 重新 clone pybind11 v2.11.1 —— 需要能连 GitHub。
好处是编译完直接装进 venv，省掉手工 copy。


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
