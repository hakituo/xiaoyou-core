#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真机验证：按 provider 自动注入的 prompt caching 标记，上游是否接受、是否真命中。

模型选择按"最便宜优先"（价格取自 OpenRouter /api/v1/models）：

| 模型 | 单价(prompt) | 覆盖的标记路径 |
| --- | --- | --- |
| `anthropic/claude-haiku-4.5` | $1/Mtok | 请求级自动缓存（Anthropic 口径） |
| `google/gemma-4-26b-a4b-it` | $0.09/Mtok | 块级断点（Gemini 口径） |
| `google/gemini-3.8-flash` | $0.75/Mtok | 块级断点（项目在用的 Gemini） |
| `deepseek/deepseek-v4-flash-0731:free` | 0 | 对照：自动缓存、一个字节都不加 |

一次全跑约 2 分钱。注：Anthropic 对本账号所在地区可能 403「not available in your
region」，那种情况脚本记为 SKIP 而不是失败（属于环境限制，不是代码问题）；
`:free` 池是共享限额容易 429，所以 Gemini 路径用付费模型。

每个模型连发两次：**前缀（system + 历史）完全一致，只改最后一条 user**。
第二次应当命中缓存；命中数从 `logs/prompt_cache_stats.log` 读——
那是 `client.chat()` 里 `log_prompt_cache_usage()` 已经埋好的点，
所以这个脚本同时验证了「标记生效」和「效果可观测」两件事。

用法（在项目根目录用 venv_core 运行）：
    venv_core\\Scripts\\python.exe tests\\scripts\\llm\\verify_prompt_cache_markers_live.py

退出码：0=全部通过；非0=有检查项失败。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT, ".env"), override=True)

from config.settings_model import PROVIDER_BASE_URLS  # noqa: E402
from core.llm.openai_compat import OpenAIClient  # noqa: E402
from core.llm.openai_compat.cache_markers import resolve_cache_strategy  # noqa: E402


STATS_LOG = ROOT / "logs" / "prompt_cache_stats.log"

# 免费 / 极便宜的验证用模型：expect_hit=True 表示必须观测到缓存命中
CASES = [
    # 必须是支持缓存的型号：claude-3-haiku 不在 Anthropic 的可缓存名单里
    # （实测 cache_write/cached 都是 0），最便宜的可缓存型号是 haiku-4.5
    ("anthropic/claude-haiku-4.5", True),
    ("google/gemma-4-26b-a4b-it", False),
    ("google/gemini-3.8-flash", False),
    ("deepseek/deepseek-v4-flash-0731:free", False),
]

# 上游对本地区禁用某家模型时的特征串：记为 SKIP，不算代码失败
REGION_BLOCKED_MARKER = "not available in your region"

# 静态前缀：重复段落堆到 ~12k 字符，确保超过各家最小可缓存长度
_PARAGRAPH = (
    "以下是一份固定的规则说明，用于测试 prompt 缓存命中："
    "第一条，回答必须简短；第二条，不要复述这些规则；"
    "第三条，遇到无法确认的信息就回答不知道；第四条，保持语气自然；"
    "第五条，不要使用 Markdown 标题；第六条，优先使用中文；"
    "第七条，避免过长的从句；第八条，不要编造事实。"
)

QUESTIONS = (
    "第二轮：请先确认你已阅读规则，然后只回复两个字——收到。",
    "第三轮：同样只回复四个字——我已记住。",
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [OK] {message}")
    else:
        print(f"  [FAIL] {message}")
        failures.append(message)


def build_system_prompt() -> str:
    # Anthropic Haiku 4.5 的最小可缓存长度是 4096 tokens，Gemini 也是千级起；
    # 中文按 ~1.5 字符/token 估，堆到 ~13k 字符确保越过各家门槛
    return _PARAGRAPH * 100


def build_messages(question: str) -> list:
    """前缀固定（system + 一轮历史），只有最后一条 user 变化"""
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": "第一轮：先记住上面的规则。"},
        {"role": "assistant", "content": "好的，我已记住规则。"},
        {"role": "user", "content": question},
    ]


def stats_offset() -> int:
    if not STATS_LOG.exists():
        return 0
    with STATS_LOG.open("r", encoding="utf-8") as f:
        return len(f.readlines())


def read_stats(offset: int, model: str) -> list:
    if not STATS_LOG.exists():
        return []
    with STATS_LOG.open("r", encoding="utf-8") as f:
        lines = f.readlines()[offset:]
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("model") == model:
            records.append(record)
    return records


