# 向量搜索功能使用说明

本文档介绍了小悠核心框架中新增的向量搜索功能，该功能允许基于语义相似度查询记忆内容，提供更智能的记忆检索体验。

## 功能概述

向量搜索功能主要包括：

1. **文本嵌入生成**：将文本转换为向量表示
2. **相似度搜索**：基于向量相似度检索相关记忆
3. **混合搜索**：结合关键词搜索和向量相似度搜索
4. **加权向量搜索**：考虑记忆权重的向量搜索

## 核心组件

### 1. EmbeddingGenerator

负责将文本转换为向量表示的组件，基于Hugging Face的sentence-transformers模型。

#### 主要方法：
- `generate_embedding(text)`: 生成单个文本的向量嵌入
- `generate_embeddings_batch(texts)`: 批量生成文本向量嵌入
- `cosine_similarity(vec1, vec2)`: 计算两个向量的余弦相似度
- `embedding_to_base64(embedding)`: 将向量转换为base64编码字符串
- `base64_to_embedding(encoded)`: 将base64编码字符串转换回向量

#### 使用示例：
```python
from memory.embedding_generator import get_embedding_generator

# 获取嵌入生成器实例
embedding_generator = get_embedding_generator()

# 生成文本嵌入
vector = embedding_generator.generate_embedding("这是一段测试文本")

# 计算相似度
vector2 = embedding_generator.generate_embedding("这是另一段测试文本")
similarity = embedding_generator.cosine_similarity(vector, vector2)
```

### 2. WeightedMemoryManager向量搜索功能

WeightedMemoryManager类新增了向量搜索相关方法：

#### 主要方法：
- `search_by_similarity(query, top_k=5, min_weight=0.0)`: 基于向量相似度搜索记忆
- `hybrid_search(query, top_k=5, keyword_weight=0.3, similarity_weight=0.7, min_weight=0.0)`: 混合关键词和向量搜索
- `generate_missing_embeddings()`: 为没有向量嵌入的记忆生成嵌入

#### 使用示例：
```python
from memory.weighted_memory_manager import WeightedMemoryManager

# 创建加权记忆管理器实例
memory_manager = WeightedMemoryManager()

# 添加带有向量嵌入的记忆
memory_manager.add_memory(
    user_id="user123",
    content="Python是一种广泛使用的编程语言",
    weight=0.8,
    tags=["编程", "Python"]
)

# 使用向量相似度搜索
results = memory_manager.search_by_similarity("编程语言", top_k=3)

# 使用混合搜索
hybrid_results = memory_manager.hybrid_search(
    query="Python编程",
    top_k=5,
    keyword_weight=0.3,
    similarity_weight=0.7
)

# 为缺失嵌入的记忆生成嵌入
memory_manager.generate_missing_embeddings()
```

## 配置说明

向量搜索功能依赖于Hugging Face的sentence-transformers模型。默认使用的模型是`paraphrase-multilingual-MiniLM-L12-v2`，支持多语言。

### 首次使用

首次使用时，系统会自动下载所需的模型文件。请确保网络连接正常，并且有足够的磁盘空间。

### 离线使用

如果需要在离线环境中使用，可以提前下载模型文件，并放置在适当的缓存目录中。

## 性能考虑

- 向量搜索比传统的关键词搜索计算成本更高
- 对于大量记忆，建议定期调用`generate_missing_embeddings()`确保所有记忆都有向量嵌入
- 可以通过调整`min_weight`参数过滤低权重的记忆，提高搜索效率

## 注意事项

1. 向量搜索结果的质量取决于嵌入模型的质量和训练数据
2. 对于非常短的文本（如单个单词），向量搜索的效果可能不如关键词搜索
3. 混合搜索通常能提供更好的整体搜索体验，建议优先使用

## 示例：完整的使用流程

```python
from memory.weighted_memory_manager import WeightedMemoryManager

# 初始化记忆管理器
wm = WeightedMemoryManager()

# 添加一些记忆
wm.add_memory("user123", "Python是一种解释型、面向对象、动态数据类型的高级程序设计语言", 0.9, ["编程", "Python"])
wm.add_memory("user123", "Java是一种广泛使用的计算机编程语言", 0.8, ["编程", "Java"])
wm.add_memory("user123", "今天天气很好", 0.5, ["天气"])

# 确保所有记忆都有向量嵌入
wm.generate_missing_embeddings()

# 执行各种搜索
print("\n基于相似度的搜索 - 编程语言:")
similar_results = wm.search_by_similarity("编程语言", top_k=2)
for result in similar_results:
    print(f"内容: {result['content']}, 相似度: {result['similarity']:.4f}")

print("\n混合搜索 - Python开发:")
hybrid_results = wm.hybrid_search("Python开发", top_k=2)
for result in hybrid_results:
    print(f"内容: {result['content']}, 综合得分: {result['score']:.4f}")
```

## 故障排除

### 常见问题

1. **模型下载失败**：检查网络连接，可能需要配置代理
2. **内存占用过高**：对于大量记忆，可以调整批处理大小
3. **搜索结果不理想**：尝试调整混合搜索中的权重参数，或使用更精确的查询语句

如有其他问题，请参考完整的错误日志或联系技术支持。