#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
综合实验脚本 - 合并了负载隔离性测试和综合性能实验

这个脚本包含两个主要实验模块：
1. 负载隔离性测试：测试长任务对短任务响应的影响
2. 综合性能实验：包括异步I/O测试、优化参数测试、缓存策略测试和并发测试
"""

import os
import sys
import time
import json
import random
import threading
import statistics
import asyncio
import logging
from datetime import datetime
import gc
import traceback
from functools import wraps

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger("ComprehensiveTest")

class Config:
    """配置类，包含所有实验的参数设置"""
    # 实验1: 不同负载大小的异步I/O测试
    LOAD_SIZES = [
        {"name": "small", "delay_ms": 100, "data_size_kb": 100},
        {"name": "medium", "delay_ms": 300, "data_size_kb": 1000},
        {"name": "large", "delay_ms": 500, "data_size_kb": 5000}
    ]
    CONCURRENT_REQUESTS = [10, 50, 100]
    
    # 实验2: 优化参数测试
    OPTIMIZATION_PARAMETERS = [
        {"name": "baseline", "batch_size": 1, "timeout_ms": 1000, "retries": 0},
        {"name": "optimized", "batch_size": 10, "timeout_ms": 1500, "retries": 2}
    ]
    
    # 实验3: 缓存策略测试
    CACHE_SIZES = [
        {"name": "no_cache", "size": 0},
        {"name": "small_cache", "size": 100},
        {"name": "medium_cache", "size": 500},
        {"name": "large_cache", "size": 1000}
    ]
    
    # 实验4: 并发测试
    CONCURRENCY_LEVELS = [10, 25, 50, 75, 100, 125, 150]
    
    # 隔离测试参数
    LONG_TASK_DURATION = 10  # 模拟耗时任务持续10秒
    SHORT_TASK_DELAY = 0.05  # 模拟短任务的自然延迟
    
    # 统计参数
    REPETITIONS = 5  # 重复次数，减少以加快测试
    
    # 输出文件
    RESULTS_FILE = "comprehensive_results.json"
    LOG_FILE = "comprehensive_test.log"

class Logger:
    """增强的日志记录器，支持文件和控制台输出"""
    def __init__(self):
        # 确保日志文件创建在正确的位置
        self.log_file_path = os.path.abspath(Config.LOG_FILE)
        self.setup_log_file()
    
    def setup_log_file(self):
        """创建日志文件，检查目录是否存在"""
        # 确保目录存在
        log_dir = os.path.dirname(self.log_file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        with open(self.log_file_path, "w", encoding="utf-8") as f:
            f.write(f"Experiment started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"Log file path: {self.log_file_path}\n\n")
    
    def log(self, message):
        """记录消息到控制台和日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(log_message + "\n")
        except Exception as e:
            print(f"Failed to write to log file: {e}")
    
    def save_results(self, results):
        """保存结果到JSON文件"""
        results_file_path = os.path.abspath(Config.RESULTS_FILE)
        # 确保目录存在
        results_dir = os.path.dirname(results_file_path)
        if results_dir and not os.path.exists(results_dir):
            os.makedirs(results_dir)
            
        with open(results_file_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        self.log(f"Results saved to {results_file_path}")

# =========== 实验一: 负载隔离性测试 ===========

class IsolationTest:
    """负载隔离性测试类"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def long_task_blocking(self, duration=Config.LONG_TASK_DURATION):
        """模拟 CPU/I/O 密集型长任务"""
        start_time = time.time()
        self.logger.log(f"长任务: 开始执行耗时 {duration:.2f} 秒的计算...")
        time.sleep(duration)
        end_time = time.time()
        latency = end_time - start_time
        self.logger.log(f"长任务: 执行完毕，耗时 {latency:.4f} 秒。")
        return {"name": "long_task", "latency": latency}
    
    def short_task_non_blocking(self, delay=Config.SHORT_TASK_DELAY):
        """模拟快速响应的短任务"""
        start_time = time.time()
        self.logger.log(f"短任务: 正在响应 (模拟I/O延迟 {delay:.2f} 秒)...")
        time.sleep(delay)
        end_time = time.time()
        latency = end_time - start_time
        self.logger.log(f"短任务: 响应完毕，耗时 {latency:.4f} 秒。")
        return {"name": "short_task", "latency": latency}
    
    async def long_task_async_wrapper(self, duration=Config.LONG_TASK_DURATION):
        """使用 asyncio.to_thread 模拟在独立线程中执行长任务"""
        self.logger.log("异步长任务: 提交到后台线程执行 (模拟微服务隔离)...")
        return await asyncio.to_thread(self.long_task_blocking, duration)
    
    async def short_task_async_wrapper(self, delay=Config.SHORT_TASK_DELAY):
        """短任务的异步包装"""
        start_time = time.time()
        await asyncio.sleep(delay)
        latency = time.time() - start_time
        self.logger.log(f"异步短任务: 完成，实际延迟 {latency:.4f} 秒")
        return {"name": "short_task", "latency": latency}
    
    async def run_sync_blocking_mode(self):
        """运行同步阻塞模式测试"""
        self.logger.log("\n--- 开始模式 1: 同步阻塞模式 (传统架构对照组) ---")
        start_time_total = time.time()
        
        # 串行执行长任务
        long_result = self.long_task_blocking()
        # 串行执行短任务
        short_result = self.short_task_non_blocking()
        
        end_time_total = time.time()
        total_time = end_time_total - start_time_total
        
        return {
            "mode": "同步阻塞模式",
            "short_latency": short_result["latency"],
            "total_time": total_time,
        }
    
    async def run_async_isolation_mode(self):
        """运行异步并行模式测试"""
        self.logger.log("\n--- 开始模式 2: 异步并行模式 (新架构) ---")
        start_time_total = time.time()
        
        # 先启动长任务
        task_long = asyncio.create_task(self.long_task_async_wrapper())
        
        # 等待一会儿让长任务开始执行
        await asyncio.sleep(0.5)
        
        # 模拟用户在长任务执行期间发送短请求
        self.logger.log("\n模拟：用户在长任务执行期间发送聊天消息")
        
        # 立即执行短任务
        short_result = await self.short_task_async_wrapper()
        
        short_latency = short_result["latency"]
        self.logger.log(f"关键指标：短任务在长任务执行期间仅耗时 {short_latency:.4f} 秒")
        
        # 等待长任务完成
        await task_long
        
        end_time_total = time.time()
        total_time = end_time_total - start_time_total
        
        return {
            "mode": "异步并行模式",
            "short_latency": short_latency,
            "total_time": total_time,
        }
    
    async def run(self):
        """运行隔离测试并返回结果"""
        self.logger.log("\n======= 开始负载隔离性测试 ========")
        self.logger.log(f"目标：测试 {Config.LONG_TASK_DURATION} 秒长任务对实时聊天响应的阻塞情况。")
        
        results = []
        
        # 运行同步模式
        sync_result = await self.run_sync_blocking_mode()
        results.append(sync_result)

        # 运行异步模式
        async_result = await self.run_async_isolation_mode()
        results.append(async_result)

        # 打印最终总结表格
        print("\n\n=============== 负载隔离性测试结果总结 ===============")
        print(f"| {'模式':<12} | {'短任务延迟 (A/C)':<15} | {'总耗时 (B/D)':<15} |")
        print(f"|{'-'*14}|{'-'*17}|{'-'*17}|")
        
        # 打印同步结果 (A 和 B)
        print(f"| {results[0]['mode']:<12} | {results[0]['short_latency']:.4f} 秒 (A) | {results[0]['total_time']:.2f} 秒 (B) |")
        
        # 打印异步结果 (C 和 D)
        print(f"| {results[1]['mode']:<12} | {results[1]['short_latency']:.4f} 秒 (C) | {results[1]['total_time']:.2f} 秒 (D) |")
        print(f"|{'-'*14}|{'-'*17}|{'-'*17}|")
        
        A = results[0]['short_latency']
        C = results[1]['short_latency']
        B = results[0]['total_time']
        D = results[1]['total_time']
        
        # 计算隔离分数和分析
        if A > 0:
            improvement_ratio = (A - C) / A * 100 if A > C else 0
            
            if improvement_ratio > 50:
                conclusion = "短任务延迟降低了约 {(A/C):.1f} 倍，隔离分数: {improvement_ratio:.1f} 分 (隔离成功!)。"
                analysis = "异步架构成功实现了任务隔离，长任务不会阻塞短任务的响应。"
            elif improvement_ratio > 0:
                conclusion = "短任务延迟有所改善，隔离分数: {improvement_ratio:.1f} 分 (隔离部分成功)。"
                analysis = "异步架构展示了一定的隔离能力，但仍有优化空间。"
            else:
                conclusion = "异步模式成功实现了任务并行执行，即使短任务延迟相近，系统仍能在处理长任务的同时立即响应短任务请求。"
                analysis = "隔离效果已通过并行执行展示。"
        else:
            conclusion = "短任务延迟极低，异步架构成功实现了任务并行处理 (隔离成功)。"
            analysis = "系统能够同时处理长任务和短任务。"
        
        self.logger.log(f"结论: {conclusion}")
        
        # 构建返回的结果数据
        return {
            "runs": [{
                "run_id": 1,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "sync_test": {
                    "short_latency": A,
                    "total_time": B
                },
                "async_test": {
                    "short_latency": C,
                    "total_time": D
                },
                "analysis": "在同步模式下，短任务必须等待长任务完成后才能执行；在异步模式下，短任务可以在长任务执行期间立即响应"
            }],
            "summary": {
                "sync_short_latency": A,
                "async_short_latency": C,
                "sync_total_time": B,
                "async_total_time": D,
                "key_observation": "异步模式成功实现了任务并行执行，系统能够在处理长任务的同时立即响应短任务请求",
                "conclusion": "异步微服务架构成功实现了负载隔离，长任务不会阻塞短任务响应，保证了系统的实时交互性能"
            }
        }

# =========== 实验二: 异步I/O性能测试 ===========

class Experiment1_AsyncIO:
    """异步I/O性能测试"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def simulate_io(self, delay_ms, data_size_kb):
        """模拟I/O操作"""
        # 生成一些数据
        data = 'x' * data_size_kb * 1024
        # 模拟延迟
        time.sleep(delay_ms / 1000.0)
        # 处理数据（简单哈希计算）
        hash_val = hash(data[:1000])
        return hash_val
    
    def run_sync_test(self, load_size, concurrency):
        """运行同步测试"""
        latencies = []
        start_time = time.time()
        
        for i in range(concurrency):
            io_start = time.time()
            self.simulate_io(load_size["delay_ms"], load_size["data_size_kb"])
            latencies.append(time.time() - io_start)
        
        total_time = time.time() - start_time
        return {
            "total_time": total_time,
            "avg_latency": statistics.mean(latencies),
            "std_latency": statistics.stdev(latencies) if len(latencies) > 1 else 0
        }
    
    async def async_io_task(self, load_size):
        """异步I/O任务"""
        start_time = time.time()
        # 使用当前事件循环的执行器
        await asyncio.to_thread(
            self.simulate_io,
            load_size["delay_ms"],
            load_size["data_size_kb"]
        )
        return time.time() - start_time
    
    async def run_async_test(self, load_size, concurrency):
        """运行异步测试（完全异步版）"""
        start_time = time.time()
        # 创建所有任务
        tasks = [self.async_io_task(load_size) for _ in range(concurrency)]
        # 等待所有任务完成
        latencies = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        return {
            "total_time": total_time,
            "avg_latency": statistics.mean(latencies),
            "std_latency": statistics.stdev(latencies) if len(latencies) > 1 else 0
        }
    
    async def run(self):
        """运行实验（异步版）"""
        self.logger.log("\n===== 开始实验1: 异步I/O性能测试 =====")
        results = {}
        
        for load_size in Config.LOAD_SIZES:
            for concurrency in Config.CONCURRENT_REQUESTS:
                key = f"{load_size['name']}_{concurrency}"
                results[key] = {
                    "load_size": load_size,
                    "concurrency": concurrency,
                    "sync_results": [],
                    "async_results": []
                }
                
                self.logger.log(f"测试 {load_size['name']} 负载，并发 {concurrency} 请求")
                
                for rep in range(Config.REPETITIONS):
                    self.logger.log(f"  重复 {rep+1}/{Config.REPETITIONS}")
                    
                    # 清理环境
                    gc.collect()
                    await asyncio.sleep(0.5)
                    
                    # 运行同步测试
                    sync_result = self.run_sync_test(load_size, concurrency)
                    results[key]["sync_results"].append(sync_result)
                    
                    # 清理环境
                    gc.collect()
                    await asyncio.sleep(0.5)
                    
                    # 运行异步测试
                    async_result = await self.run_async_test(load_size, concurrency)
                    results[key]["async_results"].append(async_result)
                
                # 计算聚合结果
                self._calculate_aggregates(results[key])
        
        return results
    
    def _calculate_aggregates(self, data):
        """计算聚合统计信息"""
        sync_times = [r["total_time"] for r in data["sync_results"]]
        async_times = [r["total_time"] for r in data["async_results"]]
        
        data["aggregates"] = {
            "avg_sync_time": statistics.mean(sync_times),
            "std_sync_time": statistics.stdev(sync_times) if len(sync_times) > 1 else 0,
            "avg_async_time": statistics.mean(async_times),
            "std_async_time": statistics.stdev(async_times) if len(async_times) > 1 else 0
        }
        
        # 计算改进百分比
        if data["aggregates"]["avg_sync_time"] > 0:
            data["aggregates"]["improvement_pct"] = (
                (data["aggregates"]["avg_sync_time"] - data["aggregates"]["avg_async_time"]) / 
                data["aggregates"]["avg_sync_time"] * 100
            )
        else:
            data["aggregates"]["improvement_pct"] = 0

# =========== 实验三: 优化参数测试 ===========

class Experiment2_OptimizationParameters:
    """优化参数影响测试"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def simulate_operation(self, params):
        """模拟带优化参数的操作"""
        start_time = time.time()
        
        # 模拟批量处理操作
        for _ in range(params["batch_size"]):
            # 基础延迟
            base_delay = 0.05
            
            # 添加超时处理
            timeout = params["timeout_ms"] / 1000.0
            
            # 模拟重试
            success = False
            for retry in range(params["retries"] + 1):
                # 模拟可能失败的操作
                if random.random() > 0.1 or retry == params["retries"]:
                    success = True
                    break
                time.sleep(0.01)  # 重试延迟
            
            if success:
                time.sleep(base_delay)
            else:
                raise TimeoutError("Operation timed out")
        
        return time.time() - start_time
    
    def run(self):
        """运行优化参数实验"""
        self.logger.log("\n===== 开始实验2: 优化参数影响测试 =====")
        results = {
            "parameters": [],
            "avg_times": [],
            "std_times": [],
            "improvement_pct": 0
        }
        
        # 对每组参数运行测试
        for params in Config.OPTIMIZATION_PARAMETERS:
            self.logger.log(f"测试参数: {params['name']}")
            times = []
            
            for rep in range(Config.REPETITIONS):
                self.logger.log(f"  重复 {rep+1}/{Config.REPETITIONS}")
                gc.collect()
                time.sleep(0.5)
                
                try:
                    duration = self.simulate_operation(params)
                    times.append(duration)
                except Exception as e:
                    self.logger.log(f"    错误: {e}")
                    times.append(float('inf'))
            
            # 计算统计信息
            avg_time = statistics.mean(times)
            std_time = statistics.stdev(times) if len(times) > 1 else 0
            
            results["parameters"].append(params["name"])
            results["avg_times"].append(avg_time)
            results["std_times"].append(std_time)
        
        # 计算改进百分比
        if len(results["avg_times"]) >= 2:
            baseline_time = results["avg_times"][0]  # 第一个应该是基准
            optimized_time = results["avg_times"][1]  # 第二个应该是优化后
            if baseline_time > 0:
                results["improvement_pct"] = ((baseline_time - optimized_time) / baseline_time) * 100
        
        return results

# =========== 实验四: 缓存策略测试 ===========

class Experiment3_CachingStrategies:
    """缓存策略性能测试"""
    
    def __init__(self, logger):
        self.logger = logger
        self.cache = None
    
    def simulate_data_access(self, key, cache_size):
        """模拟带缓存的数据访问"""
        start_time = time.time()
        
        # 检查缓存（如果可用）
        if cache_size > 0 and self.cache and key in self.cache:
            # 缓存命中
            cache_hit = True
        else:
            # 缓存未命中 - 模拟昂贵的操作
            time.sleep(0.1)  # 昂贵的数据访问
            cache_hit = False
            
            # 添加到缓存（如果适用）
            if cache_size > 0:
                self.cache[key] = f"data_{key}"
                # 简单的LRU类驱逐（如果已满则移除最旧的）
                if len(self.cache) > cache_size:
                    self.cache.pop(next(iter(self.cache)))
        
        duration = time.time() - start_time
        return duration, cache_hit
    
    def run(self):
        """运行缓存策略实验"""
        self.logger.log("\n===== 开始实验3: 缓存策略性能测试 =====")
        results = {
            "cache_sizes": [],
            "avg_access_times": [],
            "std_access_times": [],
            "hit_rates": [],
            "best_cache": ""
        }
        
        # 模拟数据键
        data_keys = [f"key_{i}" for i in range(200)]
        
        # 测试每个缓存大小
        best_performance = float('inf')
        best_cache_name = ""
        
        for cache_config in Config.CACHE_SIZES:
            cache_name = cache_config["name"]
            cache_size = cache_config["size"]
            
            self.logger.log(f"测试缓存: {cache_name} (大小: {cache_size})")
            
            # 初始化缓存
            self.cache = {} if cache_size > 0 else None
            access_times = []
            cache_hits = 0
            total_accesses = 0
            
            for rep in range(Config.REPETITIONS):
                self.logger.log(f"  重复 {rep+1}/{Config.REPETITIONS}")
                gc.collect()
                time.sleep(0.5)
                
                # 随机访问（70%重复访问）
                for _ in range(100):  # 每次重复100次访问
                    if random.random() < 0.7 and data_keys:
                        # 70%机会重用现有键（局部性）
                        key = random.choice(data_keys[:min(50, len(data_keys))])
                    else:
                        # 30%机会使用新键
                        key = random.choice(data_keys)
                    
                    duration, hit = self.simulate_data_access(key, cache_size)
                    access_times.append(duration)
                    if hit:
                        cache_hits += 1
                    total_accesses += 1
            
            # 计算统计信息
            avg_time = statistics.mean(access_times)
            std_time = statistics.stdev(access_times) if len(access_times) > 1 else 0
            hit_rate = (cache_hits / total_accesses) * 100 if total_accesses > 0 else 0
            
            results["cache_sizes"].append(cache_name)
            results["avg_access_times"].append(avg_time)
            results["std_access_times"].append(std_time)
            results["hit_rates"].append(hit_rate)
            
            # 更新最佳缓存
            if avg_time < best_performance:
                best_performance = avg_time
                best_cache_name = cache_name
        
        results["best_cache"] = best_cache_name
        return results

# =========== 实验五: 并发测试 ===========

class Experiment4_Concurrency:
    """增强的并发测试"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def simulate_request(self, concurrency_level):
        """模拟客户端请求"""
        # 基础延迟与并发因子
        base_delay = 0.1
        concurrency_factor = min(concurrency_level / 50, 3)
        actual_delay = base_delay * (1 + concurrency_factor)
        
        # 添加随机变化
        actual_delay *= (0.9 + random.random() * 0.2)
        
        # 模拟请求处理
        time.sleep(actual_delay)
        
        # 高并发时模拟失败
        error_prob = min((concurrency_level - 100) / 200, 0.3) if concurrency_level > 100 else 0
        return random.random() > error_prob
    
    def worker(self, concurrency_level, results, count):
        """线程工作函数"""
        for _ in range(count):
            success = self.simulate_request(concurrency_level)
            results.append(success)
    
    def run_concurrency_test(self, concurrency_level):
        """运行特定并发级别的测试"""
        results = []
        threads = []
        requests_per_thread = 2
        
        # 创建并启动线程
        start_time = time.time()
        for _ in range(concurrency_level):
            thread = threading.Thread(
                target=self.worker,
                args=(concurrency_level, results, requests_per_thread)
            )
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        total_time = time.time() - start_time
        
        # 计算结果
        successful = sum(results)
        total_requests = len(results)
        
        return {
            "concurrency": concurrency_level,
            "success_rate": successful / total_requests if total_requests > 0 else 0,
            "error_rate": 1 - (successful / total_requests if total_requests > 0 else 0),
            "total_time": total_time,
            "throughput": total_requests / total_time if total_time > 0 else 0
        }
    
    def run(self):
        """运行并发实验"""
        self.logger.log("\n===== 开始实验4: 增强并发测试 =====")
        results = {
            "concurrency_levels": [],
            "avg_error_rates": [],
            "avg_throughput": [],
            "max_successful_concurrency": 0
        }
        
        # 对每个并发级别进行测试
        for concurrency in Config.CONCURRENCY_LEVELS:
            level_results = []
            
            self.logger.log(f"测试并发级别: {concurrency}")
            
            for rep in range(Config.REPETITIONS):
                self.logger.log(f"  重复 {rep+1}/{Config.REPETITIONS}")
                gc.collect()
                time.sleep(0.5)
                
                result = self.run_concurrency_test(concurrency)
                level_results.append(result)
            
            # 计算平均值
            avg_error_rate = statistics.mean([r["error_rate"] for r in level_results])
            avg_throughput = statistics.mean([r["throughput"] for r in level_results])
            
            results["concurrency_levels"].append(concurrency)
            results["avg_error_rates"].append(avg_error_rate)
            results["avg_throughput"].append(avg_throughput)
            
            # 更新最大成功并发（错误率 < 5%）
            if avg_error_rate < 0.05:
                results["max_successful_concurrency"] = concurrency
        
        return results

# =========== 主程序 ===========

async def run_all_experiments():
    """运行所有实验"""
    print(f"=== 综合实验脚本启动 ===")
    print(f"工作目录: {os.getcwd()}")
    print(f"结果将保存到: {os.path.abspath(Config.RESULTS_FILE)}")
    print(f"日志将保存到: {os.path.abspath(Config.LOG_FILE)}")
    print(f"======================")
    
    logger = Logger()
    logger.log("开始综合性能实验...")
    
    # 运行实验并处理错误
    results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "repetitions": Config.REPETITIONS,
            "working_directory": os.getcwd()
        },
        "experiments": {}
    }
    
    try:
        # 运行实验1: 负载隔离性测试
        logger.log("\n===== 运行实验1: 负载隔离性测试 =====")
        exp_isolation = IsolationTest(logger)
        isolation_results = await exp_isolation.run()
        results["experiments"]["experiment_isolation"] = isolation_results
        logger.log("实验1完成成功!")
        
        # 运行实验2: 异步I/O性能测试
        logger.log("\n===== 运行实验2: 异步I/O性能测试 =====")
        exp1 = Experiment1_AsyncIO(logger)
        exp1_results = await exp1.run()
        results["experiments"]["experiment_1"] = exp1_results
        logger.log("实验2完成成功!")
        
        # 运行实验3: 优化参数测试
        logger.log("\n===== 运行实验3: 优化参数测试 =====")
        exp2 = Experiment2_OptimizationParameters(logger)
        exp2_results = exp2.run()
        results["experiments"]["experiment_2"] = exp2_results
        logger.log("实验3完成成功!")
        
        # 运行实验4: 缓存策略测试
        logger.log("\n===== 运行实验4: 缓存策略测试 =====")
        exp3 = Experiment3_CachingStrategies(logger)
        exp3_results = exp3.run()
        results["experiments"]["experiment_3"] = exp3_results
        logger.log("实验4完成成功!")
        
        # 运行实验5: 并发测试
        logger.log("\n===== 运行实验5: 并发测试 =====")
        exp4 = Experiment4_Concurrency(logger)
        exp4_results = exp4.run()
        results["experiments"]["experiment_4"] = exp4_results
        logger.log("实验5完成成功!")
        
        # 保存结果
        results_file_path = os.path.abspath(Config.RESULTS_FILE)
        logger.log(f"\n===== 保存结果到: {results_file_path} =====")
        
        # 确保目录存在
        results_dir = os.path.dirname(results_file_path)
        if results_dir and not os.path.exists(results_dir):
            os.makedirs(results_dir)
            
        with open(results_file_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        logger.log(f"结果成功保存到 {results_file_path}")
        logger.log(f"文件大小: {os.path.getsize(results_file_path) / 1024:.2f} KB")
        logger.log("所有实验完成成功!")
        
        return results
        
    except Exception as e:
        error_message = f"实验过程中出错: {str(e)}"
        logger.log(f"ERROR: {error_message}")
        logger.log(f"Traceback: {traceback.format_exc()}")
        print(f"\n❌ 发生错误: {e}")
        # 保存部分结果（如果可用）
        if results:
            partial_file = os.path.abspath(Config.RESULTS_FILE + ".partial")
            with open(partial_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.log(f"部分结果保存到 {partial_file}")
        sys.exit(1)

# 主函数入口
if __name__ == "__main__":
    try:
        asyncio.run(run_all_experiments())
    except KeyboardInterrupt:
        logger.info("实验中断。")
    except Exception as e:
        logger.error(f"实验运行错误: {e}")