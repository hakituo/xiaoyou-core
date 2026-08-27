"""端到端延迟测试: LLM (deepseek-v4-flash) + 火山引擎 TTS 全链路。

测量三个维度:
1. LLM TTFT (Time To First Token): 从发消息到收到第一个文本 chunk
2. LLM 完整响应时间: 从发消息到 response_done
3. TTS 合成时间: HTTP POST /api/v1/media/tts 从请求到收到完整 base64 音频
4. 模拟前端"按 TTS 按钮"全链路: LLM 完整响应 → TTS 合成 → base64 解码 → 文件大小

用法:
    venv_cpu\\Scripts\\python.exe tests\\scripts\\latency\\measure_e2e_latency.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\latency\\measure_e2e_latency.py --rounds 5
    venv_cpu\\Scripts\\python.exe tests\\scripts\\latency\\measure_e2e_latency.py --skip-tts  # 只测 LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# 让项目根目录可导入
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _pick_base_url() -> str:
    """自动探测后端端口 (8000-8050)"""
    for p in range(8000, 8051):
        try:
            r = urllib.request.urlopen(
                f"http://localhost:{p}/", timeout=1.0
            )
            if r.status == 200:
                return f"http://localhost:{p}"
        except Exception:
            pass
    return "http://localhost:8000"


BASE_URL = _pick_base_url()
WS_URL = BASE_URL.replace("http://", "ws://") + "/api/v1/ws"


def measure_llm_http(round_idx: int, prompt: str) -> dict:
    """用 HTTP SSE 测一轮 LLM: TTFT / total / 文本长度

    POST /api/v1/chat/message?stream=true, body=message JSON
    返回 SSE: data: {"type":"message","subtype":"response_chunk","content":"..."}
            data: {"type":"message","subtype":"response_done"}
            data: [DONE]
    """
    import requests

    print(f"\n--- LLM Round {round_idx} (HTTP SSE) ---")
    print(f"Prompt: {prompt[:60]}")

    payload = {
        "content": prompt,
        "conversation_id": f"latency_http_{int(time.time())}",
        "message_id": str(int(time.time() * 1000)),
    }

    t_send = time.time()
    first_token_time = None
    response_text = ""

    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/chat/message?stream=true",
            json=payload,
            stream=True,
            timeout=(15, 120),
            headers={"Accept": "text/event-stream"},
        )
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            return {
                "round": round_idx,
                "ttft_ms": None,
                "total_ms": (time.time() - t_send) * 1000,
                "text_len": 0,
                "text": "",
                "error": f"HTTP {resp.status_code}",
            }

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith("data: "):
                continue
            data_str = raw[6:]
            if data_str == "[DONE]":
                total = time.time() - t_send
                print(f"  完整响应: {total*1000:.0f}ms, 文本 {len(response_text)} 字")
                return {
                    "round": round_idx,
                    "ttft_ms": first_token_time * 1000 if first_token_time else None,
                    "total_ms": total * 1000,
                    "text_len": len(response_text),
                    "text": response_text,
                }
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "message":
                subtype = data.get("subtype")
                if subtype == "response_chunk":
                    content = data.get("content", "")
                    is_backchannel = bool(data.get("backchannel"))
                    if content and not is_backchannel:
                        if first_token_time is None:
                            first_token_time = time.time() - t_send
                            print(f"  TTFT: {first_token_time*1000:.0f}ms")
                        response_text += content
                elif subtype == "response_done":
                    total = time.time() - t_send
                    print(f"  完整响应: {total*1000:.0f}ms, 文本 {len(response_text)} 字")
                    return {
                        "round": round_idx,
                        "ttft_ms": first_token_time * 1000 if first_token_time else None,
                        "total_ms": total * 1000,
                        "text_len": len(response_text),
                        "text": response_text,
                    }
                elif subtype == "error":
                    print(f"  [ERROR] {data.get('message', data)}")
                    return {
                        "round": round_idx,
                        "ttft_ms": first_token_time * 1000 if first_token_time else None,
                        "total_ms": (time.time() - t_send) * 1000,
                        "text_len": len(response_text),
                        "text": response_text,
                        "error": data.get("message"),
                    }

        # 流自然结束 (没收到 [DONE] 或 response_done)
        total = time.time() - t_send
        print(f"  流结束: {total*1000:.0f}ms, 文本 {len(response_text)} 字")
        return {
            "round": round_idx,
            "ttft_ms": first_token_time * 1000 if first_token_time else None,
            "total_ms": total * 1000,
            "text_len": len(response_text),
            "text": response_text,
        }
    except Exception as e:
        print(f"  [EXCEPTION] {e}")
        return {
            "round": round_idx,
            "ttft_ms": first_token_time * 1000 if first_token_time else None,
            "total_ms": (time.time() - t_send) * 1000,
            "text_len": len(response_text),
            "text": response_text,
            "error": str(e),
        }


def measure_tts(text: str, voice: str = "Aveline") -> dict:
    """测 TTS 合成: HTTP POST /api/v1/media/tts"""
    import requests

    print(f"\n--- TTS 测试 ---")
    print(f"  文本 ({len(text)} 字): {text[:60]}...")
    print(f"  voice: {voice}")

    payload = {
        "text": text,
        "voice": voice,
        "text_lang": "zh",
        "speed": 1.0,
    }

    t_start = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/media/tts",
            json=payload,
            timeout=120,
        )
        elapsed = time.time() - t_start
        print(f"  HTTP {resp.status_code}, 耗时 {elapsed*1000:.0f}ms")

        if resp.status_code != 200:
            return {"ok": False, "elapsed_ms": elapsed * 1000, "error": resp.text[:200]}

        data = resp.json()
        if data.get("status") != "success":
            return {"ok": False, "elapsed_ms": elapsed * 1000, "error": str(data)[:200]}

        result = data.get("data", {})
        audio_b64 = result.get("audio_base64", "")
        audio_path = result.get("audio_path", "")

        # 估算解码后大小 (base64 → bytes)
        audio_bytes_len = len(audio_b64) * 3 // 4 if audio_b64 else 0

        print(f"  音频大小: {audio_bytes_len / 1024:.1f} KB ({audio_bytes_len} bytes)")
        print(f"  audio_path: {audio_path}")

        return {
            "ok": True,
            "elapsed_ms": elapsed * 1000,
            "audio_kb": audio_bytes_len / 1024,
            "text_len": len(text),
            "ms_per_char": elapsed * 1000 / max(len(text), 1),
        }
    except Exception as e:
        return {"ok": False, "elapsed_ms": (time.time() - t_start) * 1000, "error": str(e)}


def print_summary(llm_results: list[dict], tts_result: dict | None):
    """打印汇总表"""
    print("\n" + "=" * 72)
    print("延迟测试汇总")
    print("=" * 72)

    if llm_results:
        print("\n[LLM 链路] (deepseek-v4-flash + persona 系统 + 记忆注入)")
        print(f"{'轮次':<6} {'ack(ms)':<12} {'TTFT(ms)':<12} {'总耗时(ms)':<14} {'文本字数':<10}")
        print("-" * 60)
        acks, ttfts, totals, lens = [], [], [], []
        for r in llm_results:
            ack = r.get("ack_ms")
            ttft = r.get("ttft_ms")
            tot = r.get("total_ms")
            ln = r.get("text_len", 0)
            ack_s = f"{ack:.0f}" if ack else "N/A"
            ttft_s = f"{ttft:.0f}" if ttft else "N/A"
            print(f"{r['round']:<6} {ack_s:<12} {ttft_s:<12} {tot:<14.0f} {ln:<10}")
            if ack: acks.append(ack)
            if ttft: ttfts.append(ttft)
            totals.append(tot)
            lens.append(ln)

        if ttfts:
            print(f"\n  TTFT 平均: {sum(ttfts)/len(ttfts):.0f}ms (min={min(ttfts):.0f}, max={max(ttfts):.0f})")
        if totals:
            print(f"  完整响应 平均: {sum(totals)/len(totals):.0f}ms")
        if lens:
            print(f"  平均生成长度: {sum(lens)/len(lens):.0f} 字")

    if tts_result:
        print(f"\n[TTS 链路] (火山引擎, voice=Aveline)")
        if tts_result.get("ok"):
            print(f"  合成耗时: {tts_result['elapsed_ms']:.0f}ms")
            print(f"  音频大小: {tts_result['audio_kb']:.1f} KB")
            print(f"  文本长度: {tts_result['text_len']} 字")
            print(f"  每字耗时: {tts_result['ms_per_char']:.1f} ms/字")
        else:
            print(f"  失败: {tts_result.get('error', 'unknown')}")

    if llm_results and tts_result and tts_result.get("ok"):
        avg_llm = sum(r["total_ms"] for r in llm_results) / len(llm_results)
        avg_tts = tts_result["elapsed_ms"]
        print(f"\n[全链路] LLM 完整响应 + TTS 合成")
        print(f"  LLM 平均: {avg_llm:.0f}ms")
        print(f"  TTS 平均: {avg_tts:.0f}ms")
        print(f"  串行总计: {(avg_llm + avg_tts):.0f}ms ({(avg_llm + avg_tts)/1000:.2f}s)")
        print(f"  → 这是'用户发消息 → 按TTS → 听到声音'的串行总延迟")
        print(f"  → 若 LLM 流式 + 按句并行 TTS, 理论可降到 TTFT + 单句 TTS ≈ { (sum(r['ttft_ms'] for r in llm_results if r.get('ttft_ms'))/max(len([r for r in llm_results if r.get('ttft_ms')]),1)):.0f} + {avg_tts/max(len(llm_results),1):.0f}ms")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="端到端延迟测试: LLM + TTS")
    parser.add_argument("--rounds", type=int, default=3, help="LLM 测试轮数 (默认 3)")
    parser.add_argument("--skip-tts", action="store_true", help="跳过 TTS 测试")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 测试")
    parser.add_argument(
        "--prompt", default="你好，请用一句话介绍你自己。",
        help="LLM 测试 prompt"
    )
    parser.add_argument("--voice", default="Aveline", help="TTS voice (默认 Aveline)")
    args = parser.parse_args()

    print(f"后端: {BASE_URL}")

    llm_results = []
    tts_text_for_test = ""

    if not args.skip_llm:
        print(f"\n用 HTTP SSE 测 LLM...")
        for i in range(1, args.rounds + 1):
            res = measure_llm_http(i, args.prompt)
            llm_results.append(res)
            if i < args.rounds:
                time.sleep(2)
        # 用最后一轮的回复做 TTS 测试文本
        if llm_results and llm_results[-1].get("text"):
            tts_text_for_test = llm_results[-1]["text"]

    if not args.skip_tts:
        if not tts_text_for_test:
            # 没跑 LLM 或失败, 用固定文本测 TTS
            tts_text_for_test = "你好，我是Aveline，很高兴见到你。今天天气不错，我们一起聊聊天吧。"
        tts_result = measure_tts(tts_text_for_test, voice=args.voice)
    else:
        tts_result = None

    print_summary(llm_results, tts_result)


if __name__ == "__main__":
    main()
