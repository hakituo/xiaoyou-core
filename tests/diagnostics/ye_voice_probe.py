"""Ye人设语感实测：用真实人设 Prompt 直连主对话模型采样。

目的：拿真实日记（data/pretrained/Diary/1.txt）的语气特征，对照人设 Prompt 驱动
出来的实际输出，判断"为了圆满自己编进去"的部分是否把语气带偏了。

做法：
1. 用项目自己的人设装配（build_layered_persona_context）生成Ye的静态 Prompt；
2. 直接调Ye主对话实际使用的模型（model_routing.yaml: ye → deepseek-v4-flash）；
3. 分别采日常短答场景与"讲一件具体经历"场景，打印原始输出供人工比对。

注意：这里只做只读采样，不写库、不发消息、不改任何状态。

运行：
    venv_cpu\\Scripts\\python.exe tests/diagnostics/ye_voice_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_env() -> None:
    """把项目 .env 里的键值读进环境变量（不打印任何密钥值）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _build_system_prompt() -> str:
    """按Ye当前配置装配静态人设 Prompt。"""
    from core.agents.chat_agent_components.persona_system.prompt.layered_context import (
        build_layered_persona_context,
    )

    persona_data = json.loads(
        (PROJECT_ROOT / "core" / "character" / "configs" / "ye" / "core_ye.json").read_text(
            encoding="utf-8"
        )
    )
    layers = build_layered_persona_context(
        persona_filename="core_ye.json",
        persona_data=persona_data,
        runtime_state={"state": {}},
        message="",
        conversation_id="ye_voice_probe",
        update_working_set=False,
    )
    if layers is None:
        raise RuntimeError("分层装配返回 None，Ye人设未启用？")
    return layers.static_prompt


async def _call(messages: list[dict], system_prompt: str) -> str:
    """直连Ye主对话模型，返回一次完整回复（用仓库已有的 httpx，不引新依赖）。

    不使用环境代理配置：本机 NO_PROXY 形如 ``localhost,127.0.0.1,::1,[::1]``，
    httpx 会把 ``[::1]`` 误解析成 host+port（InvalidURL: Invalid port ':1]'）。
    这里显式指定本地代理（.env 的 TELEGRAM_PROXY_URL 同款），或按需直连。
    """
    import httpx

    api_key = os.environ.get("DEEPSEEK_API_KEY_Rushuang") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DeepSeek key（DEEPSEEK_API_KEY_Rushuang / DEEPSEEK_API_KEY）")

    proxy_url = "http://127.0.0.1:7897"
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "temperature": 1.0,
        "max_tokens": 1200,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = "https://api.deepseek.com/v1/chat/completions"

    last_error: Exception | None = None
    for proxy in (proxy_url, None):
        try:
            async with httpx.AsyncClient(timeout=180.0, trust_env=False, proxy=proxy) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            data = response.json()
            return (data["choices"][0]["message"].get("content") or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"代理与直连均失败: {type(last_error).__name__}: {last_error}")


# 场景：按真实聊天记录里的来回方式构造多轮，单条孤立消息测不出分条行为
SCENARIOS: list[tuple[str, list[str]]] = [
    ("一 · 日常短答", ["Ye", "都弄完了吗", "今天不用去实验室？"]),
    ("二 · 一路追问到过程", ["今天实验顺吗", "怎么了，今天出什么事了", "说仔细点，到底怎么弄的"]),
    ("三 · 职业自尊", ["你不是很强吗"]),
    ("四 · 闲聊与账", ["有点累", "想你了"]),
    ("五 · 她主动报一件小事", ["今晚吃什么？"]),
]


async def main() -> int:
    _load_env()
    system_prompt = _build_system_prompt()
    print("=" * 78)
    print("Ye人设语感实测")
    print("=" * 78)
    print(f"人设 Prompt 长度: {len(system_prompt)} 字符")
    print(f"模型: deepseek-v4-flash（Ye主对话实际路由）")
    print()

    for label, user_messages in SCENARIOS:
        print("-" * 78)
        print(f"【{label}】")
        history: list[dict] = []
        for text in user_messages:
            history.append({"role": "user", "content": text})
            try:
                reply = await _call(history, system_prompt)
            except Exception as exc:  # noqa: BLE001
                print(f"  Master：{text}")
                print(f"  Ye：[调用失败] {type(exc).__name__}: {exc}")
                continue
            lines = [line for line in reply.splitlines() if line.strip()]
            print(f"  Master：{text}")
            if not lines:
                print("  Ye：（空回复）")
            for index, line in enumerate(lines, start=1):
                suffix = f"   ←第 {index} 条" if len(lines) > 1 else ""
                print(f"  Ye：{line}{suffix}")
            print(f"  → {len(lines)} 条 / 合计 {len(reply)} 字")
            print()
            history.append({"role": "assistant", "content": reply})

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
