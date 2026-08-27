#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实调用 DeepSeek API 流式请求，打印原始 SSE 数据，确认 usage chunk 格式"""

import asyncio
import json
import os
import sys

# 确保项目根目录在路径中
sys.path.insert(0, r"D:\AI\xiaoyou-core")

from core.llm.openai_compat.deepseek_client import DeepSeekClient


async def main():
    # 读取 API Key
    api_key = None
    try:
        from config.integrated_config import get_settings
        settings = get_settings()
        api_key = getattr(settings.model.llm, "api_key", None)
        if not api_key:
            api_key = os.getenv("DEEPSEEK_API_KEY")
    except Exception as e:
        print(f"[WARN] 无法读取 settings，尝试环境变量: {e}")
        api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        print("[ERROR] 未找到 DeepSeek API Key，请检查 settings 或 DEEPSEEK_API_KEY 环境变量")
        return

    client = DeepSeekClient(api_key=api_key, model="deepseek-v4-flash")
    await client.initialize()

    messages = [
        {"role": "system", "content": "你是一个 helpful assistant。"},
        {"role": "user", "content": "用一句话介绍 Python 的 asyncio 是什么。"},
    ]

    # 先看 payload 里有没有 stream_options
    payload = client._build_payload(messages, stream=True)
    print("\n" + "=" * 60)
    print("[1] 请求 Payload (检查 stream_options)")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    # 先直接用 aiohttp 发请求，打印原始 SSE 行
    import aiohttp
    print("\n" + "=" * 60)
    print("[2] 原始 SSE 响应（逐行打印）")
    print("=" * 60)

    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    raw_chunks = []
    try:
        async with session.post(client.base_url, json=payload) as resp:
            print(f"HTTP 状态码: {resp.status}")
            if resp.status != 200:
                print(await resp.text())
                return

            buffer = b""
            line_no = 0
            async for raw_chunk in resp.content.iter_any():
                if not raw_chunk:
                    continue
                buffer += raw_chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.strip()
                    if not line:
                        continue
                    line_no += 1
                    try:
                        decoded = line.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = repr(line)
                    print(f"  L{line_no:03d}: {decoded}")
                    raw_chunks.append(decoded)

                    # 尝试解析 data: 行
                    if line.startswith(b"data:"):
                        data_bytes = line[5:].strip()
                        if data_bytes != b"[DONE]":
                            try:
                                data = json.loads(data_bytes.decode("utf-8", errors="replace"))
                                if isinstance(data, dict) and "usage" in data and data["usage"]:
                                    print(f"\n  >>> !!! 发现 usage chunk: {json.dumps(data['usage'], ensure_ascii=False)}")
                            except Exception:
                                pass
    finally:
        await session.close()

    # 再用 DeepSeekClient.stream_chat 走正常链路，看会不会触发 log
    print("\n" + "=" * 60)
    print("[3] 通过 DeepSeekClient.stream_chat 走正常链路")
    print("=" * 60)

    full_content = ""
    usage_found = False
    async for chunk in client.stream_chat(messages):
        if isinstance(chunk, dict):
            if "content" in chunk:
                full_content += chunk["content"]
                print(chunk["content"], end="", flush=True)
            if "usage" in chunk:
                usage_found = True
                print(f"\n[INFO] stream_chat 返回了 usage: {chunk['usage']}")
            if "error" in chunk:
                print(f"\n[ERROR] {chunk}")
    print()
    print(f"\n[结果] 完整回复: {full_content[:100]}{'...' if len(full_content) > 100 else ''}")
    print(f"[结果] stream_chat 中是否遇到 usage chunk: {usage_found}")

    # 检查日志文件
    log_path = r"D:\AI\xiaoyou-core\logs\prompt_cache_stats.log"
    if os.path.exists(log_path):
        print("\n" + "=" * 60)
        print("[4] 日志文件最后 5 条 (检查 mode=stream 是否写入)")
        print("=" * 60)
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-5:]:
            try:
                rec = json.loads(line.strip())
                print(f"  [{rec.get('level')}] mode={rec.get('mode')} "
                      f"hit={rec.get('hit_tokens')} miss={rec.get('miss_tokens')} "
                      f"model={rec.get('model')}")
            except Exception:
                print(f"  (raw) {line.strip()[:100]}")

    await client.shutdown()


if __name__ == "__main__":
    # 切换到项目根目录，方便读取配置
    os.chdir(r"D:\AI\xiaoyou-core")
    asyncio.run(main())
