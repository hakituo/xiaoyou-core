import unittest
import time
import threading
import random
from collections import defaultdict
from ..cache import EnhancedCacheManager, CacheStrategy, cache_decorator


class TestEnhancedCacheManager(unittest.TestCase):
    
    def setUp(self):
        """每个测试前初始化缓存管理器"""
        self.cache = EnhancedCacheManager(max_size=10, ttl=10)
    
    def test_basic_get_set(self):
        """测试基本的获取和设置功能"""
        # 设置缓存项
        self.cache.set("key1", "value1")
        
        # 获取缓存项
        self.assertEqual(self.cache.get("key1"), "value1")
        
        # 获取不存在的缓存项
        self.assertIsNone(self.cache.get("nonexistent"))
    
    def test_expiration(self):
        """测试缓存过期功能"""
        # 创建一个短期缓存
        temp_cache = EnhancedCacheManager(max_size=10, ttl=1)  # 1秒过期
        
        # 设置缓存项
        temp_cache.set("key1", "value1")
        
        # 验证立即获取成功
        self.assertEqual(temp_cache.get("key1"), "value1")
        
        # 等待过期
        time.sleep(1.1)
        
        # 验证过期后获取失败
        self.assertIsNone(temp_cache.get("key1"))
    
    def test_custom_ttl(self):
        """测试自定义TTL功能"""
        # 设置具有不同TTL的缓存项
        self.cache.set("short_key", "short_value", custom_ttl=1)
        self.cache.set("long_key", "long_value", custom_ttl=5)
        
        # 立即获取，两者都应该存在
        self.assertEqual(self.cache.get("short_key"), "short_value")
        self.assertEqual(self.cache.get("long_key"), "long_value")
        
        # 等待1.1秒，短TTL项应该过期
        time.sleep(1.1)
        
        # 验证结果
        self.assertIsNone(self.cache.get("short_key"))
        self.assertEqual(self.cache.get("long_key"), "long_value")
    
    def test_max_size_limit(self):
        """测试最大大小限制功能"""
        # 创建一个小缓存
        small_cache = EnhancedCacheManager(max_size=3)
        
        # 添加超过最大大小的项
        for i in range(5):
            small_cache.set(f"key{i}", f"value{i}")
        
        # 验证只有最近的3个项存在
        self.assertIsNone(small_cache.get("key0"))
        self.assertIsNone(small_cache.get("key1"))
        self.assertEqual(small_cache.get("key2"), "value2")
        self.assertEqual(small_cache.get("key3"), "value3")
        self.assertEqual(small_cache.get("key4"), "value4")
    
    def test_lru_strategy(self):
        """测试LRU缓存策略"""
        lru_cache = EnhancedCacheManager(max_size=3, strategy=CacheStrategy.LRU)
        
        # 添加项
        lru_cache.set("key1", "value1")
        lru_cache.set("key2", "value2")
        lru_cache.set("key3", "value3")
        
        # 访问key1，使其成为最近使用的
        lru_cache.get("key1")
        
        # 添加新项，应该驱逐key2（最久未使用）
        lru_cache.set("key4", "value4")
        
        # 验证结果
        self.assertEqual(lru_cache.get("key1"), "value1")
        self.assertIsNone(lru_cache.get("key2"))
        self.assertEqual(lru_cache.get("key3"), "value3")
        self.assertEqual(lru_cache.get("key4"), "value4")
    
    def test_mru_strategy(self):
        """测试MRU缓存策略"""
        mru_cache = EnhancedCacheManager(max_size=3, strategy=CacheStrategy.MRU)
        
        # 添加项
        mru_cache.set("key1", "value1")
        mru_cache.set("key2", "value2")
        mru_cache.set("key3", "value3")
        
        # 访问key1，使其成为最近使用的
        mru_cache.get("key1")
        
        # 添加新项，应该驱逐key1（最近使用的）
        mru_cache.set("key4", "value4")
        
        # 验证结果
        self.assertIsNone(mru_cache.get("key1"))
        self.assertEqual(mru_cache.get("key2"), "value2")
        self.assertEqual(mru_cache.get("key3"), "value3")
        self.assertEqual(mru_cache.get("key4"), "value4")
    
    def test_fifo_strategy(self):
        """测试FIFO缓存策略"""
        fifo_cache = EnhancedCacheManager(max_size=3, strategy=CacheStrategy.FIFO)
        
        # 添加项
        fifo_cache.set("key1", "value1")
        fifo_cache.set("key2", "value2")
        fifo_cache.set("key3", "value3")
        
        # 访问key1，但在FIFO中这不会改变顺序
        fifo_cache.get("key1")
        
        # 添加新项，应该驱逐key1（最早进入的）
        fifo_cache.set("key4", "value4")
        
        # 验证结果
        self.assertIsNone(fifo_cache.get("key1"))
        self.assertEqual(fifo_cache.get("key2"), "value2")
        self.assertEqual(fifo_cache.get("key3"), "value3")
        self.assertEqual(fifo_cache.get("key4"), "value4")
    
    def test_lfu_strategy(self):
        """测试LFU缓存策略"""
        lfu_cache = EnhancedCacheManager(max_size=3, strategy=CacheStrategy.LFU)
        
        # 添加项
        lfu_cache.set("key1", "value1")
        lfu_cache.set("key2", "value2")
        lfu_cache.set("key3", "value3")
        
        # 增加key1和key2的访问频率
        for _ in range(5):
            lfu_cache.get("key1")
        
        for _ in range(3):
            lfu_cache.get("key2")
        
        # 添加新项，应该驱逐key3（使用频率最低的）
        lfu_cache.set("key4", "value4")
        
        # 验证结果
        self.assertEqual(lfu_cache.get("key1"), "value1")
        self.assertEqual(lfu_cache.get("key2"), "value2")
        self.assertIsNone(lfu_cache.get("key3"))
        self.assertEqual(lfu_cache.get("key4"), "value4")
    
    def test_clear(self):
        """测试清空缓存功能"""
        # 添加项
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        
        # 验证项存在
        self.assertEqual(self.cache.get("key1"), "value1")
        
        # 清空缓存
        self.cache.clear()
        
        # 验证项不存在
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))
    
    def test_delete(self):
        """测试删除特定项功能"""
        # 添加项
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        
        # 删除一个项
        self.assertTrue(self.cache.delete("key1"))
        
        # 验证结果
        self.assertIsNone(self.cache.get("key1"))
        self.assertEqual(self.cache.get("key2"), "value2")
        
        # 删除不存在的项
        self.assertFalse(self.cache.delete("nonexistent"))
    
    def test_stats(self):
        """测试统计功能"""
        # 确保统计已启用
        self.assertTrue(self.cache.stats_enabled)
        
        # 执行一些操作
        self.cache.set("key1", "value1")
        self.cache.get("key1")  # 命中
        self.cache.get("nonexistent")  # 未命中
        
        # 获取统计信息
        stats = self.cache.get_stats()
        
        # 验证统计信息
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["max_size"], 10)
        self.assertEqual(stats["hit_rate"], 50.0)  # 1命中/2次访问
    
    def test_update_config(self):
        """测试更新配置功能"""
        # 添加一些项
        for i in range(5):
            self.cache.set(f"key{i}", f"value{i}")
        
        # 更新最大大小为3
        new_config = self.cache.update_config(max_size=3)
        
        # 验证配置更新
        self.assertEqual(new_config["max_size"], 3)
        
        # 验证缓存大小已调整
        self.assertEqual(len(self.cache.cache), 3)
        
        # 更新TTL和策略
        new_config = self.cache.update_config(ttl=5, strategy=CacheStrategy.MRU)
        
        # 验证配置更新
        self.assertEqual(new_config["ttl"], 5)
        self.assertEqual(new_config["strategy"], "MRU")
    
    def test_item_size_limit(self):
        """测试项大小限制功能"""
        # 创建有限制的缓存
        size_limited_cache = EnhancedCacheManager(max_size=10, item_size_limit=20)
        
        # 设置小项应该成功
        self.assertTrue(size_limited_cache.set("small_key", "small_value"))
        
        # 设置大项应该失败
        large_value = "x" * 100  # 超过20字节
        self.assertFalse(size_limited_cache.set("large_key", large_value))
        
        # 验证结果
        self.assertEqual(size_limited_cache.get("small_key"), "small_value")
        self.assertIsNone(size_limited_cache.get("large_key"))
    
    def test_thread_safety(self):
        """测试线程安全性"""
        # 创建一个新的缓存
        thread_cache = EnhancedCacheManager(max_size=100, ttl=10)
        
        # 计数器用于验证操作
        operation_count = defaultdict(int)
        
        def worker(worker_id, operations):
            """工作线程函数"""
            for i in range(operations):
                key = f"key_{worker_id}_{i}"
                value = f"value_{worker_id}_{i}"
                
                # 随机执行操作
                op = random.choice(["set", "get", "delete"])
                
                if op == "set":
                    thread_cache.set(key, value)
                    operation_count["set"] += 1
                elif op == "get":
                    thread_cache.get(key)
                    operation_count["get"] += 1
                elif op == "delete":
                    thread_cache.delete(key)
                    operation_count["delete"] += 1
        
        # 创建多个线程
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i, 100))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证至少执行了一些操作
        self.assertTrue(sum(operation_count.values()) > 0)
        
        # 验证缓存状态仍然一致
        # 如果线程安全有问题，这可能会抛出异常
        try:
            stats = thread_cache.get_stats()
            self.assertIsNotNone(stats)
        except Exception as e:
            self.fail(f"线程安全测试失败: {str(e)}")


