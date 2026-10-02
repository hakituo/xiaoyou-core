#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试提醒功能"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.tools.reminder_tool import ReminderTool


async def test_reminder():
    """测试提醒功能"""
    tool = ReminderTool()
    
    # 测试: 设置 1 分钟后的提醒
    print("=== 测试: 设置 1 分钟后的提醒 ===")
    result = await tool._run(minutes=1, message="测试提醒：该喝水了")
    print(f"结果: {result}")
    
    # 验证提醒是否写入
    from core.services.workspace.service import get_workspace_service
    ws = get_workspace_service()
    reminders = await ws.get_reminders()
    print(f"reminders.json 中的数据: {reminders}")
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    asyncio.run(test_reminder())
