#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GPU可用性测试脚本
用于验证各虚拟环境中的PyTorch是否正确配置了GPU支持
"""

import torch
import os

print("=== GPU可用性测试 ===")
print(f"Python环境路径: {os.sys.executable}")
print(f"PyTorch版本: {torch.__version__}")

# 检查CUDA是否可用
cuda_available = torch.cuda.is_available()
print(f"CUDA可用: {cuda_available}")

# 如果CUDA可用，显示更多信息
if cuda_available:
    print(f"CUDA版本: {torch.version.cuda}")
    print(f"GPU设备数量: {torch.cuda.device_count()}")
    print(f"当前GPU设备: {torch.cuda.current_device()}")
    print(f"GPU名称: {torch.cuda.get_device_name(0)}")
    
    # 进行简单的GPU计算测试
    try:
        # 创建一个随机张量并移动到GPU
        x = torch.randn(1000, 1000).cuda()
        y = torch.randn(1000, 1000).cuda()
        
        # 执行计算
        start_time = torch.cuda.Event(enable_timing=True)
        end_time = torch.cuda.Event(enable_timing=True)
        
        start_time.record()
        z = torch.matmul(x, y)
        end_time.record()
        
        # 等待计算完成
        torch.cuda.synchronize()
        
        # 计算时间
        elapsed_time = start_time.elapsed_time(end_time)
        print(f"GPU计算测试成功!")
        print(f"矩阵乘法耗时: {elapsed_time:.4f} ms")
        print(f"结果校验: {z.mean().item():.4f}")
    except Exception as e:
        print(f"GPU计算测试失败: {e}")
else:
    print("警告: 未检测到可用的GPU。实验将在CPU模式下运行。")

print("\n=== 测试完成 ===")