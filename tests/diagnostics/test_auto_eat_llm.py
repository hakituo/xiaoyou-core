"""诊断 auto-eat LLM 选食物是否正常工作（含增强 prompt 和社交决策）"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

async def main():
    from core.services.scheduler.task.task_scheduler import get_global_scheduler
    from core.utils.json_utils import extract_json_object
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        AUTO_EAT_DECISION_PROMPT,
    )
    from core.food.data import get_food, get_all_food

    scheduler = get_global_scheduler()
    model_path = "cloud:siliconflow:deepseek-ai/DeepSeek-V3.2"

    # 构建候选食物（模拟 snack 类型）
    items = []
    for food in get_all_food():
        if food.type == "snack":
            items.append({
                "food_id": food.id,
                "name": food.name,
                "type": food.type,
                "nutrition": {
                    "hunger": float(food.nutrition.hunger),
                    "thirst": float(food.nutrition.thirst),
                    "energy": float(food.nutrition.energy),
                    "health": float(food.nutrition.health),
                },
            })

    import json
    # 模拟增强 prompt 的上下文参数
    candidates_text = (
        f"上一餐food_id:none\n"
        f"候选:{json.dumps(items, ensure_ascii=False)}"
    )
    prompt = AUTO_EAT_DECISION_PROMPT.format(
        target_type="snack",
        hunger=30.0,
        thirst=40.0,
        mood_score=72.0,
        mood_desc="平静",
        activity="idle",
        digestion_desc="1件",
        meal_history="上一餐: cola\n",
        ling_context="同伴Ling: hunger=45, thirst=60, mood=70/100\n",
        candidates_text=candidates_text,
    )

    print(f"=== Prompt ({len(prompt)} chars) ===")
    print(prompt)
    print("\n=== LLM 调用中 (max_tokens=512) ===")

    raw_out = ""
    reasoning_out = ""
    chunk_count = 0
    async for chunk in scheduler.submit_llm_task(
        prompt,
        max_tokens=512,
        temperature=0.6,
        model_path=model_path,
    ):
        chunk_count += 1
        if isinstance(chunk, str):
            raw_out += chunk
            print(f"  chunk[{chunk_count}] str: {chunk[:80]}")
        elif isinstance(chunk, dict):
            if chunk.get("content"):
                raw_out += str(chunk.get("content") or "")
                print(f"  chunk[{chunk_count}] content: {str(chunk.get('content'))[:80]}")
            elif chunk.get("reasoning"):
                reasoning_out += str(chunk.get("reasoning") or "")
            elif chunk.get("error"):
                print(f"  chunk[{chunk_count}] ERROR: {chunk.get('error')}")

    print(f"\n=== 结果 ===")
    print(f"总 chunk 数: {chunk_count}")
    print(f"reasoning 长度: {len(reasoning_out)} chars")
    print(f"raw_out 长度: {len(raw_out)} chars")
    print(f"raw_out 内容: {raw_out!r}")
    
    obj = extract_json_object(raw_out)
    print(f"extract_json_object 结果: {obj}")

    if obj:
        picked = str(obj.get("food_id") or "").strip()
        reason = str(obj.get("reason") or "").strip()
        share = bool(obj.get("share_with_ling", False))
        chat = bool(obj.get("chat_while_eating", False))
        print(f"选中: {picked}, 理由: {reason}")
        print(f"分享给Ling: {share}, 边吃边聊: {chat}")
    else:
        print("解析失败！JSON 提取返回 None")

    # 测试2：Ling 很饿的情况
    print(f"\n=== 测试2: Ling 很饿 (hunger=20) ===")
    prompt2 = AUTO_EAT_DECISION_PROMPT.format(
        target_type="snack",
        hunger=50.0,
        thirst=70.0,
        mood_score=85.0,
        mood_desc="开心",
        activity="idle",
        digestion_desc="无",
        meal_history="",
        ling_context="同伴Ling: hunger=20, thirst=55, mood=45/100\n",
        candidates_text=candidates_text,
    )
    raw_out2 = ""
    async for chunk in scheduler.submit_llm_task(
        prompt2,
        max_tokens=512,
        temperature=0.6,
        model_path=model_path,
    ):
        if isinstance(chunk, str):
            raw_out2 += chunk
        elif isinstance(chunk, dict) and chunk.get("content"):
            raw_out2 += str(chunk.get("content") or "")

    print(f"raw_out: {raw_out2!r}")
    obj2 = extract_json_object(raw_out2)
    if obj2:
        print(f"选中: {obj2.get('food_id')}, 理由: {obj2.get('reason')}")
        print(f"分享给Ling: {obj2.get('share_with_ling')}, 边吃边聊: {obj2.get('chat_while_eating')}")
    else:
        print("解析失败！")

if __name__ == "__main__":
    asyncio.run(main())
