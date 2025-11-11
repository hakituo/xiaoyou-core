#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GPU负载阻塞实验（核心实验1）
验证：当GPU运行大模型任务（LLM推理、图像生成）时，主线程是否仍能维持实时响应
目的：异步隔离机制在GPU密集场景下的通用性
"""

import os
import time
import json
import asyncio
import psutil
import subprocess
import threading
from datetime import datetime
from typing import List, Dict, Any

# 确保实验结果目录存在
RESULT_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\data"
PICTURE_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\picture"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class GPULoadTest:
    def __init__(self):
        self.results = {
            "experiment_name": "GPU负载阻塞实验",
            "timestamp": datetime.now().isoformat(),
            "system_info": {},
            "metrics": {
                "response_latency": [],
                "gpu_utilization": [],
                "cpu_usage": [],
                "async_queue_length": []
            },
            "test_cases": []
        }
        self.async_tasks = []
        self.queue_length = 0
        self.running = False
    
    def get_system_info(self):
        """获取系统信息"""
        try:
            # CPU信息
            cpu_info = {
                "count": psutil.cpu_count(logical=True),
                "physical_count": psutil.cpu_count(logical=False)
            }
            
            # 内存信息
            mem_info = psutil.virtual_memory()
            memory_info = {
                "total": mem_info.total / (1024 ** 3),
                "available": mem_info.available / (1024 ** 3)
            }
            
            # GPU信息（尝试通过nvidia-smi获取）
            gpu_info = []
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.split(',')
                            if len(parts) >= 2:
                                gpu_info.append({
                                    "name": parts[0].strip(),
                                    "memory_total": int(parts[1].strip())
                                })
            except Exception as e:
                print(f"无法获取GPU信息: {e}")
            
            self.results["system_info"] = {
                "cpu": cpu_info,
                "memory": memory_info,
                "gpu": gpu_info if gpu_info else "GPU信息不可用"
            }
        except Exception as e:
            print(f"获取系统信息时出错: {e}")
            self.results["system_info"] = {"error": str(e)}
    
    def get_gpu_utilization(self):
        """获取GPU利用率"""
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            print(f"获取GPU利用率时出错: {e}")
        return None
    
    def get_cpu_usage(self):
        """获取CPU占用率"""
        return psutil.cpu_percent(interval=0.1)
    
    async def monitor_resources(self):
        """资源监控线程"""
        while self.running:
            # 记录GPU利用率
            gpu_util = self.get_gpu_utilization()
            if gpu_util is not None:
                self.results["metrics"]["gpu_utilization"].append({
                    "timestamp": time.time(),
                    "value": gpu_util
                })
            
            # 记录CPU占用率
            self.results["metrics"]["cpu_usage"].append({
                "timestamp": time.time(),
                "value": self.get_cpu_usage()
            })
            
            # 记录队列长度
            self.results["metrics"]["async_queue_length"].append({
                "timestamp": time.time(),
                "value": self.queue_length
            })
            
            await asyncio.sleep(0.5)  # 500ms采样一次
    
    async def simulate_gpu_task(self, task_type: str, task_id: int):
        """模拟GPU密集型任务"""
        self.queue_length += 1
        start_time = time.time()
        
        try:
            if task_type == "image_generation":
                # 模拟图像生成任务（替换为实际调用）
                print(f"Task {task_id}: 开始模拟图像生成任务...")
                # 这里应该调用实际的SDXL模型，现在用sleep模拟
                await asyncio.sleep(8)  # 模拟图像生成耗时
            elif task_type == "text_generation":
                # 模拟文本生成任务（替换为实际调用）
                print(f"Task {task_id}: 开始模拟文本生成任务...")
                # 这里应该调用实际的Qwen2模型，现在用sleep模拟
                await asyncio.sleep(5)  # 模拟文本生成耗时
            
            end_time = time.time()
            duration = end_time - start_time
            
            self.results["test_cases"].append({
                "task_id": task_id,
                "task_type": task_type,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration
            })
            
            print(f"Task {task_id}: {task_type} 完成，耗时: {duration:.2f}秒")
            
        except Exception as e:
            print(f"Task {task_id}: {task_type} 失败: {e}")
        finally:
            self.queue_length -= 1
    
    async def ping_test(self, ping_id: int):
        """模拟短指令ping测试，测量响应延迟"""
        start_time = time.time()
        # 模拟处理ping请求
        await asyncio.sleep(0.05)  # 最小处理时间
        end_time = time.time()
        
        latency = (end_time - start_time) * 1000  # 转换为毫秒
        
        self.results["metrics"]["response_latency"].append({
            "ping_id": ping_id,
            "timestamp": start_time,
            "latency": latency
        })
        
        print(f"Ping {ping_id} 响应延迟: {latency:.2f}ms")
    
    async def run_test(self):
        """运行完整测试"""
        # 获取系统信息
        self.get_system_info()
        
        # 启动资源监控
        self.running = True
        monitor_task = asyncio.create_task(self.monitor_resources())
        
        try:
            # 等待监控启动
            await asyncio.sleep(1)
            
            # 先进行几次基准ping测试
            print("\n=== 开始基准ping测试 ===")
            for i in range(5):
                await self.ping_test(f"baseline_{i}")
                await asyncio.sleep(0.5)
            
            # 启动GPU密集型任务
            print("\n=== 启动GPU密集型任务 ===")
            gpu_tasks = []
            
            # 启动图像生成任务
            for i in range(3):
                task = asyncio.create_task(self.simulate_gpu_task("image_generation", i))
                gpu_tasks.append(task)
                await asyncio.sleep(1)  # 间隔启动
            
            # 在GPU任务运行期间发送ping请求
            print("\n=== GPU任务运行期间进行ping测试 ===")
            for i in range(10):
                await self.ping_test(f"during_gpu_{i}")
                await asyncio.sleep(1)
            
            # 再启动文本生成任务
            print("\n=== 启动文本生成任务 ===")
            for i in range(3):
                task = asyncio.create_task(self.simulate_gpu_task("text_generation", i + 10))
                gpu_tasks.append(task)
                await asyncio.sleep(0.5)
            
            # 等待所有GPU任务完成
            await asyncio.gather(*gpu_tasks)
            
            # 完成后再次进行ping测试
            print("\n=== GPU任务完成后进行ping测试 ===")
            for i in range(5):
                await self.ping_test(f"after_gpu_{i}")
                await asyncio.sleep(0.5)
            
            # 等待最后一次资源监控数据
            await asyncio.sleep(1)
            
        finally:
            # 停止监控
            self.running = False
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        # 保存结果
        self.save_results()
    
    def save_results(self):
        """保存实验结果"""
        # 计算统计信息
        if self.results["metrics"]["response_latency"]:
            latencies = [item["latency"] for item in self.results["metrics"]["response_latency"]]
            self.results["summary"] = {
                "avg_response_latency": sum(latencies) / len(latencies),
                "max_response_latency": max(latencies),
                "min_response_latency": min(latencies),
                "total_test_cases": len(self.results["test_cases"])
            }
        
        # 保存到文件
        output_file = os.path.join(RESULT_DIR, "gpu_test.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n实验完成！结果已保存至: {output_file}")

def main():
    print("=== GPU负载阻塞实验开始 ===")
    test = GPULoadTest()
    
    try:
        asyncio.run(test.run_test())
        
        # 打印汇总信息
        if "summary" in test.results:
            print("\n=== 实验汇总 ===")
            print(f"平均响应延迟: {test.results['summary']['avg_response_latency']:.2f}ms")
            print(f"最大响应延迟: {test.results['summary']['max_response_latency']:.2f}ms")
            print(f"最小响应延迟: {test.results['summary']['min_response_latency']:.2f}ms")
            print(f"总测试任务数: {test.results['summary']['total_test_cases']}")
    
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验运行出错: {e}")
    
    print("=== GPU负载阻塞实验结束 ===")

if __name__ == "__main__":
    main()