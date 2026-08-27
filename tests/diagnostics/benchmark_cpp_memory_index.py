import time
import random
import uuid

# 假设我们在 tests 目录下运行
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memory_index_py

def generate_dummy_embedding(dim=1536):
    return [random.uniform(-1.0, 1.0) for _ in range(dim)]

def run_benchmark():
    print("=== C++ Memory Indexer Benchmark ===")
    indexer = memory_index_py.VectorIndexer()
    
    num_records = 50000  # 模拟 5 万条记忆
    dim = 1536          # 模拟 OpenAI 或类似模型的维度
    
    print(f"\n[1] 生成并插入 {num_records} 条假数据 (维度: {dim})...")
    start_time = time.time()
    for i in range(num_records):
        mid = str(uuid.uuid4())
        emb = generate_dummy_embedding(dim)
        weight = random.uniform(1.0, 10.0)
        ts = time.time() - random.uniform(0, 30 * 24 * 3600)  # 过去 30 天内
        indexer.addRecord(mid, emb, weight, ts, "chat", ["test_topic"])
    
    insert_time = time.time() - start_time
    print(f"插入耗时: {insert_time:.2f} 秒")
    
    print("\n[2] 执行极速检索测试...")
    query_emb = generate_dummy_embedding(dim)
    
    # 预热一次
    indexer.search(query_emb, 10, 0.0, time.time(), 0.95, 0.1, 0.0, "", [])
    
    # 测试 100 次检索取平均值
    num_searches = 100
    search_start = time.time()
    for _ in range(num_searches):
        results = indexer.search(
            query_embedding=query_emb,
            top_k=10,
            min_similarity=0.0,
            current_time=time.time(),
            decay_rate=0.95,
            base_min_weight=0.1,
            absolute_min_weight=0.0,
            filter_source="",
            filter_topics=[]
        )
    search_end = time.time()
    
    avg_search_time = ((search_end - search_start) / num_searches) * 1000  # 转为毫秒
    print(f"执行 {num_searches} 次检索")
    print(f"平均每次检索耗时: {avg_search_time:.2f} ms")
    
    print("\nTop 3 检索结果展示:")
    for i, res in enumerate(results[:3]):
        print(f"  {i+1}. ID: {res.id[:8]}... 相似度: {res.similarity:.4f}, 综合得分: {res.final_score:.4f}")

if __name__ == "__main__":
    run_benchmark()
