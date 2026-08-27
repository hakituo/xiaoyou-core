# Memory System (记忆系统)

## 概述

记忆系统是Xiaoyou-Core系统的核心组件，负责对话上下文、长期记忆的存储、检索和管理。该系统采用权重管理机制，支持向量搜索、关键词索引、记忆蒸馏等高级功能。

## 目录结构

```
memory/
├── core/                           # 核心模块
│   ├── __init__.py
│   ├── analysis_ops.py            # 分析操作
│   ├── async_persistence.py       # 异步持久化（async_safe_json_dump/async_safe_json_load，aiofiles + 回退到 asyncio.to_thread）
│   ├── batch_ops.py               # 批量操作（batch_delete_memories/batch_update_weights/batch_search_memories，单次锁获取）
│   ├── cache_ops.py               # 缓存操作
│   ├── concurrency_optimized.py   # 并发优化（ConcurrentCache 读无锁+写加锁，ThreadSafeCounter，ReadWriteLock 写者优先）
│   ├── discourse.py               # 话语类型分析（INSTRUCTION/QUESTION/HYPOTHETICAL/FUTURE_PLAN/RETROSPECTIVE_SELF_REPORT 等）
│   ├── distillation.py            # 记忆蒸馏
│   ├── history_ops.py             # 历史操作
│   ├── io_ops.py                  # IO操作
│   ├── keyword_index.py           # 关键词索引
│   ├── keyword_ops.py             # 关键词索引辅助与偏好视图
│   ├── lifecycle_ops.py           # 加载/清理/迁移/保存生命周期
│   ├── lock_utils.py              # 共享锁工具（get_read_lock/get_write_lock 上下文管理器，13 子模块统一使用）
│   ├── maintenance_ops.py         # 维护操作
│   ├── manager_init_ops.py        # 布局与管理器基础初始化
│   ├── mutation_ops.py            # 变更操作
│   ├── performance_monitor.py     # 性能监控
│   ├── persistence.py             # 持久化
│   ├── preferences.py             # 偏好管理
│   ├── readable_ops.py            # readable/history 导出与回填
│   ├── recall_probability.py      # 召回概率计算
│   ├── record_ops.py              # 记录规范化/去重/readable 视图
│   ├── retrieval_ops.py           # 检索操作
│   ├── retrieval_ops_optimized.py # 增量主题缓存（TopicWeightCache 增量更新 + needs_rebuild() 定期重建）
│   ├── runtime_ops.py             # auto-save/trim/运行时调度
│   ├── scoring_utils.py           # 统一评分函数（compute_hybrid_score_with_result，统一所有模块的评分逻辑）
│   ├── search.py                  # 搜索核心
│   ├── state_ops.py               # 状态操作
│   ├── storage.py                 # 存储操作
│   ├── taxonomy.py                # 分类管理
│   ├── text_segmenter.py          # 文本分词器（_UNIFIED_STOPWORDS 合并停用词）
│   ├── unified_cache_manager.py   # 统一缓存管理器（UnifiedCacheManager 整合嵌入/查询/记忆 L1-L2/主题缓存）
│   ├── utils.py                   # 工具函数
│   ├── vector_ops.py              # 向量操作
│   └── weights.py                 # 权重计算
├── weighted_memory_manager.py # 记忆管理器主类
├── embedding_generator.py     # 向量嵌入生成
├── nightly/                   # 夜间处理拆分模块
│   ├── config.py              # 夜间处理配置与分析目录
│   ├── user_loader.py         # 睡眠状态检测与用户扫描
│   ├── task_runner.py         # 薄门面：异步桥接与 scope/global 阶段路由
│   ├── distillation_service.py # 蒸馏候选、批量请求与失败回退
│   ├── distillation_codec.py  # 蒸馏 Prompt、响应解析与人物信号规则
│   ├── global_tasks.py        # 每日一次的全局业务编排
│   ├── analysis_service.py    # 夜间分析、权重更新与结果落盘
│   ├── run_state.py           # 按目标日期记录 scope/global 进度，支持断点续跑
│   └── sleep_hooks.py         # nightly 与角色睡眠状态桥接
├── nightly_processor.py       # 夜间处理门面（保留兼容接口）
├── persistent_state.py        # 持久化状态
├── README.md                  # 本文档
├── README_VECTOR_SEARCH.md    # 向量搜索文档
├── enhanced_memory_system_design.md # 系统设计文档
└── vector_search_implementation_plan.md # 向量搜索实现计划
```

### Nightly 编排边界

