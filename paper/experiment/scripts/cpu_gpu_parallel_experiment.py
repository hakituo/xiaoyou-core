#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CPU+GPU并行运行实验（核心实验5）
目的：验证在虚拟环境隔离的情况下，CPU和GPU并行运行语音、LLM和图像任务的性能表现
模拟多模态AI助手在不同硬件资源上的任务分配策略效果
"""

import os
import time
import json
import asyncio
import random
import subprocess
import psutil
import signal
from datetime import datetime
from typing import List, Dict, Any, Optional

# 确保实验结果目录存在
RESULT_DIR = "d:\AI\xiaoyou-core\paper\experiment\experiment_results\data"
PICTURE_DIR = "d:\AI\xiaoyou-core\paper\experiment\experiment_results\picture"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class CPU_GPU_Parallel_Experiment:
    def __init__(self):
        self.results = {
            "experiment_name": "CPU+GPU并行运行实验",
            "timestamp": datetime.now().isoformat(),
            "system_info": {},
            "test_config": {
                "virtual_environments": [
                    {"name": "venv_llm", "tasks": "LLM推理", "hardware": "GPU"},
                    {"name": "venv_voice", "tasks": "语音识别/合成", "hardware": "CPU/GPU"},
                    {"name": "venv_img", "tasks": "图像生成/识别", "hardware": "GPU"}
                ],
                "concurrency_levels": [1, 3, 5, 10],
                "task_types": ["llm", "voice", "image", "all"]
            },
            "experiment_results": [],
            "summary_metrics": {
                "avg_response_time": {},
                "throughput": {},
                "resource_utilization": {}
            }
        }
        self.running_processes = []
        self.start_time = 0
        self.task_counter = 0
    
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
                "total_gb": round(mem_info.total / (1024**3), 2),
                "available_gb": round(mem_info.available / (1024**3), 2),
                "percent": mem_info.percent
            }
            
            # GPU信息（通过nvidia-smi获取）
            gpu_info = []
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.strip().split(', ')
                            if len(parts) >= 3:
                                gpu_info.append({
                                    "name": parts[0],
                                    "total_memory_mb": int(parts[1]),
                                    "used_memory_mb": int(parts[2])
                                })
            except Exception as e:
                print(f"获取GPU信息失败: {e}")
            
            self.results["system_info"] = {
                "cpu": cpu_info,
                "memory": memory_info,
                "gpu": gpu_info,
                "os": os.name,
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            }
        except Exception as e:
            print(f"获取系统信息失败: {e}")
    
    def get_resource_metrics(self) -> Dict[str, Any]:
        """获取资源使用指标"""
        metrics = {
            "cpu_usage": psutil.cpu_percent(interval=0.1),
            "memory_usage_percent": psutil.virtual_memory().percent,
            "memory_usage_gb": round(psutil.virtual_memory().used / (1024**3), 2),
            "timestamp": time.time()
        }
        
        # GPU使用情况
        gpu_metrics = []
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for i, line in enumerate(result.stdout.strip().split('\n')):
                    if line.strip():
                        parts = line.strip().split(', ')
                        if len(parts) >= 2:
                            gpu_metrics.append({
                                "gpu_id": i,
                                "utilization_percent": int(parts[0]),
                                "used_memory_mb": int(parts[1])
                            })
        except Exception as e:
            pass
        
        if gpu_metrics:
            metrics["gpu"] = gpu_metrics
        
        return metrics
    
    async def run_virtual_env_task(self, env_name: str, task_type: str, task_id: int) -> Dict[str, Any]:
        """在指定虚拟环境中运行任务"""
        start_time = time.time()
        task_result = {
            "task_id": task_id,
            "env_name": env_name,
            "task_type": task_type,
            "start_time": start_time,
            "status": "failed"
        }
        
        try:
            # 根据虚拟环境和任务类型选择Python解释器路径
            env_paths = {
                "venv_llm": "d:\\AI\\xiaoyou-core\\venv_llm\\Scripts\\python.exe",
                "venv_voice": "d:\\AI\\xiaoyou-core\\venv_voice\\Scripts\\python.exe",
                "venv_img": "d:\\AI\\xiaoyou-core\\venv_img\\Scripts\\python.exe"
            }
            
            if env_name not in env_paths:
                raise ValueError(f"未知的虚拟环境: {env_name}")
            
            python_exe = env_paths[env_name]
            
            # 生成任务脚本内容
            script_content = self._generate_task_script(task_type)
            
            # 写入临时脚本文件
            temp_script = f"temp_task_{task_id}.py"
            with open(temp_script, "w", encoding="utf-8") as f:
                f.write(script_content)
            
            # 运行任务
            process = await asyncio.create_subprocess_exec(
                python_exe,
                temp_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.running_processes.append(process)
            
            stdout, stderr = await process.communicate()
            
            # 移除临时文件
            try:
                if os.path.exists(temp_script):
                    os.remove(temp_script)
            except:
                pass
            
            end_time = time.time()
            task_result.update({
                "end_time": end_time,
                "duration": end_time - start_time,
                "stdout": stdout.decode('utf-8', errors='ignore'),
                "stderr": stderr.decode('utf-8', errors='ignore'),
                "status": "success" if process.returncode == 0 else "failed",
                "returncode": process.returncode
            })
            
        except Exception as e:
            end_time = time.time()
            task_result.update({
                "end_time": end_time,
                "duration": end_time - start_time,
                "error": str(e),
                "status": "failed"
            })
        
        return task_result
    
    def _generate_task_script(self, task_type: str) -> str:
        """生成任务脚本内容"""
        scripts = {
            "llm": """
