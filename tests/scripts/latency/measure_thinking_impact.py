"""直接调 DeepSeek API 对比 thinking 模式开关对延迟的影响。

绕过后端中间层, 纯测 LLM 原始 TTFT, 变量控制最干净。

三组对比:
- A: thinking on, reasoning_effort=high (后端当前默认)
- B: thinking on, reasoning_effort=low
- C: thinking off (不传 thinking 参数)

用法:
    venv_cpu\\Scripts\\python.exe tests\\scripts\\latency\\measure_thinking_impact.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\latency\\measure_thinking_impact.py --rounds 5
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

# 加载 .env
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash"

PROMPT = "你好，请用一句话介绍你自己。"


def measure_once(round_idx: int, mode: str) -> dict:
    """测一轮: mode = high/low/off, 用 requests 直连 DeepSeek API"""
    import json
    import requests

    print(f"\n--- Round {round_idx} [{mode}] ---")

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": True,
        "max_tokens": 200,
    }

    if mode == "high":
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
        payload["reasoning_effort"] = "high"
    elif mode == "low":
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
        payload["reasoning_effort"] = "low"
    # off: 不传

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    t_start = time.time()
    first_token_time = None
    full_text = ""
    thinking_text = ""

    try:
        resp = requests.post(
            BASE_URL,
            json=payload,
            headers=headers,
            stream=True,
            timeout=(15, 120),
        )
        if resp.status_code != 200:
            print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
            return {
                "round": round_idx, "mode": mode, "ttft_ms": None,
                "total_ms": (time.time() - t_start) * 1000,
                "visible_len": 0, "thinking_len": 0,
                "error": f"HTTP {resp.status_code}",
            }

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith("data: "):
                continue
            data_str = raw[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = data.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            # thinking 内容 (reasoning_content 字段)
            reasoning = delta.get("reasoning_content", "")
            if reasoning:
                if first_token_time is None:
                    first_token_time = time.time() - t_start
                    print(f"  首 thinking token: {first_token_time*1000:.0f}ms")
                thinking_text += reasoning
                continue

            content = delta.get("content", "") or ""
            if content:
                if first_token_time is None:
                    first_token_time = time.time() - t_start
                    print(f"  TTFT (可见内容): {first_token_time*1000:.0f}ms")
                full_text += content

        total = time.time() - t_start
        print(f"  完整: {total*1000:.0f}ms, 可见 {len(full_text)} 字, thinking {len(thinking_text)} 字")
        if thinking_text:
            print(f"  thinking 摘要: {thinking_text[:80]}...")

        return {
            "round": round_idx,
            "mode": mode,
            "ttft_ms": first_token_time * 1000 if first_token_time else None,
            "total_ms": total * 1000,
            "visible_len": len(full_text),
            "thinking_len": len(thinking_text),
        }
    except Exception as e:
        print(f"  [ERROR] {e}")
        return {
            "round": round_idx, "mode": mode, "ttft_ms": None,
            "total_ms": (time.time() - t_start) * 1000,
            "visible_len": 0, "thinking_len": 0,
            "error": str(e),
        }


def print_summary(results: dict[str, list[dict]]):
    print("\n" + "=" * 78)
    print("Thinking 模式对比 (直接调 DeepSeek API, 绕过后端)")
    print("=" * 78)
    print(f"{'模式':<8} {'TTFT均(ms)':<14} {'总耗时均(ms)':<16} {'可见字数':<10} {'thinking字数':<12}")
    print("-" * 66)

    for mode in ["high", "low", "off"]:
        rs = results.get(mode, [])
        if not rs:
            continue
        ttfts = [r["ttft_ms"] for r in rs if r.get("ttft_ms")]
        totals = [r["total_ms"] for r in rs]
        vis = [r["visible_len"] for r in rs]
        thk = [r["thinking_len"] for r in rs]

        ttft_avg = sum(ttfts) / len(ttfts) if ttfts else 0
        total_avg = sum(totals) / len(totals) if totals else 0
        vis_avg = sum(vis) / len(vis) if vis else 0
        thk_avg = sum(thk) / len(thk) if thk else 0

        print(f"{mode:<8} {ttft_avg:<14.0f} {total_avg:<16.0f} {vis_avg:<10.0f} {thk_avg:<12.0f}")

    print("\n[解读]")
    high_ttft = [r["ttft_ms"] for r in results.get("high", []) if r.get("ttft_ms")]
    off_ttft = [r["ttft_ms"] for r in results.get("off", []) if r.get("ttft_ms")]
    if high_ttft and off_ttft:
        h_avg = sum(high_ttft) / len(high_ttft)
        o_avg = sum(off_ttft) / len(off_ttft)
        diff = h_avg - o_avg
        pct = diff / h_avg * 100 if h_avg else 0
        print(f"  thinking high → off: TTFT 降低 {diff:.0f}ms ({pct:.0f}%)")
        print(f"  high TTFT: {h_avg:.0f}ms  vs  off TTFT: {o_avg:.0f}ms")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(description="DeepSeek thinking 模式延迟对比")
    parser.add_argument("--rounds", type=int, default=3, help="每组测试轮数 (默认 3)")
    parser.add_argument("--modes", default="high,low,off", help="测试模式, 逗号分隔")
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] DEEPSEEK_API_KEY 未设置")
        return

    print(f"DeepSeek API 直连测试")
    print(f"模型: {MODEL}")
    print(f"Prompt: {PROMPT}")
    print(f"每组 {args.rounds} 轮")

    modes = args.modes.split(",")
    results = {}
    for mode in modes:
        mode = mode.strip()
        results[mode] = []
        for i in range(1, args.rounds + 1):
            r = measure_once(i, mode)
            results[mode].append(r)
            time.sleep(1)

    print_summary(results)


if __name__ == "__main__":
    main()