- `NightlyProcessor` 只负责触发与分阶段编排：每个记忆 scope 仅执行蒸馏；人物档案与日记、计划、数字健康、睡眠标记、核心记忆整理都在每个目标日期的 global 阶段执行一次。
- `run_state.json` 记录已完成 scope 和 global 阶段；进程重启或单 scope 失败时只补跑未完成部分。
- 分析窗口使用 `target_date` 的本地自然日，不使用滚动 24 小时。
- 模型路由以 `config/yaml/sections/model_routing.yaml` 为真源：日记/偏好合并用 `journal_model`，用户计划用 `character_daily_models.plan_generator`，蒸馏/人物档案用 `memory_models.distillation`。LLM 请求保持稳定 system prompt 与动态 user prompt 分离。
- 蒸馏结果同步落盘 `distillation_metadata`（人物线索、Aveline/Ling 角色演化线索）；global 人物提取只放行命中线索的原始聊天批次。若蒸馏与本地零 API 保守规则都无线索，则推进增量水位并以 0 次人物档案 LLM 请求结束。

## 核心组件

### 1. WeightedMemoryManager (权重记忆管理器)

**文件**: `weighted_memory_manager.py`

统一的记忆管理入口，整合所有记忆操作：

```python
class WeightedMemoryManager:
    def __init__(self):
        self.weighted_memories: Dict[str, Dict] = {}
        self.keyword_index: Dict[str, Set[str]] = {}
        self.category_index: Dict[str, List[str]] = {}
        self.lock = threading.RLock()
        
    async def add_memory(
        self,
        content: str,
        category: str = "general",
        weight: float = 1.0,
        metadata: Optional[Dict] = None,
    ) -> str:
        """添加记忆"""
        
    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """搜索记忆"""
        
    async def update_weight(
        self,
        memory_id: str,
        delta: float,
    ) -> bool:
        """更新记忆权重"""
```

**核心功能**:
- 记忆存储与管理
- 权重计算与更新
- 关键词索引
- 分类管理
- 向量搜索

### 2. MemoryWeightCalculator (权重计算器)

**文件**: `core/weights.py`

记忆权重计算器：

```python
class MemoryWeightCalculator:
    def calculate_weight(
        self,
        memory: Dict[str, Any],
        context: Optional[Dict] = None,
    ) -> float:
        """计算记忆权重"""
        
    def decay_weight(
        self,
        current_weight: float,
        elapsed_seconds: float,
    ) -> float:
        """权重衰减"""
```

**权重因子**:
| 因子 | 说明 | 权重 |
|------|------|------|
| 时间衰减 | 越久远的记忆权重越低 | 0.3 |
| 访问频率 | 被引用越多次越重要 | 0.2 |
| 情感强度 | 情感强烈的记忆更重要 | 0.2 |
| 用户反馈 | 用户明确标记的记忆 | 0.15 |
| 关联度 | 与其他记忆的关联 | 0.15 |

### 3. EmbeddingGenerator (向量嵌入生成器)

**文件**: `embedding_generator.py`

向量嵌入生成，支持向量搜索：

```python
class EmbeddingGenerator:
    async def generate_embedding(
        self,
        text: str,
    ) -> Optional[List[float]]:
        """生成文本向量嵌入"""
        
    async def batch_generate(
        self,
        texts: List[str],
    ) -> List[Optional[List[float]]]:
        """批量生成向量嵌入"""
```

**支持模型**:
- text2vec-base-chinese
- bge-large-zh
- 自定义模型

### 4. 检索操作模块

**文件**: `core/retrieval_ops.py`

记忆检索操作：

```python
def search_memories(
    manager: Any,
    query: str,
    limit: int = 10,
    category: Optional[str] = None,
    emotion: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """搜索记忆"""

def search_by_similarity(
    manager: Any,
    query_embedding: List[float],
    limit: int = 10,
    threshold: float = 0.7,
) -> List[Dict[str, Any]]:
    """向量相似度搜索"""

def hybrid_search_memories(
    manager: Any,
    query: str,
    limit: int = 10,
    keyword_weight: float = 0.4,
    vector_weight: float = 0.6,
) -> List[Dict[str, Any]]:
    """混合搜索（关键词 + 向量）"""
```

### 5. 关键词索引模块

**文件**: `core/keyword_index.py`

关键词索引管理：

```python
def rebuild_keyword_index(manager: Any):
    """重建关键词索引"""

def upsert_memory_keywords(
    manager: Any,
    memory_id: str,
    content: str,
):
    """更新记忆关键词"""

def expand_keywords(
    manager: Any,
    keywords: List[str],
    top_k: int = 3,
) -> List[str]:
    """扩展关键词（同义词、相关词）"""
```

### 6. 记忆蒸馏模块

**文件**: `core/distillation.py`

记忆蒸馏与压缩：

