import asyncio
import time
import aiohttp
import json
import os
import sys

# 导入配置逻辑 (模拟 adapter 环境)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
sys.path.append(PROJECT_ROOT)

XIAOYOU_HTTP_BASE_URL = "http://127.0.0.1:8000"
XIAOYOU_WS_URL = "ws://127.0.0.1:8000/api/v1/ws"
XIAOYOU_ACCESS_TOKEN = "" # 如果有 Token 请填写

async def test_intent_latency(text: str):
    # 直接模拟逻辑：如果文本太短，adapter 层会跳过。
    # 这里我们模拟 adapter 的判断逻辑
    if len(text.strip()) <= 2:
        print(f"\n[模拟 Adapter 逻辑] 输入: '{text}' -> 长度 <= 2, 自动跳过识别 (耗时: 0.000s)")
        return

    url = f"{XIAOYOU_HTTP_BASE_URL}/api/v1/intent/classify"
    payload = {
        "text": text,
        "candidates": ["CLEAR_MEMORY", "SHOW_STATUS", "NONE"],
        "max_tokens": 64,
        "temperature": 0.0
    }
    headers = {}
    if XIAOYOU_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {XIAOYOU_ACCESS_TOKEN}"
    
    print(f"\n[测试意图识别] 输入: '{text}'")
    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=5) as resp:
                cost = time.time() - start
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ 成功: 耗时 {cost:.3f}s, 识别结果: {data.get('intent')} (置信度: {data.get('confidence')})")
                else:
                    print(f"❌ 失败: 状态码 {resp.status}, 耗时 {cost:.3f}s")
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}, 耗时 {time.time() - start:.3f}s")

async def test_chat_latency(text: str):
    # 模拟 WebSocket 握手耗时
    ws_url = f"{XIAOYOU_WS_URL}?client_id=test_script&user_id=test_user&platform=qq"
    print(f"\n[测试聊天响应] 输入: '{text}'")
    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, timeout=5) as ws:
                ws_ready = time.time() - start
                print(f"  - WebSocket 连接耗时: {ws_ready:.3f}s")
                
                payload = {
                    "type": "message",
                    "content": text,
                    "message_id": f"test_{int(time.time())}"
                }
                await ws.send_json(payload)
                
                # 等待首个 token 或完成
                first_token_time = None
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if not first_token_time:
                            first_token_time = time.time() - start
                            print(f"  - 首个响应 (TTFT) 耗时: {first_token_time:.3f}s")
                        
                        if data.get("type") == "message" and data.get("subtype") == "response_done":
                            break
                        if data.get("type") == "finish":
                            break
                
                total = time.time() - start
                print(f"✅ 总计耗时: {total:.3f}s")
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}, 耗时 {time.time() - start:.3f}s")

async def main():
    print("=== Xiaoyou Core 延迟验证脚本 ===")
    
    # 1. 测试短消息 (应该跳过意图识别)
    print("\n--- 场景 1: 短消息 (预期跳过识别) ---")
    # 注意：脚本直接调 API，不经过 adapter 的跳过逻辑，
    # 这里我们主要测试 API 本身的响应速度。
    await test_intent_latency("hi")
    
    # 2. 测试带指令关键词的消息
    print("\n--- 场景 2: 带指令关键词 (预期触发识别) ---")
    await test_intent_latency("帮我看看系统状态")
    
    # 3. 测试完整聊天链路
    print("\n--- 场景 3: 完整聊天链路 (WS) ---")
    await test_chat_latency("你好，请做个自我介绍")

if __name__ == "__main__":
    asyncio.run(main())
