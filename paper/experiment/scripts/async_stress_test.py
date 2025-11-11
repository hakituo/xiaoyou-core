#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
异步架构压力测试（核心实验2）
目的：在多任务（图像生成 + 语音识别 + 文本应答）同时运行时，测试系统的稳定性和吞吐能力
"""

import os
import time
import json
import asyncio
import random
import psutil
from datetime import datetime
from typing import List, Dict, Any, Tuple

# 确保实验结果目录存在
RESULT_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\data"
PICTURE_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\picture"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class AsyncStressTest:
    def __init__(self):
        self.results = {
            "experiment_name": "异步架构压力测试",
            "timestamp": datetime.now().isoformat(),
            "test_config": {},
            "metrics": {
                "task_completion_times": [],
                "task_success_rates": [],
                "system_metrics": []
            },
            "task_results": []
        }
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.running_tasks = set()
        self.start_time = 0
    
    def get_system_metrics(self) -> Dict[str, float]:
        """获取系统指标"""
        return {
            "cpu_usage": psutil.cpu_percent(interval=0.1),
            "memory_usage": psutil.virtual_memory().percent,
            "running_tasks": len(self.running_tasks)
        }
    
    async def monitor_system(self):
        """监控系统资源使用情况"""
        while len(self.running_tasks) > 0 or self.total_tasks < self.results["test_config"]["total_tasks"]:
            metrics = self.get_system_metrics()
            metrics["timestamp"] = time.time()
            self.results["metrics"]["system_metrics"].append(metrics)
            await asyncio.sleep(1)
    
    async def simulate_task(self, task_id: int, task_type: str) -> Tuple[bool, float]:
        """模拟不同类型的异步任务"""
        self.running_tasks.add(task_id)
        start_time = time.time()
        success = True
        
        try:
            print(f"任务 {task_id} ({task_type}) 开始执行")
            
            if task_type == "text_generation":
                # 模拟文本生成任务
                # 实际使用时应替换为真实的LLM调用
                await asyncio.sleep(random.uniform(1.0, 3.0))
            
            elif task_type == "image_generation":
                # 模拟图像生成任务
                # 实际使用时应替换为真实的SDXL调用
                await asyncio.sleep(random.uniform(5.0, 10.0))
            
            elif task_type == "speech_synthesis":
                # 模拟语音合成任务
                # 实际使用时应替换为真实的TTS调用
                await asyncio.sleep(random.uniform(0.5, 2.0))
            
            # 模拟随机失败（1%概率）
            if random.random() < 0.01:
                raise Exception("模拟任务随机失败")
                
        except Exception as e:
            success = False
            print(f"任务 {task_id} ({task_type}) 失败: {e}")
        finally:
            end_time = time.time()
            duration = end_time - start_time
            self.running_tasks.remove(task_id)
            
            # 记录任务结果
            task_result = {
                "task_id": task_id,
                "task_type": task_type,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "success": success
            }
            self.task_results.append(task_result)
            
            # 更新统计
            if success:
                self.completed_tasks += 1
            else:
                self.failed_tasks += 1
            
            # 每完成10个任务打印一次进度
            if (self.completed_tasks + self.failed_tasks) % 10 == 0:
                progress = (self.completed_tasks + self.failed_tasks) / self.total_tasks * 100
                print(f"进度: {progress:.1f}% - 完成: {self.completed_tasks}, 失败: {self.failed_tasks}")
        
        return success, duration
    
    async def run_test_case(self, concurrency_level: int):
        """运行特定并发级别的测试"""
        print(f"\n=== 开始并发级别: {concurrency_level} 的测试 ===")
        
        # 重置计数器
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.running_tasks.clear()
        
        # 任务类型列表，按照实际使用场景设置权重
        task_types = ["text_generation", "image_generation", "speech_synthesis"]
        task_weights = [0.5, 0.3, 0.2]  # 文本生成占50%，图像生成30%，语音合成20%
        
        # 计算此并发级别下的任务数
        tasks_per_level = min(concurrency_level * 5, 500)  # 每并发级别最多500个任务
        
        # 启动系统监控
        monitor_task = asyncio.create_task(self.monitor_system())
        
        # 记录开始时间
        level_start_time = time.time()
        
        # 创建并启动任务
        tasks = []
        for i in range(tasks_per_level):
            task_id = i + 1
            self.total_tasks += 1
            # 根据权重随机选择任务类型
            task_type = random.choices(task_types, weights=task_weights)[0]
            
            # 控制并发数
            while len(self.running_tasks) >= concurrency_level:
                await asyncio.sleep(0.1)
            
            # 启动任务
            task = asyncio.create_task(self.simulate_task(task_id, task_type))
            tasks.append(task)
            
            # 添加小延迟避免瞬间创建过多任务
            if i % 10 == 0:
                await asyncio.sleep(0.01)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        # 等待监控结束
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        # 计算统计信息
        level_end_time = time.time()
        total_time = level_end_time - level_start_time
        success_count = sum(1 for success, _ in results if success)
        success_rate = (success_count / tasks_per_level) * 100 if tasks_per_level > 0 else 0
        
        # 计算平均延迟（仅考虑成功的任务）
        success_durations = [duration for success, duration in results if success]
        avg_duration = sum(success_durations) / len(success_durations) if success_durations else 0
        
        # 计算吞吐量（任务/秒）
        throughput = tasks_per_level / total_time if total_time > 0 else 0
        
        test_case_result = {
            "concurrency_level": concurrency_level,
            "total_tasks": tasks_per_level,
            "completed_tasks": success_count,
            "failed_tasks": tasks_per_level - success_count,
            "success_rate": success_rate,
            "total_duration": total_time,
            "average_task_duration": avg_duration,
            "throughput": throughput
        }
        
        self.results["metrics"]["task_completion_times"].append({
            "concurrency_level": concurrency_level,
            "avg_duration": avg_duration
        })
        
        self.results["metrics"]["task_success_rates"].append({
            "concurrency_level": concurrency_level,
            "success_rate": success_rate
        })
        
        print(f"并发级别 {concurrency_level} 测试完成")
        print(f"  成功任务数: {success_count}/{tasks_per_level}")
        print(f"  成功率: {success_rate:.2f}%")
        print(f"  总耗时: {total_time:.2f}秒")
        print(f"  平均任务耗时: {avg_duration:.2f}秒")
        print(f"  吞吐量: {throughput:.2f} 任务/秒")
        
        return test_case_result
    
    async def run_test(self, concurrency_levels: List[int] = None, total_test_runs: int = 100):
        """运行完整的压力测试"""
        # 默认并发级别
        if concurrency_levels is None:
            concurrency_levels = [10, 25, 50, 75, 100, 125, 150, 200]
        
        # 保存测试配置
        self.results["test_config"] = {
            "concurrency_levels": concurrency_levels,
            "total_tasks": 0,  # 将在测试过程中更新
            "total_test_runs": total_test_runs
        }
        
        # 记录整体开始时间
        self.start_time = time.time()
        
        # 运行各个并发级别的测试
        self.results["test_cases"] = []
        for level in concurrency_levels:
            test_result = await self.run_test_case(level)
            self.results["test_cases"].append(test_result)
            
            # 如果成功率低于80%，停止测试（找到了系统极限）
            if test_result["success_rate"] < 80:
                print(f"\n警告: 并发级别 {level} 的成功率低于80%，已达到系统处理极限")
                break
            
            # 添加短暂休息，让系统恢复
            await asyncio.sleep(5)
        
        # 更新总任务数
        self.results["test_config"]["total_tasks"] = self.total_tasks
        
        # 计算整体统计
        all_success_rates = [case["success_rate"] for case in self.results["test_cases"]]
        all_avg_durations = [case["average_task_duration"] for case in self.results["test_cases"]]
        all_throughputs = [case["throughput"] for case in self.results["test_cases"]]
        
        self.results["summary"] = {
            "total_duration": time.time() - self.start_time,
            "average_success_rate": sum(all_success_rates) / len(all_success_rates) if all_success_rates else 0,
            "average_task_duration": sum(all_avg_durations) / len(all_avg_durations) if all_avg_durations else 0,
            "peak_throughput": max(all_throughputs) if all_throughputs else 0,
            "max_stable_concurrency": self.results["test_cases"][-1]["concurrency_level"] if self.results["test_cases"] else 0
        }
        
        # 保存所有任务结果
        self.results["task_results"] = self.task_results
        
        # 保存结果
        self.save_results()
    
    def save_results(self):
        """保存实验结果"""
        output_file = os.path.join(RESULT_DIR, "stress_test.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n实验完成！结果已保存至: {output_file}")

def main():
    print("=== 异步架构压力测试开始 ===")
    test = AsyncStressTest()
    
    # 可以根据需要调整并发级别
    concurrency_levels = [10, 25, 50, 75, 100, 125, 150]
    
    try:
        asyncio.run(test.run_test(concurrency_levels))
        
        # 打印汇总信息
        if "summary" in test.results:
            print("\n=== 实验汇总 ===")
            print(f"总耗时: {test.results['summary']['total_duration']:.2f}秒")
            print(f"平均成功率: {test.results['summary']['average_success_rate']:.2f}%")
            print(f"平均任务耗时: {test.results['summary']['average_task_duration']:.2f}秒")
            print(f"峰值吞吐量: {test.results['summary']['peak_throughput']:.2f} 任务/秒")
            print(f"最大稳定并发: {test.results['summary']['max_stable_concurrency']}")
            
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验运行出错: {e}")
    
    print("=== 异步架构压力测试结束 ===")

if __name__ == "__main__":
    main()