```python
def trim_short_term_memory(
    manager: Any,
    max_items: int = 100,
):
    """修剪短期记忆"""

async def distill_memories(
    manager: Any,
    memory_ids: List[str],
) -> Dict[str, Any]:
    """蒸馏多条记忆为摘要"""
```

### 7. 分析操作模块

**文件**: `core/analysis_ops.py`

记忆分析操作：

```python
def count_pending_analysis(manager: Any) -> int:
    """统计待分析记忆数量"""

def get_pending_analysis_items(
    manager: Any,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """获取待分析记忆"""

async def process_pending_analysis(
    manager: Any,
    memory_id: str,
) -> bool:
    """处理待分析记忆"""
```

## 架构设计

### 记忆层次结构

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory System                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Short-term Memory (短期记忆)            │   │
│  │  - 当前对话上下文                                    │   │
│  │  - 最近N条消息                                       │   │
│  │  - 高权重，快速衰减                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Long-term Memory (长期记忆)             │   │
│  │  - 重要事件和偏好                                    │   │
│  │  - 用户画像                                          │   │
│  │  - 低衰减，持久存储                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Episodic Memory (情景记忆)              │   │
│  │  - 特定事件和经历                                    │   │
│  │  - 时间戳标记                                        │   │
│  │  - 情感关联                                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 检索流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Search Query                              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Query Processing                          │
│  - 关键词提取                                              │
│  - 向量嵌入生成                                            │
│  - 查询扩展                                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Keyword     │   │ Vector      │   │ Category    │
│ Search      │   │ Search      │   │ Filter      │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Result Ranking                            │
│  - 权重排序                                                │
│  - 回忆概率过滤                                            │
│  - 多样性优化                                              │
└─────────────────────────────────────────────────────────────┘
```

### 权重衰减曲线

```
权重
1.0 ┤
    │ ╲
0.8 ┤  ╲
    │   ╲
0.6 ┤    ╲
    │     ╲
0.4 ┤      ╲
    │       ╲
0.2 ┤        ╲___
    │            ╲___
0.0 ┤________________╲___
    0   1d  3d  7d  14d  30d  时间
```

## 使用示例

### 添加记忆

```python
from memory.weighted_memory_manager import get_memory_manager

manager = get_memory_manager()

# 添加记忆
memory_id = await manager.add_memory(
    content="用户今天学习了Python的列表推导式",
    category="study",
    weight=1.0,
    metadata={
        "emotion": "happy",
        "importance": "high",
    }
)
```

### 搜索记忆

```python
# 关键词搜索
results = await manager.search_memories(
    query="Python学习",
    limit=10,
    category="study",
)

# 混合搜索
results = await manager.hybrid_search(
    query="最近学了什么",
    limit=5,
    keyword_weight=0.4,
    vector_weight=0.6,
)
```

### 更新权重

```python
# 用户引用记忆时增加权重
await manager.update_weight(
    memory_id="mem_123",
    delta=0.1,  # 增加权重
)

# 时间衰减
await manager.apply_decay()
```

### 获取统计

```python
# 获取分类统计
stats = await manager.get_category_stats()
print(f"总记忆数: {stats['total_memories']}")
print(f"分类分布: {stats['distribution']}")
```

## 配置

### 记忆配置

```python
# config/integrated_config.py
class MemorySettings:
    # 短期记忆最大条数
    short_term_max: int = 100
    
    # 权重衰减率（每天）
    decay_rate: float = 0.1
    
    # 最小权重阈值
    min_weight: float = 0.1
    
    # 向量搜索阈值
    similarity_threshold: float = 0.7
    
    # 关键词扩展数量
    keyword_expand_k: int = 3
```

### 存储配置

```python
# 记忆存储路径
MEMORY_DIR = "Aveline_daily_data/memories"

# 向量缓存路径
VECTOR_CACHE_DIR = "Aveline_daily_data/vectors"

# 索引文件
KEYWORD_INDEX_FILE = "keyword_index.json"
CATEGORY_INDEX_FILE = "category_index.json"
```

## 性能特性

### 检索性能

- **关键词搜索**: < 50ms
- **向量搜索**: < 100ms
- **混合搜索**: < 150ms

### 存储容量

- **短期记忆**: 100条
- **长期记忆**: 无限制
- **向量缓存**: 自动管理

### 内存占用

- **基础占用**: < 50MB
- **向量缓存**: 按需加载
- **索引大小**: 与记忆数量成正比

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [向量搜索文档](./README_VECTOR_SEARCH.md)
- [系统设计文档](./enhanced_memory_system_design.md)
- [向量搜索实现计划](./vector_search_implementation_plan.md)
- [核心层文档](../core/README.md)

---

最后更新：2026-06-18