import time
import random

# 模拟LLM推理任务（GPU密集型）
print(f"开始LLM推理任务，时间: {time.time()}")

# 模拟计算密集型操作
def simulate_llm_inference():
    result = 0
    for i in range(10000000):
        result += i * random.random()
    return result

# 执行模拟任务
result = simulate_llm_inference()
print(f"LLM推理完成，结果特征: {result % 100}")
print(f"任务完成时间: {time.time()}")
""",
            "voice": """
import time
import numpy as np

# 模拟语音处理任务（CPU/GPU混合）
print(f"开始语音处理任务，时间: {time.time()}")

# 模拟语音数据处理
def simulate_voice_processing():
    # 生成模拟音频数据
    audio_data = np.random.randn(16000 * 3)  # 3秒音频
    
    # 模拟特征提取和处理
    for i in range(100):
        features = np.fft.fft(audio_data[:1000])
        
    # 模拟语音识别/合成逻辑
    time.sleep(0.5)  # 模拟I/O等待
    
    return "模拟识别结果"

# 执行模拟任务
result = simulate_voice_processing()
print(f"语音处理完成，结果: {result}")
print(f"任务完成时间: {time.time()}")
""",
            "image": """
import time
import numpy as np

# 模拟图像处理任务（GPU密集型）
print(f"开始图像处理任务，时间: {time.time()}")

# 模拟图像处理
def simulate_image_processing():
    # 生成模拟图像数据
    image = np.random.rand(512, 512, 3)
    
    # 模拟卷积操作和特征提取
    for _ in range(50):
        # 模拟卷积层计算
        for i in range(100):
            feature = np.sum(image[i:i+10, i:i+10, :])
    
    # 模拟生成操作
    time.sleep(0.3)
    
    return "模拟图像结果"

