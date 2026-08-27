#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试体质数据记录工具"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import asyncio
from core.tools.physiology_tool import RecordBodyMetricsTool


async def test_record_body_metrics():
    """测试体质数据记录"""
    tool = RecordBodyMetricsTool()
    
    # 测试 1: 只记录体重
    print("=== 测试 1: 只记录体重 ===")
    result = await tool._run(weight_kg=48.2)
    print(f"结果: {result}")
    
    # 验证数据是否写入
    from core.services.workspace.status_manager import get_user_status_manager
    status_mgr = get_user_status_manager()
    body_metrics = status_mgr.get_body_metrics()
    print(f"user_status.json 中的数据: {body_metrics}")
    
    # 测试 2: 记录多个指标
    print("\n=== 测试 2: 记录多个指标 ===")
    result = await tool._run(
        weight_kg=48.5,
        body_fat_percent=11.3,
        muscle_mass_kg=38.2,
        bmi=17.8,
        note="最近有运动"
    )
    print(f"结果: {result}")
    
    # 验证数据是否写入
    body_metrics = status_mgr.get_body_metrics()
    print(f"user_status.json 中的数据: {body_metrics}")
    
    # 测试 3: 验证 user_physiology 服务
    print("\n=== 测试 3: 验证 user_physiology 服务 ===")
    from core.services.user_physiology.service import get_user_physiology_service
    physiology = get_user_physiology_service()
    latest = physiology.get_latest("default_user")
    print(f"user_physiology.json 中的数据: {latest}")
    
    print("\n=== 所有测试完成 ===")


if __name__ == "__main__":
    asyncio.run(test_record_body_metrics())
