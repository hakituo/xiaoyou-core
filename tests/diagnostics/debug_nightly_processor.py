#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NightlyProcessor 诊断脚本

诊断日记生成返回 non-JSON 和记忆蒸馏失败的原因。
需要在主程序运行时执行（依赖 scheduler 和 LLM 服务）。

用法:
    python tests/debug_nightly_processor.py                # 测试全部
    python tests/debug_nightly_processor.py --diary        # 只测日记
    python tests/debug_nightly_processor.py --distill      # 只测蒸馏
    python tests/debug_nightly_processor.py --llm-only     # 只测 LLM 调用
"""

import os
import sys
import time
import asyncio
import argparse
import logging
import traceback

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 强制 DEBUG 级别输出到控制台
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console = logging.getLogger("debug_nightly")
console.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────
# 1. 直接测试 scheduler.submit_llm_task
# ─────────────────────────────────────────────────────────
async def test_llm_call_direct():
    """直接调用 scheduler.submit_llm_task，看 LLM 是否正常返回"""
    print("\n" + "=" * 70)
    print("[TEST 1] 直接测试 scheduler.submit_llm_task")
    print("=" * 70)

    from core.services.scheduler.task.task_scheduler import get_global_scheduler
    scheduler = get_global_scheduler()
    console.info(f"Scheduler 类型: {type(scheduler).__name__}")

    prompt = "请用JSON格式回答：{\"answer\": \"hello\"}"
    llm_kwargs = {"max_tokens": 100, "temperature": 0.3}

    console.info(f"发送 prompt: {prompt}")
    console.info(f"llm_kwargs: {llm_kwargs}")

    full_response = ""
    chunk_count = 0
    try:
        # 加超时保护
        async def _collect():
            nonlocal full_response, chunk_count
            async for chunk in scheduler.submit_llm_task(prompt, **llm_kwargs):
                chunk_count += 1
                if isinstance(chunk, str):
                    full_response += chunk
                    console.debug(f"  chunk#{chunk_count} (str): {repr(chunk[:80])}")
                elif isinstance(chunk, dict):
                    content = chunk.get("content", "")
                    full_response += content
                    console.debug(f"  chunk#{chunk_count} (dict): keys={list(chunk.keys())}, content={repr(content[:80])}")
                    if chunk.get("error"):
                        console.error(f"  chunk#{chunk_count} ERROR: {chunk['error']}")
                    if chunk.get("status"):
                        console.info(f"  chunk#{chunk_count} status: {chunk['status']}")
                else:
                    console.debug(f"  chunk#{chunk_count} (type={type(chunk).__name__}): {repr(chunk)[:80]}")
                if chunk_count > 50:
                    console.warning("chunk 数量超过 50，截断")
                    break

        try:
            await asyncio.wait_for(_collect(), timeout=30.0)
        except asyncio.TimeoutError:
            console.error("submit_llm_task 超时 (30秒)")

    except Exception as e:
        console.error(f"submit_llm_task 异常: {type(e).__name__}: {e}")
        traceback.print_exc()

    print(f"\n--- 结果 ---")
    print(f"  chunk 总数: {chunk_count}")
    print(f"  response 长度: {len(full_response)}")
    print(f"  response 内容: {repr(full_response[:300])}")
    return full_response


# ─────────────────────────────────────────────────────────
# 2. 测试日记生成
# ─────────────────────────────────────────────────────────
async def test_diary_generation():
    """测试日记生成，看 non-JSON 的原始 LLM 输出"""
    print("\n" + "=" * 70)
    print("[TEST 2] 测试日记生成 (JournalSummaryService)")
    print("=" * 70)

    from core.services.journal.service import get_journal_service
    from core.utils.time_utils import get_diary_target_date

    journal_service = get_journal_service()
    target_date = get_diary_target_date()
    date_str = target_date.strftime("%Y-%m-%d")
    console.info(f"目标日期: {date_str}")

    # 用 force=True 强制重新生成
    for persona in ["aveline", "ling"]:
        print(f"\n--- 生成 {persona} 日记 ---")
        try:
            summary = await journal_service.generate_daily_summary(
                date_str, persona=persona, force=True
            )
            if summary:
                console.info(f"  summary.summary 长度: {len(summary.summary or '')}")
                console.info(f"  summary.stats: {summary.stats}")
                if summary.stats.get("parse_error"):
                    console.error(f"  parse_error: {summary.stats['parse_error']}")
                    console.error(f"  raw_output_len: {summary.stats.get('raw_output_len')}")
                print(f"  结果: {summary.summary[:200]}")
            else:
                console.error(f"  返回 None")
        except Exception as e:
            console.error(f"  异常: {e}")
            traceback.print_exc()


# ─────────────────────────────────────────────────────────
# 3. 测试记忆蒸馏
# ─────────────────────────────────────────────────────────
async def test_distillation():
    """测试记忆蒸馏，看 LLM 调用是否正常"""
    print("\n" + "=" * 70)
    print("[TEST 3] 测试记忆蒸馏 (NightlyProcessor._distill_memories_async)")
    print("=" * 70)

    from memory.weighted_memory_manager import get_weighted_memory_manager
    from memory.nightly_processor import NightlyProcessor, DEFAULT_NIGHTLY_CONFIG

    # 获取所有用户的记忆管理器
    from memory.weighted_memory_manager import _instances, _instances_lock
    with _instances_lock:
        memory_managers = dict(_instances)

    console.info(f"已注册的记忆管理器: {list(memory_managers.keys())}")

    if not memory_managers:
        console.warning("没有已注册的记忆管理器，尝试手动创建...")
        # 手动获取
        for uid in ["private_10001__scope__aveline", "private_10001__scope__ling"]:
            try:
                mgr = get_weighted_memory_manager(uid)
                memory_managers[uid] = mgr
                console.info(f"  手动创建: {uid}")
            except Exception as e:
                console.error(f"  创建失败 {uid}: {e}")

    config = DEFAULT_NIGHTLY_CONFIG.copy()
    config["auto_run"] = False
    config["distillation_threshold_hours"] = 0
    config["max_distill_per_night"] = 3  # 只蒸馏 3 条，快速验证

    processor = NightlyProcessor(config=config)

    for user_id, manager in memory_managers.items():
        print(f"\n--- 用户: {user_id} ---")

        # 统计
        total = len(manager.weighted_memories)
        undistilled = sum(1 for m in manager.weighted_memories.values() if not m.get("is_distilled"))
        console.info(f"  加权记忆总数: {total}, 未蒸馏: {undistilled}")

        if undistilled == 0:
            console.info("  没有待蒸馏的记忆，跳过")
            continue

        # 取一条未蒸馏记忆的内容看看
        sample = None
        for mid, msg in manager.weighted_memories.items():
            if not msg.get("is_distilled"):
                sample = msg
                break
        if sample:
            console.info(f"  示例记忆 [{sample['id'][:8]}]: {sample.get('content', '')[:100]}")

        # 执行蒸馏
        try:
            distilled_count = await processor._distill_memories_async(user_id, manager)
            console.info(f"  蒸馏完成: {distilled_count} 条")
        except Exception as e:
            console.error(f"  蒸馏异常: {e}")
            traceback.print_exc()

    processor.stop()


# ─────────────────────────────────────────────────────────
# 4. 测试 journal model hint
# ─────────────────────────────────────────────────────────
async def test_model_config():
    """检查模型配置"""
    print("\n" + "=" * 70)
    print("[TEST 4] 模型配置检查")
    print("=" * 70)

    from config.model_config import load_model_config, get_journal_model
    from memory.nightly_processor import get_memory_distillation_model

    config = load_model_config()
    console.info(f"journal_model: {get_journal_model()}")
    console.info(f"distillation_model: {get_memory_distillation_model()}")
    console.info(f"memory_models: {config.get('memory_models', {})}")

    # 检查 scheduler 状态
    from core.services.scheduler.task.task_scheduler import get_global_scheduler
    scheduler = get_global_scheduler()
    console.info(f"scheduler 类型: {type(scheduler).__name__}")
    if hasattr(scheduler, 'get_status'):
        console.info(f"scheduler 状态: {scheduler.get_status()}")


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="NightlyProcessor 诊断")
    parser.add_argument("--diary", action="store_true", help="只测日记生成")
    parser.add_argument("--distill", action="store_true", help="只测记忆蒸馏")
    parser.add_argument("--llm-only", action="store_true", help="只测 LLM 调用")
    args = parser.parse_args()

    run_all = not (args.diary or args.distill or args.llm_only)

    print("=" * 70)
    print("NightlyProcessor 诊断脚本")
    print("=" * 70)

    # 先检查模型配置
    await test_model_config()

    if run_all or args.llm_only:
        await test_llm_call_direct()

    if run_all or args.diary:
        await test_diary_generation()

    if run_all or args.distill:
        await test_distillation()

    print("\n" + "=" * 70)
    print("诊断完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
