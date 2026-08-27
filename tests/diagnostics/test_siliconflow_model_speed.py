#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SiliconFlow 多模型平均响应速度测试

测试指标：
- 首字节延迟（TTFB）：从发请求到拿到第一个 content chunk 的时间
- 完整生成时间：从发请求到流式结束的总时间
- 生成字符数：用于估算生成速率

每个模型重复测 N 次（默认 5 次），输出 min/avg/max。

用法：
    python test_siliconflow_model_speed.py
    python test_siliconflow_model_speed.py --rounds 3
"""
import os
import sys
import asyncio
import time
import argparse
import statistics
from pathlib import Path

# 加载 .env
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import aiohttp

API_KEY = os.getenv("SILICONFLOW_API_KEY")
BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"

# 待测模型列表（与 model_routing.yaml 中 SiliconFlow 实际使用的模型对齐）
MODELS = [
    "deepseek-ai/DeepSeek-V4-Flash",        # Active Care 决策/自动进食/优先级分析
    "Pro/MiniMaxAI/MiniMax-M2.5",            # 日记/总结导出
    "Pro/moonshotai/Kimi-K2.5",              # 当前 provider 兜底默认
    "Pro/moonshotai/Kimi-K2.6",              # 用户指定的新 fallback
    "Qwen/Qwen3-VL-32B-Instruct",            # 视觉理解（纯文本 prompt 测速）
]

# 统一测试 prompt（中等长度，模拟实际对话场景）
TEST_PROMPT = "请用三句话介绍一下Python语言的特点，要简明扼要。"


async def measure_one(session: aiohttp.ClientSession, model: str, max_tokens: int = 300):
    """测一次调用，返回 (ttfb, total_time, char_count, error)"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    ttfb = None
    char_count = 0
    start = time.monotonic()

    try:
        async with session.post(BASE_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                return None, None, 0, f"HTTP {resp.status}: {text[:200]}"
            buffer = b""
            async for chunk in resp.content.iter_any():
                buffer += chunk
                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        try:
                            data = __import__("json").loads(line[6:])
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                # 跳过 reasoning_content，只测 content
                                content = delta.get("content", "")
                                if content:
                                    if ttfb is None:
                                        ttfb = time.monotonic() - start
                                    char_count += len(content)
                        except Exception:
                            continue
            total = time.monotonic() - start
            return ttfb, total, char_count, None
    except asyncio.TimeoutError:
        return ttfb, time.monotonic() - start, char_count, "TimeoutError"
    except Exception as e:
        return ttfb, time.monotonic() - start, char_count, f"{type(e).__name__}: {e}"


def fmt(stats, key):
    """格式化 min/avg/max"""
    vals = [s[key] for s in stats if s.get(key) is not None]
    if not vals:
        return "  N/A"
    return f"min={min(vals):.2f}s avg={statistics.mean(vals):.2f}s max={max(vals):.2f}s"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=5, help="每个模型重复测试次数")
    parser.add_argument("--max-tokens", type=int, default=300, help="单次生成最大 token 数")
    parser.add_argument("--timeout", type=int, default=120, help="单次请求总超时秒数")
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] 未找到 SILICONFLOW_API_KEY，请检查 .env")
        sys.exit(1)

    print(f"SiliconFlow 多模型测速（每模型 {args.rounds} 次，max_tokens={args.max_tokens}）")
    print(f"Prompt: {TEST_PROMPT}")
    print("=" * 80)

    # 用 sock_read 兜底，避免单次卡死整个测试
    timeout = aiohttp.ClientTimeout(total=args.timeout, connect=10, sock_read=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for model in MODELS:
            print(f"\n>>> {model}")
            stats = []
            for i in range(args.rounds):
                ttfb, total, chars, err = await measure_one(session, model, args.max_tokens)
                if err:
                    print(f"  [{i+1}/{args.rounds}] FAIL: {err}")
                    stats.append({"ttfb": ttfb, "total": total, "chars": chars, "error": err})
                else:
                    rate = chars / total if total > 0 else 0
                    print(f"  [{i+1}/{args.rounds}] TTFB={ttfb:.2f}s total={total:.2f}s chars={chars} rate={rate:.1f}c/s")
                    stats.append({"ttfb": ttfb, "total": total, "chars": chars, "error": None})

            # 汇总
            ok = [s for s in stats if not s.get("error")]
            fail = [s for s in stats if s.get("error")]
            print(f"  --- 汇总（成功 {len(ok)}/{len(stats)}）---")
            if ok:
                print(f"  首字节延迟: {fmt(ok, 'ttfb')}")
                print(f"  完整生成:   {fmt(ok, 'total')}")
                avg_chars = statistics.mean(s["chars"] for s in ok)
                avg_total = statistics.mean(s["total"] for s in ok)
                if avg_total > 0:
                    print(f"  平均速率:   {avg_chars/avg_total:.1f} 字符/秒")
            if fail:
                print(f"  失败 {len(fail)} 次: {set(s['error'] for s in fail)}")

    print("\n" + "=" * 80)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