# 执行模拟任务
result = simulate_image_processing()
print(f"图像处理完成")
print(f"任务完成时间: {time.time()}")
"""
        }
        
        return scripts.get(task_type, "print('未知任务类型')")
    
    async def run_concurrent_tasks(self, concurrency: int, task_type: str) -> Dict[str, Any]:
        """运行并发任务"""
        print(f"开始测试 - 并发数: {concurrency}, 任务类型: {task_type}")
        
        test_start_time = time.time()
        tasks = []
        
        # 根据任务类型选择要运行的环境和任务
        if task_type == "all":
            # 混合任务：每个虚拟环境运行不同类型的任务
            for i in range(concurrency):
                env_index = i % 3
                envs = [("venv_llm", "llm"), ("venv_voice", "voice"), ("venv_img", "image")]
                env_name, task = envs[env_index]
                tasks.append(self.run_virtual_env_task(env_name, task, self.task_counter))
                self.task_counter += 1
        else:
            # 单一任务类型
            env_map = {
                "llm": "venv_llm",
                "voice": "venv_voice",
                "image": "venv_img"
            }
            env_name = env_map.get(task_type)
            if not env_name:
                raise ValueError(f"未知的任务类型: {task_type}")
            
            for i in range(concurrency):
                tasks.append(self.run_virtual_env_task(env_name, task_type, self.task_counter))
                self.task_counter += 1
        
        # 并发执行所有任务
        results = await asyncio.gather(*tasks)
        
        test_end_time = time.time()
        test_duration = test_end_time - test_start_time
        
        # 计算性能指标
        successful_tasks = [r for r in results if r["status"] == "success"]
        avg_duration = sum(r["duration"] for r in successful_tasks) / len(successful_tasks) if successful_tasks else 0
        throughput = len(successful_tasks) / test_duration if test_duration > 0 else 0
        
        # 收集资源使用情况
        resource_metrics = self.get_resource_metrics()
        
        return {
            "concurrency": concurrency,
            "task_type": task_type,
            "start_time": test_start_time,
            "end_time": test_end_time,
            "duration": test_duration,
            "total_tasks": len(tasks),
            "successful_tasks": len(successful_tasks),
            "success_rate": len(successful_tasks) / len(tasks) * 100 if tasks else 0,
            "avg_task_duration": avg_duration,
            "throughput": throughput,
            "resource_metrics": resource_metrics,
            "task_results": results
        }
    
    async def run_test(self, concurrency_levels: List[int] = None, task_types: List[str] = None):
        """运行完整测试"""
        # 使用默认配置或自定义配置
        if concurrency_levels is None:
            concurrency_levels = self.results["test_config"]["concurrency_levels"]
        if task_types is None:
            task_types = self.results["test_config"]["task_types"]
        
        # 获取系统信息
        self.get_system_info()
        
        # 预热系统
        print("开始系统预热...")
        warmup_results = await self.run_concurrent_tasks(1, "voice")
        print("系统预热完成")
        
        # 运行所有测试用例
        for task_type in task_types:
            for concurrency in concurrency_levels:
                # 运行测试
                result = await self.run_concurrent_tasks(concurrency, task_type)
                self.results["experiment_results"].append(result)
                
                # 打印进度
                print(f"完成测试 - 任务类型: {task_type}, 并发数: {concurrency}")
                print(f"  成功率: {result['success_rate']:.2f}%")
                print(f"  平均耗时: {result['avg_task_duration']:.2f}秒")
                print(f"  吞吐量: {result['throughput']:.2f}任务/秒")
                
                # 短暂休息，避免系统过热
                await asyncio.sleep(2)
        
        # 计算汇总指标
        self._calculate_summary_metrics()
        
        # 保存结果
        self.save_results()
    
    def _calculate_summary_metrics(self):
        """计算汇总指标"""
        # 按任务类型分组统计
        by_task_type = {}
        for result in self.results["experiment_results"]:
            task_type = result["task_type"]
            if task_type not in by_task_type:
                by_task_type[task_type] = []
            by_task_type[task_type].append(result)
        
        # 计算各任务类型的平均响应时间和吞吐量
        for task_type, results in by_task_type.items():
            avg_duration = sum(r["avg_task_duration"] for r in results) / len(results)
            total_throughput = sum(r["throughput"] for r in results)
            
            self.results["summary_metrics"]["avg_response_time"][task_type] = avg_duration
            self.results["summary_metrics"]["throughput"][task_type] = total_throughput / len(results)
        
        # 汇总资源使用情况
        cpu_usages = []
        memory_usages = []
        gpu_usages = []
        
        for result in self.results["experiment_results"]:
            metrics = result["resource_metrics"]
            cpu_usages.append(metrics.get("cpu_usage", 0))
            memory_usages.append(metrics.get("memory_usage_percent", 0))
            
            if "gpu" in metrics:
                for gpu in metrics["gpu"]:
                    gpu_usages.append(gpu.get("utilization_percent", 0))
        
        self.results["summary_metrics"]["resource_utilization"] = {
            "avg_cpu_usage": sum(cpu_usages) / len(cpu_usages) if cpu_usages else 0,
            "avg_memory_usage": sum(memory_usages) / len(memory_usages) if memory_usages else 0,
            "avg_gpu_usage": sum(gpu_usages) / len(gpu_usages) if gpu_usages else 0
        }
    
    def save_results(self):
        """保存实验结果"""
        result_file = os.path.join(RESULT_DIR, "cpu_gpu_parallel_results.json")
        
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"实验结果已保存至: {result_file}")
        print("\n===== 实验汇总 =====")
        print(f"平均响应时间:")
        for task_type, avg_time in self.results["summary_metrics"]["avg_response_time"].items():
            print(f"  {task_type}: {avg_time:.2f}秒")
        print(f"\n吞吐量:")
        for task_type, throughput in self.results["summary_metrics"]["throughput"].items():
            print(f"  {task_type}: {throughput:.2f}任务/秒")
        print(f"\n资源利用率:")
        print(f"  CPU: {self.results['summary_metrics']['resource_utilization']['avg_cpu_usage']:.2f}%")
        print(f"  内存: {self.results['summary_metrics']['resource_utilization']['avg_memory_usage']:.2f}%")
        print(f"  GPU: {self.results['summary_metrics']['resource_utilization']['avg_gpu_usage']:.2f}%")
    
    def clean_up(self):
        """清理资源"""
        for process in self.running_processes:
            try:
                if process.returncode is None:
                    process.terminate()
                    process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass

async def main():
    experiment = CPU_GPU_Parallel_Experiment()
    
    try:
        print("=== CPU+GPU并行运行实验开始 ===")
        # 运行测试，可以自定义并发级别和任务类型
        await experiment.run_test(
            concurrency_levels=[1, 3, 5],  # 可以根据需要调整
            task_types=["llm", "voice", "image", "all"]
        )
        print("\n=== CPU+GPU并行运行实验完成 ===")
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        experiment.clean_up()

if __name__ == "__main__":
    import sys
    # 检查Python版本是否支持异步
    if sys.version_info < (3, 7):
        print("错误: 需要Python 3.7或更高版本")
        sys.exit(1)
    
    # 运行主函数
    asyncio.run(main())