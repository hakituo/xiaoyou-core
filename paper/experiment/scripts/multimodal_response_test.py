#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多模态综合实验（核心实验4）
目的：验证异步架构在同时执行「图像生成 + 语音识别 + 文本应答」时的表现
模拟未来手机AI助手架构
"""

import os
import time
import json
import asyncio
import random
import wave
import numpy as np
import psutil
from datetime import datetime
from typing import List, Dict, Any, Tuple

# 确保实验结果目录存在
RESULT_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\data"
PICTURE_DIR = "d:\\AI\\xiaoyou-core\\paper\\experiment\\experiment_results\\picture"
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(PICTURE_DIR, exist_ok=True)

class MultimodalResponseTest:
    def __init__(self):
        self.results = {
            "experiment_name": "多模态综合实验",
            "timestamp": datetime.now().isoformat(),
            "system_info": {},
            "test_config": {},
            "experiment_results": [],
            "summary_metrics": {}
        }
        self.total_runs = 0
        self.successful_runs = 0
        self.running_tasks = set()
    
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
    
    def generate_test_audio(self, duration: float = 3.0, sample_rate: int = 16000) -> str:
        """生成测试音频文件（用于模拟手机语音输入）"""
        # 创建一个简单的音频文件
        filename = os.path.join(RESULT_DIR, f"test_audio_{int(time.time())}.wav")
        
        try:
            # 生成正弦波数据
            t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
            # 生成一些随机噪声来模拟语音
            audio_data = np.random.normal(0, 0.1, t.shape)
            audio_data = (audio_data * 32767).astype(np.int16)
            
            # 写入WAV文件
            with wave.open(filename, 'w') as wf:
                wf.setnchannels(1)  # 单声道
                wf.setsampwidth(2)  # 16位
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())
            
            return filename
        except Exception as e:
            print(f"生成测试音频时出错: {e}")
            return None
    
    async def speech_recognition_task(self, audio_file: str) -> Dict[str, Any]:
        """模拟语音识别任务"""
        start_time = time.time()
        
        try:
            # 模拟Whisper语音识别过程
            print(f"开始语音识别: {audio_file}")
            
            # 实际使用时应替换为真实的Whisper调用
            # 这里模拟不同长度的识别时间（基于音频长度）
            audio_duration = 3.0  # 假设音频长度为3秒
            recognition_time = audio_duration * 0.8  # 模拟识别时间为音频长度的80%
            await asyncio.sleep(recognition_time)
            
            # 生成模拟的识别结果
            sample_texts = [
                "请帮我生成一张美丽的风景图片",
                "描述一下今天的天气怎么样",
                "请给我讲一个简短的故事",
                "画一只可爱的小猫在草地上玩耍",
                "生成一张未来城市的科幻场景"
            ]
            recognized_text = random.choice(sample_texts)
            
            end_time = time.time()
            
            return {
                "task_type": "speech_recognition",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "recognized_text": recognized_text,
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            return {
                "task_type": "speech_recognition",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "error": str(e),
                "success": False
            }
    
    async def llm_inference_task(self, text_input: str) -> Dict[str, Any]:
        """模拟LLM推理任务"""
        start_time = time.time()
        
        try:
            print(f"开始LLM推理: {text_input[:50]}...")
            
            # 实际使用时应替换为真实的LLM调用（如Qwen模型）
            # 根据输入文本长度模拟不同的推理时间
            inference_time = max(1.0, len(text_input) * 0.02)
            await asyncio.sleep(inference_time)
            
            # 生成模拟的LLM响应
            if "生成" in text_input or "画" in text_input:
                # 图像生成相关请求
                llm_response = {
                    "text": f"我将为您生成关于'{text_input}'的图像",
                    "should_generate_image": True,
                    "image_prompt": text_input
                }
            else:
                # 普通文本响应
                llm_response = {
                    "text": "这是LLM对您问题的详细回答，包含了您所需的信息。",
                    "should_generate_image": False
                }
            
            end_time = time.time()
            
            return {
                "task_type": "llm_inference",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "response": llm_response,
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            return {
                "task_type": "llm_inference",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "error": str(e),
                "success": False
            }
    
    async def image_generation_task(self, prompt: str) -> Dict[str, Any]:
        """模拟图像生成任务"""
        start_time = time.time()
        
        try:
            print(f"开始图像生成: {prompt[:50]}...")
            
            # 实际使用时应替换为真实的SDXL调用
            # 模拟图像生成时间
            await asyncio.sleep(random.uniform(6.0, 12.0))
            
            # 模拟生成的图像路径
            image_path = os.path.join(PICTURE_DIR, f"generated_image_{int(time.time())}.png")
            
            # 在实际场景中，这里会有真实的图像生成代码
            # 现在我们只是创建一个空文件作为占位符
            with open(image_path, 'w') as f:
                f.write("This is a placeholder for a generated image")
            
            end_time = time.time()
            
            return {
                "task_type": "image_generation",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "image_path": image_path,
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            return {
                "task_type": "image_generation",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "error": str(e),
                "success": False
            }
    
    async def text_to_speech_task(self, text: str) -> Dict[str, Any]:
        """模拟文本转语音任务"""
        start_time = time.time()
        
        try:
            print(f"开始语音合成: {text[:50]}...")
            
            # 实际使用时应替换为真实的TTS调用
            # 根据文本长度模拟不同的合成时间
            synthesis_time = max(0.5, len(text) * 0.01)
            await asyncio.sleep(synthesis_time)
            
            # 模拟生成的音频路径
            audio_path = os.path.join(RESULT_DIR, f"tts_output_{int(time.time())}.wav")
            
            # 创建一个空文件作为占位符
            with open(audio_path, 'w') as f:
                f.write("This is a placeholder for TTS audio")
            
            end_time = time.time()
            
            return {
                "task_type": "text_to_speech",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "audio_path": audio_path,
                "success": True
            }
            
        except Exception as e:
            end_time = time.time()
            return {
                "task_type": "text_to_speech",
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "error": str(e),
                "success": False
            }
    
    async def run_full_pipeline(self, run_id: int) -> Dict[str, Any]:
        """运行完整的多模态处理 pipeline"""
        pipeline_start_time = time.time()
        pipeline_results = {
            "run_id": run_id,
            "start_time": pipeline_start_time,
            "tasks": [],
            "success": True
        }
        
        try:
            # 1. 生成测试音频
            audio_file = self.generate_test_audio()
            if not audio_file:
                raise Exception("无法生成测试音频")
            
            # 2. 语音识别
            speech_result = await self.speech_recognition_task(audio_file)
            pipeline_results["tasks"].append(speech_result)
            
            if not speech_result["success"]:
                raise Exception(f"语音识别失败: {speech_result.get('error')}")
            
            # 3. LLM推理
            llm_result = await self.llm_inference_task(speech_result["recognized_text"])
            pipeline_results["tasks"].append(llm_result)
            
            if not llm_result["success"]:
                raise Exception(f"LLM推理失败: {llm_result.get('error')}")
            
            # 4. 条件性图像生成
            image_result = None
            if llm_result["response"].get("should_generate_image", False):
                image_result = await self.image_generation_task(
                    llm_result["response"]["image_prompt"]
                )
                pipeline_results["tasks"].append(image_result)
                
                if not image_result["success"]:
                    raise Exception(f"图像生成失败: {image_result.get('error')}")
            
            # 5. 文本转语音
            tts_result = await self.text_to_speech_task(llm_result["response"]["text"])
            pipeline_results["tasks"].append(tts_result)
            
            if not tts_result["success"]:
                raise Exception(f"语音合成失败: {tts_result.get('error')}")
            
            # 计算总耗时
            pipeline_end_time = time.time()
            pipeline_results["end_time"] = pipeline_end_time
            pipeline_results["total_duration"] = pipeline_end_time - pipeline_start_time
            
            # 计算各阶段耗时
            pipeline_results["stage_durations"] = {
                "total": pipeline_results["total_duration"]
            }
            
            for task in pipeline_results["tasks"]:
                pipeline_results["stage_durations"][task["task_type"]] = task["duration"]
            
            print(f"Pipeline {run_id} 完成！总耗时: {pipeline_results['total_duration']:.2f}秒")
            
        except Exception as e:
            pipeline_results["end_time"] = time.time()
            pipeline_results["total_duration"] = pipeline_results["end_time"] - pipeline_start_time
            pipeline_results["error"] = str(e)
            pipeline_results["success"] = False
            print(f"Pipeline {run_id} 失败: {e}")
        finally:
            # 清理临时文件
            if 'audio_file' in locals() and audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass
        
        return pipeline_results
    
    async def run_async_pipelines(self, num_runs: int, concurrency: int = 1):
        """异步运行多个pipeline"""
        print(f"\n=== 开始运行 {num_runs} 个多模态pipeline（并发数: {concurrency}）===")
        
        # 创建任务队列
        tasks = []
        running_tasks = set()
        
        for run_id in range(num_runs):
            # 控制并发数
            while len(running_tasks) >= concurrency:
                # 检查是否有任务完成
                done, pending = await asyncio.wait(running_tasks, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
                running_tasks -= done
            
            # 创建新任务
            task = asyncio.create_task(self.run_full_pipeline(run_id))
            tasks.append(task)
            running_tasks.add(task)
            
            # 添加小延迟避免瞬间创建过多任务
            if run_id % 2 == 0 and run_id > 0:
                await asyncio.sleep(0.5)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        # 统计结果
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        print(f"\n=== Pipeline运行完成 ===")
        print(f"成功: {len(successful)}/{num_runs}")
        print(f"失败: {len(failed)}/{num_runs}")
        
        return results
    
    def calculate_summary_metrics(self, all_results: List[Dict[str, Any]]):
        """计算汇总指标"""
        successful_results = [r for r in all_results if r["success"]]
        
        if not successful_results:
            self.results["summary_metrics"] = {"error": "没有成功的实验结果"}
            return
        
        # 计算总体延迟
        total_durations = [r["total_duration"] for r in successful_results]
        avg_total_duration = sum(total_durations) / len(total_durations)
        
        # 计算各阶段平均延迟
        stage_durations = {
            "speech_recognition": [],
            "llm_inference": [],
            "image_generation": [],
            "text_to_speech": []
        }
        
        for result in successful_results:
            for stage, duration in result.get("stage_durations", {}).items():
                if stage in stage_durations:
                    stage_durations[stage].append(duration)
        
        # 计算每个阶段的平均值
        avg_stage_durations = {}
        for stage, durations in stage_durations.items():
            if durations:
                avg_stage_durations[stage] = sum(durations) / len(durations)
        
        # 计算总体吞吐量（pipeline/秒）
        if total_durations:
            total_time_span = max(r["end_time"] for r in successful_results) - min(r["start_time"] for r in successful_results)
            throughput = len(successful_results) / total_time_span if total_time_span > 0 else 0
        else:
            throughput = 0
        
        # 计算成功率
        success_rate = len(successful_results) / len(all_results) * 100 if all_results else 0
        
        self.results["summary_metrics"] = {
            "total_runs": len(all_results),
            "successful_runs": len(successful_results),
            "success_rate": success_rate,
            "average_total_duration": avg_total_duration,
            "average_stage_durations": avg_stage_durations,
            "throughput": throughput,
            "min_total_duration": min(total_durations) if total_durations else 0,
            "max_total_duration": max(total_durations) if total_durations else 0
        }
    
    async def run_test(self, num_runs: int = 10, concurrency_levels: List[int] = None):
        """运行完整的多模态测试"""
        # 获取系统信息
        self.get_system_info()
        
        # 默认并发级别
        if concurrency_levels is None:
            concurrency_levels = [1]  # 默认只测试单并发
        
        # 保存测试配置
        self.results["test_config"] = {
            "num_runs": num_runs,
            "concurrency_levels": concurrency_levels
        }
        
        # 运行不同并发级别的测试
        for concurrency in concurrency_levels:
            print(f"\n=== 测试并发级别: {concurrency} ===")
            
            # 计算此并发级别下的运行次数（可以根据需要调整）
            runs_for_concurrency = min(num_runs, concurrency * 5)
            
            # 运行测试
            results = await self.run_async_pipelines(runs_for_concurrency, concurrency)
            
            # 保存结果
            self.results["experiment_results"].append({
                "concurrency": concurrency,
                "num_runs": runs_for_concurrency,
                "results": results
            })
            
            # 短暂休息，让系统恢复
            await asyncio.sleep(3)
        
        # 收集所有结果用于计算汇总指标
        all_results = []
        for exp in self.results["experiment_results"]:
            all_results.extend(exp["results"])
        
        # 计算汇总指标
        self.calculate_summary_metrics(all_results)
        
        # 保存结果
        self.save_results()
    
    def save_results(self):
        """保存实验结果"""
        output_file = os.path.join(RESULT_DIR, "multimodal.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n实验完成！结果已保存至: {output_file}")

def main():
    print("=== 多模态综合实验开始 ===")
    test = MultimodalResponseTest()
    
    # 可以根据需要调整测试参数
    num_runs = 5  # 每个并发级别运行的次数
    concurrency_levels = [1, 2, 3]  # 测试的并发级别
    
    try:
        asyncio.run(test.run_test(num_runs, concurrency_levels))
        
        # 打印汇总信息
        if "summary_metrics" in test.results:
            metrics = test.results["summary_metrics"]
            print("\n=== 实验汇总 ===")
            print(f"总运行次数: {metrics['total_runs']}")
            print(f"成功次数: {metrics['successful_runs']}")
            print(f"成功率: {metrics['success_rate']:.2f}%")
            print(f"平均总耗时: {metrics['average_total_duration']:.2f}秒")
            print(f"系统吞吐量: {metrics['throughput']:.2f} pipelines/秒")
            print("\n各阶段平均耗时:")
            for stage, duration in metrics.get('average_stage_durations', {}).items():
                print(f"  {stage}: {duration:.2f}秒")
                
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验运行出错: {e}")
    
    print("=== 多模态综合实验结束 ===")

if __name__ == "__main__":
    main()