class TestCacheDecorator(unittest.TestCase):
    
    def test_sync_decorator(self):
        """测试同步函数的缓存装饰器"""
        # 计数器用于验证函数调用次数
        call_count = 0
        
        @cache_decorator(max_size=10, ttl=5)
        def expensive_function(a, b):
            nonlocal call_count
            call_count += 1
            # 模拟昂贵的操作
            time.sleep(0.01)
            return a + b
        
        # 多次调用相同参数的函数
        result1 = expensive_function(1, 2)
        result2 = expensive_function(1, 2)  # 应该从缓存返回
        result3 = expensive_function(3, 4)  # 新参数，应该执行函数
        
        # 验证结果
        self.assertEqual(result1, 3)
        self.assertEqual(result2, 3)
        self.assertEqual(result3, 7)
        
        # 验证函数只被调用了两次
        self.assertEqual(call_count, 2)
    
    def test_async_decorator(self):
        """测试异步函数的缓存装饰器"""
        # 计数器用于验证函数调用次数
        call_count = 0
        
        @cache_decorator(max_size=10, ttl=5)
        async def async_expensive_function(a, b):
            nonlocal call_count
            call_count += 1
            # 模拟昂贵的异步操作
            await asyncio.sleep(0.01)
            return a + b
        
        # 运行异步测试
        async def run_test():
            # 多次调用相同参数的函数
            result1 = await async_expensive_function(1, 2)
            result2 = await async_expensive_function(1, 2)  # 应该从缓存返回
            result3 = await async_expensive_function(3, 4)  # 新参数，应该执行函数
            
            # 验证结果
            self.assertEqual(result1, 3)
            self.assertEqual(result2, 3)
            self.assertEqual(result3, 7)
            
            # 验证函数只被调用了两次
            self.assertEqual(call_count, 2)
        
        import asyncio
        asyncio.run(run_test())
    
    def test_decorator_expiration(self):
        """测试装饰器的缓存过期功能"""
        # 计数器用于验证函数调用次数
        call_count = 0
        
        @cache_decorator(max_size=10, ttl=1)  # 1秒过期
        def short_ttl_function(a):
            nonlocal call_count
            call_count += 1
            return a * 2
        
        # 首次调用
        result1 = short_ttl_function(5)
        
        # 立即再次调用，应该使用缓存
        result2 = short_ttl_function(5)
        
        # 等待缓存过期
        time.sleep(1.1)
        
        # 再次调用，应该重新执行函数
        result3 = short_ttl_function(5)
        
        # 验证结果和调用次数
        self.assertEqual(result1, 10)
        self.assertEqual(result2, 10)
        self.assertEqual(result3, 10)
        self.assertEqual(call_count, 2)  # 应该被调用两次（一次初始，一次过期后）


if __name__ == '__main__':
    unittest.main()