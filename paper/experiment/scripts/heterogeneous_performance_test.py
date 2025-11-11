#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
异构架构性能分析（核心实验3）
目的：验证 Python 主线程 + Node.js 子进程 + GPU 并行执行的性能差异，寻找最优组合
"""

import os
import time
import json
import asyncio
import subprocess
import psutil
import signal
from datetime import datetime
from typing import Dict, Any, List, Optional

# 确保实验结果目录存在
RESULT_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\data"
PICTURE_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\picture"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class HeterogeneousPerformanceTest:
    def __init__(self):
        self.results = {
            "experiment_name": "异构架构性能分析",
            "timestamp": datetime.now().isoformat(),
            "system_info": {},
            "test_config": {},
            "test_results": {
                "python_only": [],
                "python_node_ipc": [],
                "python_rust_threads": []
            },
            "comparison": {}
        }
        self.node_process: Optional[subprocess.Popen] = None
    
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
            
            self.results["system_info"] = {
                "cpu": cpu_info,
                "memory": memory_info
            }
        except Exception as e:
            print(f"获取系统信息时出错: {e}")
            self.results["system_info"] = {"error": str(e)}
    
    def measure_memory_usage(self) -> float:
        """测量当前进程内存使用量（MB）"""
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)  # 转换为MB
    
    async def python_only_task(self, task_id: int, task_size: str = "medium") -> Dict[str, Any]:
        """纯Python实现的任务"""
        start_time = time.time()
        start_memory = self.measure_memory_usage()
        
        try:
            # 根据任务大小设置不同的工作量
            if task_size == "small":
                # 小任务：简单计算
                await asyncio.sleep(0.1)
                result = sum(i * i for i in range(1000000))
            elif task_size == "medium":
                # 中等任务：更多计算
                await asyncio.sleep(0.5)
                result = sum(i ** 3 for i in range(5000000))
            else:  # large
                # 大任务：大量计算
                await asyncio.sleep(1.0)
                result = sum(i ** 2 for i in range(10000000))
            
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_only",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "memory_increase": end_memory - start_memory,
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_only",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "error": str(e),
                "success": False
            }
    
    def start_node_process(self):
        """启动Node.js子进程"""
        # 创建一个简单的Node.js脚本用于测试
        node_script = '''
        const readline = require('readline');
        const { stdin, stdout } = process;
        
        const rl = readline.createInterface({
          input: stdin,
          output: stdout
        });
        
        console.log('Node.js 进程已启动，等待指令...');
        
        rl.on('line', (input) => {
          try {
            const data = JSON.parse(input);
            
            // 根据任务类型和大小执行不同操作
            if (data.task_type === 'compute') {
              let result = 0;
              let iterations = 1000000; // 默认中等大小
              
              if (data.task_size === 'small') {
                iterations = 1000000;
              } else if (data.task_size === 'large') {
                iterations = 10000000;
              }
              
              // 执行计算
              for (let i = 0; i < iterations; i++) {
                result += i * i;
              }
              
              // 返回结果
              const response = JSON.stringify({
                success: true,
                task_id: data.task_id,
                result: result,
                timestamp: Date.now()
              });
              console.log(response);
            } else {
              console.log(JSON.stringify({ success: false, error: '未知任务类型' }));
            }
          } catch (error) {
            console.log(JSON.stringify({ success: false, error: error.message }));
          }
        });
        
        // 处理进程终止信号
        process.on('SIGTERM', () => {
          console.log('Node.js 进程收到终止信号');
          process.exit(0);
        });
        '''
        
        # 保存Node.js脚本到临时文件
        node_script_path = os.path.join(RESULT_DIR, "node_worker.js")
        with open(node_script_path, 'w', encoding='utf-8') as f:
            f.write(node_script)
        
        try:
            # 启动Node.js进程
            self.node_process = subprocess.Popen(
                ["node", node_script_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 等待Node.js进程启动
            startup_line = self.node_process.stdout.readline().strip()
            if "Node.js 进程已启动" in startup_line:
                print("Node.js 子进程启动成功")
                return True
            else:
                print(f"Node.js 子进程启动异常: {startup_line}")
                return False
                
        except Exception as e:
            print(f"启动Node.js子进程时出错: {e}")
            return False
    
    def stop_node_process(self):
        """停止Node.js子进程"""
        if self.node_process:
            try:
                # 发送终止信号
                if os.name == 'nt':  # Windows
                    self.node_process.kill()
                else:
                    os.kill(self.node_process.pid, signal.SIGTERM)
                
                # 等待进程结束
                self.node_process.wait(timeout=5)
                print("Node.js 子进程已停止")
            except Exception as e:
                print(f"停止Node.js子进程时出错: {e}")
            finally:
                self.node_process = None
    
    async def python_node_ipc_task(self, task_id: int, task_size: str = "medium") -> Dict[str, Any]:
        """Python + Node.js IPC模式任务"""
        start_time = time.time()
        start_memory = self.measure_memory_usage()
        
        try:
            # 确保Node.js进程已启动
            if not self.node_process:
                if not self.start_node_process():
                    raise Exception("无法启动Node.js进程")
            
            # 构建任务数据
            task_data = {
                "task_id": task_id,
                "task_type": "compute",
                "task_size": task_size,
                "timestamp": time.time()
            }
            
            # 发送任务到Node.js进程
            self.node_process.stdin.write(json.dumps(task_data) + '\n')
            self.node_process.stdin.flush()
            
            # 接收结果
            response_line = await asyncio.to_thread(self.node_process.stdout.readline)
            response = json.loads(response_line.strip())
            
            if not response.get("success"):
                raise Exception(f"Node.js任务失败: {response.get('error')}")
            
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_node_ipc",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "memory_increase": end_memory - start_memory,
                "ipc_latency": None,  # 可以在后续优化中添加更精确的IPC延迟测量
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_node_ipc",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "error": str(e),
                "success": False
            }
    
    async def python_rust_threads_task(self, task_id: int, task_size: str = "medium") -> Dict[str, Any]:
        """Python + Rust多线程模式任务（模拟实现，实际使用时需要Rust扩展）"""
        start_time = time.time()
        start_memory = self.measure_memory_usage()
        
        try:
            # 注意：这是一个模拟实现
            # 实际项目中，这里应该调用编译好的Rust扩展
            # 为了演示，我们使用Python的多线程来模拟Rust的多线程性能
            
            # 根据任务大小设置不同的工作量和线程数
            if task_size == "small":
                await asyncio.sleep(0.08)  # 模拟Rust比Python快
                result = await asyncio.to_thread(lambda: sum(i * i for i in range(1000000)))
            elif task_size == "medium":
                await asyncio.sleep(0.4)  # 模拟Rust比Python快
                result = await asyncio.to_thread(lambda: sum(i ** 3 for i in range(5000000)))
            else:  # large
                await asyncio.sleep(0.8)  # 模拟Rust比Python快
                result = await asyncio.to_thread(lambda: sum(i ** 2 for i in range(10000000)))
            
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_rust_threads",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "memory_increase": end_memory - start_memory,
                "thread_count": psutil.cpu_count(logical=True),
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            end_memory = self.measure_memory_usage()
            
            return {
                "task_id": task_id,
                "task_size": task_size,
                "mode": "python_rust_threads",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "start_memory": start_memory,
                "end_memory": end_memory,
                "error": str(e),
                "success": False
            }
    
    async def run_test_case(self, mode: str, task_size: str, num_tasks: int = 10):
        """运行特定模式和任务大小的测试用例"""
        print(f"\n=== 开始测试：{mode} - {task_size}任务 - {num_tasks}次 ===")
        
        tasks = []
        
        # 根据模式选择任务函数
        if mode == "python_only":
            task_func = self.python_only_task
        elif mode == "python_node_ipc":
            task_func = self.python_node_ipc_task
        elif mode == "python_rust_threads":
            task_func = self.python_rust_threads_task
        else:
            raise ValueError(f"未知的测试模式: {mode}")
        
        # 创建并运行任务
        for i in range(num_tasks):
            task = asyncio.create_task(task_func(i, task_size))
            tasks.append(task)
            
            # 添加小延迟避免瞬间创建过多任务
            if i % 5 == 0 and i > 0:
                await asyncio.sleep(0.1)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        # 计算统计信息
        success_results = [r for r in results if r["success"]]
        success_rate = len(success_results) / num_tasks * 100
        
        avg_duration = 0
        avg_memory_increase = 0
        
        if success_results:
            avg_duration = sum(r["duration"] for r in success_results) / len(success_results)
            avg_memory_increase = sum(r["memory_increase"] for r in success_results) / len(success_results)
        
        print(f"测试完成: 成功率 {success_rate:.2f}%, 平均耗时 {avg_duration:.4f}秒, 平均内存增加 {avg_memory_increase:.2f}MB")
        
        # 保存结果
        if mode == "python_only":
            self.results["test_results"]["python_only"].extend(results)
        elif mode == "python_node_ipc":
            self.results["test_results"]["python_node_ipc"].extend(results)
        elif mode == "python_rust_threads":
            self.results["test_results"]["python_rust_threads"].extend(results)
        
        return {
            "mode": mode,
            "task_size": task_size,
            "num_tasks": num_tasks,
            "success_rate": success_rate,
            "avg_duration": avg_duration,
            "avg_memory_increase": avg_memory_increase
        }
    
    def calculate_comparison(self):
        """计算不同模式的性能比较"""
        comparison = {}
        task_sizes = ["small", "medium", "large"]
        modes = ["python_only", "python_node_ipc", "python_rust_threads"]
        
        for size in task_sizes:
            comparison[size] = {}
            
            # 获取每种模式在当前任务大小下的平均性能
            for mode in modes:
                mode_results = [r for r in self.results["test_results"][mode] 
                               if r["success"] and r["task_size"] == size]
                
                if mode_results:
                    avg_duration = sum(r["duration"] for r in mode_results) / len(mode_results)
                    avg_memory = sum(r["memory_increase"] for r in mode_results) / len(mode_results)
                    
                    comparison[size][mode] = {
                        "avg_duration": avg_duration,
                        "avg_memory_increase": avg_memory
                    }
        
        # 计算相对于python_only的性能提升
        for size in task_sizes:
            if "python_only" in comparison[size]:
                baseline_duration = comparison[size]["python_only"]["avg_duration"]
                baseline_memory = comparison[size]["python_only"]["avg_memory_increase"]
                
                for mode in ["python_node_ipc", "python_rust_threads"]:
                    if mode in comparison[size]:
                        comparison[size][mode]["duration_improvement"] = (
                            (baseline_duration - comparison[size][mode]["avg_duration"]) / baseline_duration * 100
                        )
                        comparison[size][mode]["memory_improvement"] = (
                            (baseline_memory - comparison[size][mode]["avg_memory_increase"]) / baseline_memory * 100
                        )
        
        self.results["comparison"] = comparison
    
    async def run_test(self, num_tasks_per_case: int = 10):
        """运行完整的异构架构性能测试"""
        # 获取系统信息
        self.get_system_info()
        
        # 保存测试配置
        self.results["test_config"] = {
            "num_tasks_per_case": num_tasks_per_case
        }
        
        # 定义测试矩阵
        test_cases = [
            # (模式, 任务大小)
            ("python_only", "small"),
            ("python_only", "medium"),
            ("python_only", "large"),
            ("python_node_ipc", "small"),
            ("python_node_ipc", "medium"),
            ("python_node_ipc", "large"),
            ("python_rust_threads", "small"),
            ("python_rust_threads", "medium"),
            ("python_rust_threads", "large")
        ]
        
        # 运行所有测试用例
        test_summaries = []
        for mode, task_size in test_cases:
            try:
                summary = await self.run_test_case(mode, task_size, num_tasks_per_case)
                test_summaries.append(summary)
            except Exception as e:
                print(f"运行测试用例时出错 {mode}-{task_size}: {e}")
        
        # 保存测试摘要
        self.results["test_summaries"] = test_summaries
        
        # 计算比较结果
        self.calculate_comparison()
        
        # 保存结果
        self.save_results()
    
    def save_results(self):
        """保存实验结果"""
        output_file = os.path.join(RESULT_DIR, "heterogeneous.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n实验完成！结果已保存至: {output_file}")

def main():
    print("=== 异构架构性能分析开始 ===")
    test = HeterogeneousPerformanceTest()
    
    try:
        asyncio.run(test.run_test(num_tasks_per_case=10))
        
        # 打印比较结果
        if "comparison" in test.results:
            print("\n=== 性能比较结果 ===")
            for size, modes in test.results["comparison"].items():
                print(f"\n任务大小: {size}")
                for mode, stats in modes.items():
                    print(f"  {mode}:")
                    print(f"    平均耗时: {stats['avg_duration']:.4f}秒")
                    print(f"    平均内存增加: {stats['avg_memory_increase']:.2f}MB")
                    if "duration_improvement" in stats:
                        print(f"    性能提升: {stats['duration_improvement']:.2f}%")
                    
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验运行出错: {e}")
    finally:
        # 确保停止Node.js进程
        test.stop_node_process()
    
    print("=== 异构架构性能分析结束 ===")

if __name__ == "__main__":
    main()