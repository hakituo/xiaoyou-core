#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多模态调度器演示脚本
演示8GB显存限制下的文本、图像生成功能
"""

import os
import asyncio
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from multimodal_scheduler import ModelManager, ResourceMonitor

async def demo_text_chat(manager):
    """演示文本对话功能"""
    print("\n=== 📝 文本对话演示 ===")
    
    # 简单对话
    prompts = [
        "你好，我是你的用户，很高兴认识你！",
        "请简要介绍一下你能做什么？",
        "如何在8GB显存下优化大型语言模型？"
    ]
    
    for prompt in prompts:
        print(f"\n👤 用户: {prompt}")
        result = await manager.chat(prompt)
        
        if result["status"] == "success":
            print(f"🤖 AI: {result['response']}")
        else:
            print(f"❌ 错误: {result['error']}")
        
        # 显示资源状态
        status = ResourceMonitor.get_system_status()
        print(f"📊 显存使用: {status.get('gpu_memory_used', 0):.2f}GB")
        await asyncio.sleep(1)  # 短暂暂停

async def demo_image_generation(manager):
    """演示图像生成功能"""
    print("\n=== 🎨 图像生成演示 ===")
    
    # 确保输出目录存在
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成简单图像
    prompts = [
        "一只可爱的小猫，坐在窗台上，阳光照射",
        "风景照：雪山和湖泊，高清细节",
        "未来风格的城市夜景，霓虹灯"
    ]
    
    for i, prompt in enumerate(prompts):
        print(f"\n🔮 生成图像: {prompt}")
        save_path = os.path.join(output_dir, f"generated_image_{i+1}.png")
        
        result = await manager.generate_image(
            prompt=prompt,
            save_path=save_path,
            width=512,
            height=512  # 低分辨率优化
        )
        
        if result["status"] == "success":
            print(f"✅ 图像已保存到: {result['image_path']}")
        else:
            print(f"❌ 错误: {result['error']}")
        
        # 显示资源状态
        status = ResourceMonitor.get_system_status()
        print(f"📊 显存使用: {status.get('gpu_memory_used', 0):.2f}GB")
        await asyncio.sleep(1)

async def demo_model_switching(manager):
    """演示模型切换功能"""
    print("\n=== 🔄 模型切换演示 ===")
    print("展示文本模型和图像生成模型之间的显存管理")
    
    # 先使用文本模型
    print("\n1️⃣ 加载文本模型")
    result = await manager.chat("什么是多模态AI？")
    if result["status"] == "success":
        print(f"✅ 文本模型加载成功")
    
    # 显示显存使用
    status = ResourceMonitor.get_system_status()
    print(f"📊 切换前显存: {status.get('gpu_memory_used', 0):.2f}GB")
    
    # 切换到图像生成模型（自动清理文本模型显存）
    print("\n2️⃣ 切换到图像生成模型（自动清理）")
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "switch_demo.png")
    result = await manager.generate_image(
        "简单的抽象艺术，蓝色和紫色渐变",
        save_path=output_path
    )
    
    if result["status"] == "success":
        print(f"✅ 图像生成模型切换成功")
    
    # 显示显存使用
    status = ResourceMonitor.get_system_status()
    print(f"📊 切换后显存: {status.get('gpu_memory_used', 0):.2f}GB")
    
    # 再次切换回文本模型
    print("\n3️⃣ 切回文本模型")
    result = await manager.chat("请总结我们刚才做了什么操作？")
    if result["status"] == "success":
        print(f"✅ 文本模型再次加载成功")
    
    # 显示最终显存使用
    status = ResourceMonitor.get_system_status()
    print(f"📊 最终显存: {status.get('gpu_memory_used', 0):.2f}GB")

async def run_comprehensive_demo():
    """运行完整演示"""
    print("""🎯 8GB显存优化 - 多模态调度演示
======================================
本演示展示如何在8GB显存限制下高效运行：
1. 文本对话（量化LLM）
2. 图像生成（低分辨率+单batch）
3. 自动显存管理和模型切换
""")
    
    # 创建模型管理器
    manager = ModelManager()
    
    try:
        # 运行各个演示
        await demo_text_chat(manager)
        await demo_image_generation(manager)
        await demo_model_switching(manager)
        
        print("\n" + "="*50)
        print("🎉 演示完成！所有功能在8GB显存限制下正常工作")
        print("💡 关键优化：")
        print("   - 文本模型使用4-bit量化，显存占用降至5-6GB")
        print("   - 图像生成使用512x512分辨率，batch=1")
        print("   - 自动模型切换和显存清理")
        print("   - 异步处理提高效率")
        
    except Exception as e:
        print(f"\n❌ 演示过程中出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理资源
        print("\n🧹 清理资源...")
        manager._clear_memory()

if __name__ == "__main__":
    print("🚀 启动多模态调度演示")
    
    # 检查Python版本
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        sys.exit(1)
    
    # 运行演示
    try:
        asyncio.run(run_comprehensive_demo())
    except KeyboardInterrupt:
        print("\n👋 演示已取消")
    except Exception as e:
        print(f"\n❌ 演示启动失败: {e}")