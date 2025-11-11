#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
演示如何使用新配置的Qwen2.5B-instruct语言模型和Qwen2-VL-7B图像模型
"""

import os
import asyncio
from models.qwen2_5b_instruct.model_adapter import generate_response
from models.qwen2_vl_7b.model_adapter import process_image_query, is_image_supported
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def demo_llm_response():
    """演示语言模型响应"""
    print("="*60)
    print("🎯 Qwen2.5B-instruct 语言模型演示")
    print("="*60)
    
    try:
        # 简单的文本查询
        prompt = "请简要介绍一下你自己"
        print(f"\n用户提问: {prompt}")
        response = generate_response(prompt, max_tokens=500, temperature=0.7)
        print(f"\n模型响应:\n{response}")
        print("\n" + "-"*60)
        
        # 更复杂的问题
        prompt = "解释量子计算的基本原理，并说明它与传统计算机的主要区别"
        print(f"\n用户提问: {prompt}")
        response = generate_response(prompt, max_tokens=800, temperature=0.5)
        print(f"\n模型响应:\n{response}")
        
    except Exception as e:
        print(f"语言模型调用失败: {str(e)}")
        print("请确保已下载完整的模型文件到 ./models/qwen2_5b_instruct 目录")

async def demo_image_processing():
    """演示图像理解功能"""
    print("\n" + "="*60)
    print("🖼️  Qwen2-VL-7B 图像理解模型演示")
    print("="*60)
    
    # 测试图像路径 - 请替换为实际存在的图像文件
    test_image = "test_image.jpg"
    
    if not os.path.exists(test_image):
        print(f"\n⚠️  测试图像 '{test_image}' 不存在")
        print("请将测试图像放在当前目录，或修改代码中的test_image变量")
        return
    
    if not is_image_supported(test_image):
        print(f"\n❌ 图像格式不支持，请使用 jpg, jpeg, png, bmp 或 gif 格式")
        return
    
    try:
        # 基本图像描述
        prompt = "详细描述这张图片中包含的内容"
        print(f"\n图像路径: {test_image}")
        print(f"查询提示: {prompt}")
        print("\n正在处理图像，这可能需要一些时间...")
        
        # 注意：实际运行此部分需要完整的Qwen2-VL-7B模型文件
        # 以下代码被注释，避免在没有模型的情况下运行出错
        # response = process_image_query(prompt, test_image)
        # print(f"\n图像理解结果:\n{response}")
        
        print("\n📝 提示：图像理解功能需要完整的Qwen2-VL-7B模型文件")
        print("请从Hugging Face下载模型文件并放置于 ./models/qwen2_vl_7b 目录")
        
    except Exception as e:
        print(f"图像理解调用失败: {str(e)}")

async def main():
    """主演示函数"""
    print("🚀 XiaoYou Core 模型演示程序启动")
    print(f"\n当前配置:")
    print(f"🔤 语言模型: {os.getenv('MODEL_NAME', 'Qwen2.5B-instruct')}")
    print(f"   模型路径: {os.getenv('MODEL_PATH', './models/qwen2_5b_instruct')}")
    print(f"🖼️  图像模型: {os.getenv('VL_MODEL_NAME', 'Qwen2-VL-7B')}")
    print(f"   模型路径: {os.getenv('VL_MODEL_PATH', './models/qwen2_vl_7b')}")
    print(f"💻 设备: {os.getenv('DEVICE', 'cuda')}")
    
    # 运行语言模型演示
    await demo_llm_response()
    
    # 运行图像理解演示
    await demo_image_processing()
    
    print("\n" + "="*60)
    print("✅ 演示完成")
    print("📌 注意事项:")
    print("  1. 模型文件占位符已创建，请下载完整模型文件以获得实际功能")
    print("  2. 大模型首次加载需要较长时间和较多显存")
    print("  3. 请确保CUDA环境正确配置（如果使用GPU）")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())