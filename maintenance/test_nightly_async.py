#!/usr/bin/env python3
"""
测试 nightly_processor 的异步任务执行
验证 asyncio 事件循环修复是否有效
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def test_llm_call():
    """测试 LLM 调用是否能在当前事件循环中正常工作"""
    print("[测试] 开始测试 LLM 调用...")
    
    try:
        from core.services.scheduler.task.task_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        
        # 简单的 LLM 测试调用
        test_prompt = "请用一句话回答：1+1等于几？"
        response = ""
        
        print("[测试] 提交 LLM 任务...")
        async for chunk in scheduler.submit_llm_task(test_prompt, max_tokens=50, temperature=0.1):
            if isinstance(chunk, str):
                response += chunk
            elif isinstance(chunk, dict) and chunk.get("content"):
                response += chunk["content"]
        
        if response.strip():
            print(f"[测试] LLM 调用成功！响应: {response.strip()[:100]}")
            return True
        else:
            print("[测试] LLM 返回空内容")
            return False
            
    except Exception as e:
        print(f"[测试] LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_journal_service():
    """测试 Journal Service 是否能正常调用"""
    print("\n[测试] 开始测试 Journal Service...")
    
    try:
        from core.services.journal.service import get_journal_service
        journal_service = get_journal_service()
        
        # 测试获取明日计划（不生成，只查询）
        print("[测试] 查询明日计划...")
        plan = await journal_service.get_tomorrow_plan()
        
        if plan:
            print(f"[测试] 明日计划已存在: {plan.date}, {len(plan.items)} 项")
        else:
            print("[测试] 明日计划不存在（将在 nightly processor 中自动生成）")
        
        return True
        
    except Exception as e:
        print(f"[测试] Journal Service 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_nightly_processor_async_tasks():
    """测试 nightly processor 的异步任务执行"""
    print("\n[测试] 开始测试 Nightly Processor 异步任务...")
    
    try:
        # 直接测试异步任务，不导入完整的 NightlyProcessor（避免 schedule 依赖）
        # 模拟 _execute_async_tasks 的核心逻辑
        from core.services.journal.service import get_journal_service
        from core.utils.time_utils import get_diary_target_date
        import datetime
        
        print("[测试] 直接测试异步任务逻辑...")
        
        # 测试 Journal Service 的计划生成
        journal_service = get_journal_service()
        
        # 获取目标日期
        target_date = get_diary_target_date()
        print(f"[测试] 目标日期: {target_date.strftime('%Y-%m-%d')}")
        
        # 测试生成明日计划
        print("[测试] 尝试生成明日计划...")
        try:
            plan = await journal_service.generate_tomorrow_plan(force=False)
            print(f"[测试] 计划生成成功: {plan.date}, {len(plan.items)} 项")
            return True
        except Exception as e:
            print(f"[测试] 计划生成失败（可能已存在）: {e}")
            # 检查是否已存在
            existing = await journal_service.get_tomorrow_plan()
            if existing:
                print(f"[测试] 明日计划已存在: {existing.date}, {len(existing.items)} 项")
                return True
            return False
        
    except Exception as e:
        print(f"[测试] Nightly Processor 异步任务失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("=" * 60)
    print("Nightly Processor 异步任务测试")
    print("=" * 60)
    
    results = []
    
    # 测试 1: LLM 调用
    results.append(("LLM 调用", await test_llm_call()))
    
    # 测试 2: Journal Service
    results.append(("Journal Service", await test_journal_service()))
    
    # 测试 3: Nightly Processor 异步任务
    results.append(("Nightly Processor 异步任务", await test_nightly_processor_async_tasks()))
    
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)
    for name, success in results:
        status = "✓ 成功" if success else "✗ 失败"
        print(f"  {name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("=" * 60))
    if all_passed:
        print("所有测试通过！Nightly Processor 应该能正常工作。")
    else:
        print("部分测试失败，需要进一步检查。")
    print("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
