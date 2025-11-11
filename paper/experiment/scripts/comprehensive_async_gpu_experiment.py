#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
综合异步GPU多模型运行实验
实验目的：验证CPU异步调度GPU多模型（LLM、图像生成、TTS、语音识别）的性能表现
实现架构：
  [CPU 主线程] → 接收请求
    ├─> [GPU LLM] → 生成文本
    ├─> [GPU 图像生成] → 输出图片
    └─> [GPU TTS/STT] → 处理语音
"""

import os
import time
import json
import asyncio
import psutil
import subprocess
import torch
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional
import threading

# 确保实验结果目录存在
RESULT_DIR = "d:\AI\xiaoyou-core\paper\experiment\experiment_results\data"
PICTURE_DIR = "d:\AI\xiaoyou-core\paper\experiment\experiment_results\picture"
MODEL_DIR = "d:\AI\xiaoyou-core\models"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class ComprehensiveAsyncGPUExperiment:
    def __init__(self):
        self.results = {
            "experiment_name": "CPU异步调度GPU多模型运行实验",
            "timestamp": datetime.now().isoformat(),
            "system_info": {},
            "metrics": {
                "main_thread_response": [],  # 主线程响应时间
                "gpu_memory_usage": [],      # GPU显存占用
                "cpu_usage": [],             # CPU使用率
                "async_queue_length": []     # 异步队列长度
            },
            "task_results": [],            # 各任务详细结果
            "concurrency_test_results": [] # 并发测试结果
        }
        self.async_tasks = []
        self.queue_length = 0
        self.running = False
        self.start_time = None
        self.gpu_available = self.check_gpu_availability()
        self.model_instances = {}
    
    def check_gpu_availability(self):
        """检查GPU是否可用"""
        try:
            return torch.cuda.is_available()
        except:
            return False
    
    def get_system_info(self):
        """获取系统信息"""
        try:
            # CPU信息
            cpu_info = {
                "count": psutil.cpu_count(logical=True),
                "physical_count": psutil.cpu_count(logical=False),
                "model": self.get_cpu_model()
            }
            
            # 内存信息
            mem_info = psutil.virtual_memory()
            memory_info = {
                "total": mem_info.total / (1024 ** 3),
                "available": mem_info.available / (1024 ** 3)
            }
            
            # GPU信息
            gpu_info = []
            if self.gpu_available:
                try:
                    result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", 
                                          "--format=csv,noheader,nounits"], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        for line in result.stdout.strip().split('\n'):
                            if line.strip():
                                parts = line.split(',')
                                if len(parts) >= 3:
                                    gpu_info.append({
                                        "name": parts[0].strip(),
                                        "memory_total": int(parts[1].strip()),
                                        "driver_version": parts[2].strip()
                                    })
                except Exception as e:
                    print(f"获取GPU详细信息时出错: {e}")
                    # 使用torch获取基本信息
                    gpu_info.append({
                        "name": torch.cuda.get_device_name(0),
                        "memory_total": torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                    })
            
            self.results["system_info"] = {
                "cpu": cpu_info,
                "memory": memory_info,
                "gpu": gpu_info if gpu_info else "GPU不可用",
                "python_version": f"Python {asyncio.get_event_loop()._debug if hasattr(asyncio.get_event_loop(), '_debug') else 'unknown'}",
                "torch_version": torch.__version__ if self.gpu_available else "不可用"
            }
        except Exception as e:
            print(f"获取系统信息时出错: {e}")
            self.results["system_info"] = {"error": str(e)}
    
    def get_cpu_model(self):
        """获取CPU型号"""
        try:
            if os.name == 'nt':  # Windows
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                   r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                return winreg.QueryValueEx(key, "ProcessorNameString")[0]
            else:  # Linux/macOS
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":")[1].strip()
        except:
            return "未知"
    
    def get_gpu_memory_usage(self):
        """获取GPU显存使用情况"""
        if not self.gpu_available:
            return None
        try:
            # 优先使用nvidia-smi获取显存使用
            result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", 
                                  "--format=csv,noheader,nounits"], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip():
                line = result.stdout.strip().split('\n')[0]
                parts = line.split(',')
                if len(parts) >= 2:
                    return {
                        "used": int(parts[0].strip()),
                        "total": int(parts[1].strip()),
                        "unit": "MB"
                    }
        except Exception as e:
            print(f"获取GPU显存使用时出错: {e}")
            
        # 使用torch作为备选
        try:
            return {
                "used": torch.cuda.memory_allocated(0) / (1024 ** 2),
                "total": torch.cuda.get_device_properties(0).total_memory / (1024 ** 2),
                "unit": "MB"
            }
        except:
            pass
        return None
    
    def get_cpu_usage(self):
        """获取CPU占用率"""
        return psutil.cpu_percent(interval=0.1)
    
    async def monitor_resources(self):
        """资源监控协程"""
        while self.running:
            # 记录GPU显存使用
            gpu_mem = self.get_gpu_memory_usage()
            if gpu_mem:
                self.results["metrics"]["gpu_memory_usage"].append({
                    "timestamp": time.time(),
                    "used": gpu_mem["used"],
                    "total": gpu_mem["total"],
                    "percentage": (gpu_mem["used"] / gpu_mem["total"]) * 100 if gpu_mem["total"] > 0 else 0
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
    
    async def initialize_models(self):
        """初始化模型（异步方式）"""
        print("正在初始化模型...")
        
        # 注意：实际环境中需要替换为真实的模型加载代码
        # 这里仅作为示例框架，实际使用时需要根据具体模型调整
        
        # 模拟模型加载延迟
        await asyncio.sleep(2)
        
        print("模型初始化完成")
    
    async def run_llm_task(self, task_id: int, prompt: str):
        """运行LLM文本生成任务"""
        self.queue_length += 1
        task_start = time.time()
        
        try:
            print(f"任务 {task_id}: 开始LLM文本生成 - {prompt[:30]}...")
            
            # 实际环境中，这里应该调用真实的Qwen模型
            # 例如: from transformers import AutoModelForCausalLM, AutoTokenizer
            # 但为了演示，我们使用asyncio.to_thread来模拟异步调用
            
            # 使用asyncio.to_thread在独立线程中执行可能阻塞的操作
            result = await asyncio.to_thread(self._llm_inference, prompt)
            
            task_end = time.time()
            duration = task_end - task_start
            
            # 记录任务结果
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "llm",
                "prompt": prompt,
                "result": result,
                "start_time": task_start,
                "end_time": task_end,
                "duration": duration,
                "success": True
            })
            
            print(f"任务 {task_id}: LLM文本生成完成，耗时: {duration:.2f}秒")
            
            return result
            
        except Exception as e:
            error_time = time.time()
            duration = error_time - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "llm",
                "prompt": prompt,
                "error": str(e),
                "start_time": task_start,
                "end_time": error_time,
                "duration": duration,
                "success": False
            })
            
            print(f"任务 {task_id}: LLM文本生成失败: {e}")
            return None
        finally:
            self.queue_length -= 1
    
    def _llm_inference(self, prompt: str) -> str:
        """模拟LLM推理（在独立线程中执行）"""
        # 模拟文本生成延迟
        time.sleep(3)
        # 返回模拟结果
        return f"这是对提示 '{prompt}' 的模拟响应。在实际系统中，这里会返回真实的LLM生成结果。"
    
    async def run_image_generation_task(self, task_id: int, prompt: str):
        """运行图像生成任务"""
        self.queue_length += 1
        task_start = time.time()
        
        try:
            print(f"任务 {task_id}: 开始图像生成 - {prompt[:30]}...")
            
            # 实际环境中，这里应该调用真实的FLUX.1-dev或SDXL模型
            # 使用asyncio.to_thread在独立线程中执行
            image_path = await asyncio.to_thread(self._generate_image, prompt, task_id)
            
            task_end = time.time()
            duration = task_end - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "image_generation",
                "prompt": prompt,
                "image_path": image_path,
                "start_time": task_start,
                "end_time": task_end,
                "duration": duration,
                "success": True
            })
            
            print(f"任务 {task_id}: 图像生成完成，耗时: {duration:.2f}秒，保存至: {image_path}")
            
            return image_path
            
        except Exception as e:
            error_time = time.time()
            duration = error_time - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "image_generation",
                "prompt": prompt,
                "error": str(e),
                "start_time": task_start,
                "end_time": error_time,
                "duration": duration,
                "success": False
            })
            
            print(f"任务 {task_id}: 图像生成失败: {e}")
            return None
        finally:
            self.queue_length -= 1
    
    def _generate_image(self, prompt: str, task_id: int) -> str:
        """模拟图像生成（在独立线程中执行）"""
        # 模拟图像生成延迟
        time.sleep(8)
        # 创建模拟图像文件路径
        image_filename = f"generated_image_{task_id}_{int(time.time())}.jpg"
        image_path = os.path.join(PICTURE_DIR, image_filename)
        # 实际系统中，这里会保存真实生成的图像
        # 为演示，创建一个空文件
        open(image_path, 'a').close()
        return image_path
    
    async def run_tts_task(self, task_id: int, text: str):
        """运行TTS语音合成任务"""
        self.queue_length += 1
        task_start = time.time()
        
        try:
            print(f"任务 {task_id}: 开始TTS语音合成 - {text[:30]}...")
            
            # 实际环境中，这里应该调用真实的TTS模型
            # 使用asyncio.to_thread在独立线程中执行
            audio_path = await asyncio.to_thread(self._synthesize_speech, text, task_id)
            
            task_end = time.time()
            duration = task_end - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "tts",
                "text": text,
                "audio_path": audio_path,
                "start_time": task_start,
                "end_time": task_end,
                "duration": duration,
                "success": True
            })
            
            print(f"任务 {task_id}: TTS语音合成完成，耗时: {duration:.2f}秒")
            
            return audio_path
            
        except Exception as e:
            error_time = time.time()
            duration = error_time - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "tts",
                "text": text,
                "error": str(e),
                "start_time": task_start,
                "end_time": error_time,
                "duration": duration,
                "success": False
            })
            
            print(f"任务 {task_id}: TTS语音合成失败: {e}")
            return None
        finally:
            self.queue_length -= 1
    
    def _synthesize_speech(self, text: str, task_id: int) -> str:
        """模拟TTS语音合成（在独立线程中执行）"""
        # 模拟语音合成延迟
        time.sleep(2)
        # 创建模拟音频文件路径
        audio_filename = f"tts_audio_{task_id}_{int(time.time())}.wav"
        audio_path = os.path.join(PICTURE_DIR, audio_filename)
        # 实际系统中，这里会保存真实生成的音频
        # 为演示，创建一个空文件
        open(audio_path, 'a').close()
        return audio_path
    
    async def run_stt_task(self, task_id: int, audio_path: str):
        """运行STT语音识别任务"""
        self.queue_length += 1
        task_start = time.time()
        
        try:
            print(f"任务 {task_id}: 开始STT语音识别 - 音频文件: {audio_path}")
            
            # 实际环境中，这里应该调用真实的Whisper模型
            # 使用asyncio.to_thread在独立线程中执行
            recognized_text = await asyncio.to_thread(self._recognize_speech, audio_path)
            
            task_end = time.time()
            duration = task_end - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "stt",
                "audio_path": audio_path,
                "recognized_text": recognized_text,
                "start_time": task_start,
                "end_time": task_end,
                "duration": duration,
                "success": True
            })
            
            print(f"任务 {task_id}: STT语音识别完成，耗时: {duration:.2f}秒")
            
            return recognized_text
            
        except Exception as e:
            error_time = time.time()
            duration = error_time - task_start
            
            self.results["task_results"].append({
                "task_id": task_id,
                "task_type": "stt",
                "audio_path": audio_path,
                "error": str(e),
                "start_time": task_start,
                "end_time": error_time,
                "duration": duration,
                "success": False
            })
            
            print(f"任务 {task_id}: STT语音识别失败: {e}")
            return None
        finally:
            self.queue_length -= 1
    
    def _recognize_speech(self, audio_path: str) -> str:
        """模拟STT语音识别（在独立线程中执行）"""
        # 模拟语音识别延迟
        time.sleep(4)
        # 返回模拟识别结果
        return "这是模拟的语音识别结果。在实际系统中，这里会返回真实的语音识别文本。"
    
    async def main_thread_ping(self, ping_id: int):
        """主线程ping测试，测量响应延迟"""
        start_time = time.time()
        
        # 简单操作，模拟主线程处理
        await asyncio.sleep(0.01)  # 最小处理时间
        
        end_time = time.time()
        latency = (end_time - start_time) * 1000  # 转换为毫秒
        
        self.results["metrics"]["main_thread_response"].append({
            "ping_id": ping_id,
            "timestamp": start_time,
            "latency": latency
        })
        
        print(f"主线程 Ping {ping_id} 响应延迟: {latency:.2f}ms")
        return latency
    
    async def run_concurrency_test(self, concurrency_level: int, test_duration: int = 30):
        """运行并发测试"""
        print(f"\n=== 运行并发测试: {concurrency_level} 个并发任务 ===")
        
        test_start = time.time()
        tasks = []
        task_types = ["llm", "image_generation", "tts", "stt"]
        
        # 创建并发任务
        for i in range(concurrency_level):
            task_id = f"concurrency_{concurrency_level}_{i}"
            task_type = task_types[i % len(task_types)]
            
            if task_type == "llm":
                task = asyncio.create_task(self.run_llm_task(
                    task_id, 
                    f"请解释并发测试中任务 {i} 的重要性"
                ))
            elif task_type == "image_generation":
                task = asyncio.create_task(self.run_image_generation_task(
                    task_id, 
                    f"未来城市中的智能机器人场景，高并发测试任务 {i}"
                ))
            elif task_type == "tts":
                task = asyncio.create_task(self.run_tts_task(
                    task_id, 
                    f"这是高并发测试中的TTS语音合成任务，任务编号为{i}。"
                ))
            else:  # stt
                # 使用模拟音频文件路径
                audio_path = f"dummy_audio_{i}.wav"
                task = asyncio.create_task(self.run_stt_task(task_id, audio_path))
            
            tasks.append(task)
            # 稍微延迟创建下一个任务
            await asyncio.sleep(0.2)
        
        # 在任务执行期间进行主线程ping测试
        ping_results = []
        for i in range(10):
            latency = await self.main_thread_ping(f"concurrency_{concurrency_level}_{i}")
            ping_results.append(latency)
            await asyncio.sleep(2)  # 每2秒ping一次
        
        # 等待所有任务完成或超时
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=test_duration
            )
        except asyncio.TimeoutError:
            print(f"并发测试 {concurrency_level} 超时")
        
        test_end = time.time()
        test_duration_actual = test_end - test_start
        
        # 计算此并发级别下的统计数据
        completed_tasks = sum(1 for task in self.results["task_results"] 
                             if task.get("task_id", "").startswith(f"concurrency_{concurrency_level}")
                             and task.get("success", False))
        
        concurrency_result = {
            "concurrency_level": concurrency_level,
            "test_duration": test_duration_actual,
            "completed_tasks": completed_tasks,
            "main_thread_avg_latency": sum(ping_results) / len(ping_results) if ping_results else 0,
            "main_thread_max_latency": max(ping_results) if ping_results else 0,
            "timestamp": test_start
        }
        
        self.results["concurrency_test_results"].append(concurrency_result)
        
        print(f"\n并发测试 {concurrency_level} 完成:")
        print(f"  测试持续时间: {test_duration_actual:.2f}秒")
        print(f"  成功完成任务数: {completed_tasks}/{concurrency_level}")
        print(f"  主线程平均响应延迟: {concurrency_result['main_thread_avg_latency']:.2f}ms")
    
    async def run_sequential_test(self):
        """运行顺序测试（基线测试）"""
        print("\n=== 开始顺序测试（基线测试） ===")
        
        # 进行基线ping测试
        baseline_pings = []
        for i in range(5):
            latency = await self.main_thread_ping(f"baseline_{i}")
            baseline_pings.append(latency)
            await asyncio.sleep(0.5)
        
        # 顺序执行各种任务
        await self.run_llm_task("sequential_llm", "这是一个顺序执行的LLM测试任务")
        await self.run_image_generation_task("sequential_image", "一个宁静的自然风景，用于顺序测试")
        await self.run_tts_task("sequential_tts", "这是顺序测试中的TTS语音合成示例文本。")
        await self.run_stt_task("sequential_stt", "dummy_sequential_audio.wav")
        
        # 再次进行ping测试
        after_pings = []
        for i in range(5):
            latency = await self.main_thread_ping(f"after_sequential_{i}")
            after_pings.append(latency)
            await asyncio.sleep(0.5)
        
        print(f"\n顺序测试完成:")
        print(f"  基线平均ping延迟: {sum(baseline_pings)/len(baseline_pings):.2f}ms")
        print(f"  测试后平均ping延迟: {sum(after_pings)/len(after_pings):.2f}ms")
    
    async def run_async_parallel_test(self):
        """运行异步并行测试"""
        print("\n=== 开始异步并行测试 ===")
        
        # 进行基线ping测试
        baseline_pings = []
        for i in range(3):
            latency = await self.main_thread_ping(f"parallel_baseline_{i}")
            baseline_pings.append(latency)
            await asyncio.sleep(0.5)
        
        # 并行启动多个不同类型的任务
        tasks = [
            self.run_llm_task("parallel_llm", "这是一个并行执行的LLM测试任务，测试异步性能"),
            self.run_image_generation_task("parallel_image", "未来科技城市景观，用于异步并行测试"),
            self.run_tts_task("parallel_tts", "这是异步并行测试中的TTS语音合成示例。"),
            self.run_stt_task("parallel_stt", "dummy_parallel_audio.wav")
        ]
        
        # 启动任务
        task_handles = [asyncio.create_task(task) for task in tasks]
        
        # 在任务执行期间持续进行ping测试
        during_pings = []
        for i in range(15):
            latency = await self.main_thread_ping(f"during_parallel_{i}")
            during_pings.append(latency)
            await asyncio.sleep(1)
        
        # 等待所有任务完成
        await asyncio.gather(*task_handles, return_exceptions=True)
        
        # 测试完成后再次进行ping测试
        after_pings = []
        for i in range(3):
            latency = await self.main_thread_ping(f"after_parallel_{i}")
            after_pings.append(latency)
            await asyncio.sleep(0.5)
        
        print(f"\n异步并行测试完成:")
        print(f"  基线平均ping延迟: {sum(baseline_pings)/len(baseline_pings):.2f}ms")
        print(f"  任务执行期间平均ping延迟: {sum(during_pings)/len(during_pings):.2f}ms")
        print(f"  测试后平均ping延迟: {sum(after_pings)/len(after_pings):.2f}ms")
    
    async def run_full_experiment(self):
        """运行完整实验"""
        self.start_time = time.time()
        
        try:
            # 获取系统信息
            self.get_system_info()
            
            # 初始化模型
            await self.initialize_models()
            
            # 启动资源监控
            self.running = True
            monitor_task = asyncio.create_task(self.monitor_resources())
            
            try:
                # 运行顺序测试（基线）
                await self.run_sequential_test()
                
                # 运行异步并行测试
                await self.run_async_parallel_test()
                
                # 运行不同并发级别的测试
                for concurrency in [2, 4, 8]:
                    await self.run_concurrency_test(concurrency)
                
            finally:
                # 停止监控
                self.running = False
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass
            
            # 生成总结报告
            self.generate_summary()
            
        except Exception as e:
            print(f"实验执行出错: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 保存结果
            self.save_results()
    
    def generate_summary(self):
        """生成实验总结"""
        summary = {
            "total_experiment_duration": time.time() - self.start_time if self.start_time else 0,
            "total_tasks_executed": len(self.results["task_results"]),
            "successful_tasks": sum(1 for task in self.results["task_results"] if task.get("success", False)),
            "task_type_breakdown": {},
            "main_thread_performance": {},
            "gpu_performance": {},
            "concurrency_analysis": []
        }
        
        # 任务类型统计
        task_types = {}
        for task in self.results["task_results"]:
            task_type = task.get("task_type", "unknown")
            if task_type not in task_types:
                task_types[task_type] = {"total": 0, "success": 0, "durations": []}
            task_types[task_type]["total"] += 1
            if task.get("success", False):
                task_types[task_type]["success"] += 1
                if "duration" in task:
                    task_types[task_type]["durations"].append(task["duration"])
        
        # 计算每种任务类型的平均执行时间
        for task_type, stats in task_types.items():
            if stats["durations"]:
                avg_duration = sum(stats["durations"]) / len(stats["durations"])
            else:
                avg_duration = 0
            summary["task_type_breakdown"][task_type] = {
                "total": stats["total"],
                "success_rate": (stats["success"] / stats["total"]) * 100 if stats["total"] > 0 else 0,
                "avg_duration": avg_duration
            }
        
        # 主线程性能
        if self.results["metrics"]["main_thread_response"]:
            latencies = [item["latency"] for item in self.results["metrics"]["main_thread_response"]]
            summary["main_thread_performance"] = {
                "avg_latency": sum(latencies) / len(latencies),
                "max_latency": max(latencies),
                "min_latency": min(latencies)
            }
        
        # GPU性能
        if self.results["metrics"]["gpu_memory_usage"]:
            max_memory = max(item["used"] for item in self.results["metrics"]["gpu_memory_usage"])
            avg_memory = sum(item["used"] for item in self.results["metrics"]["gpu_memory_usage"]) / len(self.results["metrics"]["gpu_memory_usage"])
            summary["gpu_performance"] = {
                "peak_memory_usage_mb": max_memory,
                "avg_memory_usage_mb": avg_memory,
                "memory_utilization_percentage": max(item["percentage"] for item in self.results["metrics"]["gpu_memory_usage"])
            }
        
        # 并发分析
        for concurrency_result in self.results["concurrency_test_results"]:
            summary["concurrency_analysis"].append({
                "concurrency_level": concurrency_result["concurrency_level"],
                "throughput": concurrency_result["completed_tasks"] / concurrency_result["test_duration"] if concurrency_result["test_duration"] > 0 else 0,
                "avg_response_latency": concurrency_result["main_thread_avg_latency"]
            })
        
        self.results["summary"] = summary
    
    def save_results(self):
        """保存实验结果"""
        output_file = os.path.join(RESULT_DIR, f"comprehensive_async_gpu_experiment_{int(time.time())}.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n实验完成！结果已保存至: {output_file}")
        
        # 打印实验总结
        if "summary" in self.results:
            summary = self.results["summary"]
            print("\n=== 实验总结 ===")
            print(f"总实验时长: {summary['total_experiment_duration']:.2f}秒")
            print(f"总执行任务数: {summary['total_tasks_executed']}")
            print(f"成功完成任务数: {summary['successful_tasks']}")
            print(f"\n任务类型统计:")
            for task_type, stats in summary['task_type_breakdown'].items():
                print(f"  {task_type}: 成功率 {stats['success_rate']:.1f}%, 平均耗时 {stats['avg_duration']:.2f}秒")
            print(f"\n主线程性能:")
            if summary['main_thread_performance']:
                print(f"  平均响应延迟: {summary['main_thread_performance']['avg_latency']:.2f}ms")
                print(f"  最大响应延迟: {summary['main_thread_performance']['max_latency']:.2f}ms")
            print(f"\nGPU性能:")
            if summary['gpu_performance']:
                print(f"  峰值显存使用: {summary['gpu_performance']['peak_memory_usage_mb']:.2f} MB")
                print(f"  平均显存使用: {summary['gpu_performance']['avg_memory_usage_mb']:.2f} MB")

def main():
    print("=== CPU异步调度GPU多模型运行实验开始 ===")
    
    experiment = ComprehensiveAsyncGPUExperiment()
    
    try:
        asyncio.run(experiment.run_full_experiment())
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验运行出错: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== 实验结束 ===")

if __name__ == "__main__":
    main()