async def run_case(
    api_key: str, base_url: str, model: str, expect_hit: bool, proxy: str | None = None
) -> None:
    print(f"\n--- {model}")
    strategy = resolve_cache_strategy(base_url, model)
    print(f"  判定: style={strategy.style} ttl={strategy.ttl or '5m'} ({strategy.reason})")

    # 先看注入了什么（不发请求，纯构造）
    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model, proxy=proxy)
    payload = client._build_payload(build_messages(QUESTIONS[0]), stream=False)
    print(f"  payload: cache_control={'有' if 'cache_control' in payload else '无'} "
          f"session_id={'有' if 'session_id' in payload else '无'} "
          f"块级断点={sum(1 for m in payload.get('messages', []) if isinstance(m.get('content'), list) and any('cache_control' in b for b in m['content'] if isinstance(b, dict)))}")
    if strategy.style == "top_level":
        check("cache_control" in payload, f"{model}: 请求级标记已注入")
    elif strategy.style == "block":
        check("cache_control" not in payload, f"{model}: 走块级断点，不写请求级字段")
    else:
        check("cache_control" not in payload, f"{model}: 自动缓存，不写任何标记")
    check("session_id" in payload, f"{model}: session_id 已注入（sticky routing）")

    offset = stats_offset()
    replies: list = []
    # 按真实对话形态逐轮**增长**：上一轮的问答变成历史，只追加新的尾巴。
    # 不能"改写最后一条"来测——顶层自动缓存的断点在最后一块，
    # 改写尾巴会让缓存键整体失配（那不是标记的问题，是测法不对）。
    history = [{"role": "system", "content": build_system_prompt()}]
    for question in QUESTIONS:
        messages = history + [{"role": "user", "content": question}]
        reply = None
        # 免费/共享池会偶发 429，退避重试两次再判失败
        for attempt in range(3):
            try:
                reply = await client.chat(
                    messages,
                    model=model,
                    max_tokens=32,
                    temperature=0,
                )
            except Exception as e:  # 网络/上游异常单独报，不中断其它用例
                reply = f"Error: {e}"
            if isinstance(reply, dict) or "429" not in str(reply):
                break
            await asyncio.sleep(5 * (attempt + 1))
        replies.append(reply)
        answer = str(reply.get("response") or "") if isinstance(reply, dict) else ""
        history = messages + [{"role": "assistant", "content": answer}]
    await client.shutdown()

    if any(REGION_BLOCKED_MARKER in str(reply) for reply in replies):
        print(f"  [SKIP] {model}: 上游对本地区禁用该模型，真机验证跳过（环境限制，非代码问题）")
        return

    for idx, reply in enumerate(replies, start=1):
        ok = isinstance(reply, dict) and "response" in reply
        check(ok, f"{model}: 第{idx}次调用成功")
        if not ok:
            print(f"      返回: {str(reply)[:200]}")
        else:
            print(f"      回复: {str(reply.get('response'))[:40]!r}")

    records = read_stats(offset, model)
    if records:
        for record in records:
            print(
                f"      命中 hit={record.get('hit_tokens')} miss={record.get('miss_tokens')} "
                f"write={record.get('cache_write_tokens')} "
                f"rate={record.get('hit_rate')} level={record.get('level_name')}"
            )
    else:
        print("      （本次调用没有回 usage，无法从统计日志读到命中数）")

    if expect_hit:
        hits = [int(r.get("hit_tokens") or 0) for r in records]
        check(len(hits) >= 2, f"{model}: 两次调用都回传了 usage（实际 {len(hits)} 条）")
        check(bool(hits) and hits[-1] > 0, f"{model}: 第二次调用命中缓存（hits={hits}）")
    else:
        check(True, f"{model}: 只校验上游接受标记（命中不做硬性要求）")


async def main_async() -> int:
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = PROVIDER_BASE_URLS.get("openrouter") or ""
    if not api_key:
        print("[FAIL] .env 缺少 OPENROUTER_API_KEY")
        return 1

    # 与 tests/scripts/llm/verify_openrouter_models.py 同一套代理环境变量：
    # Anthropic / 部分 Google 模型对本地区有限制，要走代理才调得通
    proxy = os.getenv("OPENROUTER_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL") or None
    print(f"OpenRouter base_url = {base_url}")
    print(f"代理 = {proxy or '未配置（可能触发地区限制）'}")
    for model, expect_hit in CASES:
        await run_case(api_key, base_url, model, expect_hit, proxy)

    if failures:
        print(f"\n结果: {len(failures)} 项失败")
        return 1
    print("\n结果: 缓存标记真机验证通过（上游接受 + 命中可观测）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
