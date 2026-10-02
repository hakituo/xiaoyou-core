#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互式注册云端模型：选 provider -> 选/填模型 -> 自动写入全部注册点。

背景：
    每接入一个新云端模型都要手改 4~5 个地方，漏一处就会出现"模型能选但发图走 VL 中转"
    "测试不认识这个模型"之类的半成品注册。本脚本把注册动作收敛成一条命令。

自动改动的注册点：
    1. config/settings_model.py            PROVIDER_DEFAULT_MODELS[<provider>] 追加型号
    2. core/llm/model_capabilities.py      VISION_MODEL_KEYWORDS 追加关键词（多模态时）
    3. tests/scripts/verify_vision_routing.py
                                           多模态用例追加 cloud:<provider>:<model>（多模态时）
                                           纯文本用例追加裸模型名（非多模态时）
    4. tests/scripts/llm/verify_openrouter_models.py
                                           MODELS 追加型号（仅 openrouter）
    5. config/yaml/sections/model_routing.yaml
                                           provider_default_models 设为该型号（仅 --set-default）

幂等：同一行已存在就跳过，重复运行不会产生重复条目。

用法：
    # 交互式（推荐）：选 provider -> 在线搜模型 -> 确认多模态 -> 预览 -> 写入
    venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py

    # 非交互式：直接指定
    venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py ^
        --provider openrouter --model x-ai/grok-4.20 --vision --yes

    # 只看会改什么，不落盘
    venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py --provider openrouter --model x-ai/grok-4.20 --vision --dry-run

    # 注册完顺带跑验证脚本 + 写当天更新日志
    venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py --provider openrouter --model x-ai/grok-4.20 --vision --yes --verify --record

    # 列出当前已注册的 provider 与模型
    venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py --list

常用参数：
    --provider        供应商（见 --list），不传则交互式选择
    --model           模型 ID，如 x-ai/grok-4.20；不传则交互式选择/手填
    --vision          标记为多模态（原生支持图片输入）
    --text            标记为纯文本模型
    --vision-keyword  写入多模态名单的关键词，默认取模型 ID 最后一段
    --set-default     同时把该型号设为 provider_default_models[<provider>]
    --search KEYWORD  在 OpenRouter 在线目录里按关键字搜索后选择（仅 openrouter）
    --offline         不联网，跳过在线目录
    --yes             非交互式确认，跳过所有询问
    --dry-run         只预览改动不写文件
    --verify          写完后自动跑 tests/scripts/verify_vision_routing.py
    --record          生成 payload 并调用 update_project_records.py 写入 docs/updates/ 当天文件
    --no-record       跳过写入更新日志（默认会写）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

SETTINGS_MODEL = REPO_ROOT / "config" / "settings_model.py"
MODEL_CAPABILITIES = REPO_ROOT / "core" / "llm" / "model_capabilities.py"
VISION_ROUTING_TEST = REPO_ROOT / "tests" / "scripts" / "verify_vision_routing.py"
OPENROUTER_VERIFY = REPO_ROOT / "tests" / "scripts" / "llm" / "verify_openrouter_models.py"
MODEL_ROUTING_YAML = REPO_ROOT / "config" / "yaml" / "sections" / "model_routing.yaml"
PAYLOAD_DIR = REPO_ROOT / "scripts" / "doc_records"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
NETWORK_TIMEOUT = 30
MAX_CANDIDATES = 20

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ---------------------------------------------------------------- 项目配置读取


def _load_provider_tables() -> tuple[dict[str, str], dict[str, list[str]]]:
    """读取 provider -> base_url 与 provider -> 已注册模型列表。"""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from config.settings_model import (  # noqa: PLC0415
            PROVIDER_BASE_URLS,
            PROVIDER_DEFAULT_MODELS,
        )

        return dict(PROVIDER_BASE_URLS), {k: list(v) for k, v in PROVIDER_DEFAULT_MODELS.items()}
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 导入 config.settings_model 失败，退回文本解析: {e}")
        return _parse_provider_tables_from_source()


def _parse_provider_tables_from_source() -> tuple[dict[str, str], dict[str, list[str]]]:
    """兜底：直接从 settings_model.py 文本里抠出两张表。"""
    text = SETTINGS_MODEL.read_text(encoding="utf-8")
    urls: dict[str, str] = {}
    models: dict[str, list[str]] = {}
    for provider, url in re.findall(r'"([a-z_]+)":\s*"(https?://[^"]+)"', text):
        urls.setdefault(provider, url)
    block = re.search(r"PROVIDER_DEFAULT_MODELS[^=]*=\s*\{(.*?)\n\}", text, re.S)
    if block:
        for provider, inner in re.findall(r'"([a-z_]+)":\s*\[(.*?)\]', block.group(1), re.S):
            models[provider] = re.findall(r'"([^"]+)"', inner)
    return urls, models


def _api_key_env(provider: str) -> str:
    return f"{provider.upper()}_API_KEY"


# ---------------------------------------------------------------- OpenRouter 目录


def _build_opener(proxy: str | None = None) -> urllib.request.OpenerDirector:
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def _fetch_openrouter_models(proxy: str | None = None) -> list[dict[str, Any]]:
    """拉取 OpenRouter 在线模型目录。"""
    req = urllib.request.Request(
        OPENROUTER_MODELS_URL, headers={"User-Agent": "xiaoyou-core/register-cloud-model"}
    )
    with _build_opener(proxy).open(req, timeout=NETWORK_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data") or []


def _is_multimodal(entry: dict[str, Any]) -> bool:
    modalities = (entry.get("architecture") or {}).get("input_modalities") or []
    return "image" in modalities


def _format_price(entry: dict[str, Any]) -> str:
    pricing = entry.get("pricing") or {}

    def _per_million(key: str) -> str:
        raw = pricing.get(key)
        try:
            return f"{float(raw) * 1_000_000:.2f}"
        except (TypeError, ValueError):
            return "-"

    return f"{_per_million('prompt')}/{_per_million('completion')}"


def _format_candidate(entry: dict[str, Any]) -> str:
    ctx = entry.get("context_length") or 0
    ctx_text = f"{ctx / 1000:.0f}K" if ctx else "-"
    return (
        f"{entry.get('id', ''):<42} 上下文 {ctx_text:<7} "
        f"多模态 {'是' if _is_multimodal(entry) else '否'}   "
        f"输入输出(每百万token) {_format_price(entry)}"
    )


# ---------------------------------------------------------------- 文本插入工具


def _find_sequence_span(text: str, header_pattern: str, open_ch: str, close_ch: str):
    """定位形如 `<header_pattern>[` 的序列，返回 (开括号下标, 闭括号下标)。"""
    m = re.search(header_pattern, text)
    if not m:
        return None
    start = text.find(open_ch, m.start())
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == open_ch:
            depth += 1
        elif text[idx] == close_ch:
            depth -= 1
            if depth == 0:
                return start, idx
    return None


def _quoted_literal(line: str) -> str:
    """取一行里第一个双引号包裹的字面量，用于忽略行尾注释后的比较。"""
    m = re.match(r'\s*"([^"]+)"', line)
    return m.group(1) if m else ""


def _append_line(text: str, header_pattern: str, new_line: str) -> tuple[str, bool]:
    """在目标序列的闭括号前追加一行；已存在同内容则原样返回。

    Args:
        text: 文件原文
        header_pattern: 匹配到序列开括号的正则（含开括号）
        new_line: 待插入的完整行（含缩进）

    Returns:
        (新文本, 是否发生改动)
    """
    # 元组用圆括号（VISION_MODEL_KEYWORDS），其余都是方括号列表
    open_ch = "(" if header_pattern.endswith(r"\(") else "["
    close_ch = ")" if open_ch == "(" else "]"
    span = _find_sequence_span(text, header_pattern, open_ch, close_ch)
    if span is None:
        raise ValueError(f"未能在文件中定位目标序列: {header_pattern}")

    start, end = span
    block = text[start:end]
    # 行尾可能带注释，只比较引号里的字面量，避免同一模型因注释不同而重复插入
    target = _quoted_literal(new_line) or new_line.strip().rstrip(",")

    if "\n" in block:
        # 多行序列：逐行比较，插到闭括号所在行之前
        for existing in block.splitlines():
            if (_quoted_literal(existing) or existing.strip().rstrip(",")) == target:
                return text, False
        line_start = text.rfind("\n", 0, end) + 1
        return text[:line_start] + new_line + "\n" + text[line_start:], True

    # 单行序列：开闭括号同行，必须就地插进括号内。
    # 若仍按「闭括号所在行的行首」插入，会插到整行之前、落到上一个 provider 条目
    # 后面，直接把字典结构写坏（siliconflow 曾踩过：SyntaxError: ':' expected）。
    for existing in re.findall(r'"([^"]+)"', block):
        if existing == target:
            return text, False
    item = target if target.startswith('"') else f'"{target}"'
    # 末元素后面可能已有逗号（如 ["a", "b",]），只补空格即可
    sep = " " if text[end - 1] in ",[" else ", "
    return text[:end] + sep + item + text[end:], True


def _upsert_yaml_default(text: str, provider: str, model: str) -> tuple[str, bool]:
    """在 model_routing.yaml 的 provider_default_models 段设置/追加 provider 默认模型。"""
    lines = text.splitlines(keepends=True)
    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s{2}provider_default_models:\s*$", line):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("model_routing.yaml 未找到 provider_default_models 段")

    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(lines[j]) - len(lines[j].lstrip())
        if indent <= 2:
            end_idx = j
            break

    target = rf"^\s{{4}}{re.escape(provider)}:\s*(.+)$"
    for j in range(header_idx + 1, end_idx):
        m = re.match(target, lines[j])
        if m:
            if m.group(1).strip() == model:
                return text, False
            lines[j] = lines[j][: m.start(1)] + model + "\n"
            return "".join(lines), True

    lines.insert(end_idx, f"    {provider}: {model}\n")
    return "".join(lines), True


# ---------------------------------------------------------------- 交互选择


def _ask(prompt: str, default: str = "") -> str:
    suffix = f"（默认 {default}）" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return answer or default


def _choose_provider(providers: dict[str, str], registered: dict[str, list[str]]) -> str:
    names = sorted(providers)
    print("\n可选 provider：")
    for i, name in enumerate(names, 1):
        key_state = "已配 Key" if os.getenv(_api_key_env(name)) else "未配 Key"
        models = registered.get(name) or []
        print(f"  {i}. {name:<12} [{key_state}]  已注册 {len(models)} 个: {', '.join(models[:3]) or '无'}")

    while True:
        raw = _ask("\n选择 provider（序号或名称）", "openrouter")
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        if raw in names:
            return raw
        print(f"  [WARN] 无效选择: {raw}")


def _choose_model(provider: str, args) -> tuple[str, bool | None]:
    """返回 (模型 ID, 是否多模态)；是否多模态可能是 None（未知）。"""
    if args.model:
        return args.model, None

    proxy = os.getenv("OPENROUTER_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL") or None

    if provider == "openrouter" and not args.offline:
        use_online = args.search is not None or _ask(
            "从 OpenRouter 在线目录搜索模型？[Y/n]", "Y"
        ).upper().startswith("Y")
        if use_online:
            keyword = args.search or _ask("搜索关键字（如 grok / gemini / qwen）")
            try:
                entries = _fetch_openrouter_models(proxy)
            except Exception as e:  # noqa: BLE001
                print(f"  [WARN] 拉取在线目录失败，改为手填: {e}")
            else:
                hits = [e for e in entries if keyword.lower() in str(e.get("id", "")).lower()]
                if not hits:
                    print(f"  [WARN] 在线目录没匹配到 {keyword!r}，改为手填")
                else:
                    print(f"\n匹配到 {len(hits)} 个模型，显示前 {min(len(hits), MAX_CANDIDATES)} 个：")
                    for i, entry in enumerate(hits[:MAX_CANDIDATES], 1):
                        print(f"  {i}. {_format_candidate(entry)}")
                    while True:
                        raw = _ask("\n选择模型（序号，或直接输入模型 ID）")
                        if raw.isdigit() and 1 <= int(raw) <= min(len(hits), MAX_CANDIDATES):
                            picked = hits[int(raw) - 1]
                            return str(picked.get("id")), _is_multimodal(picked)
                        if raw:
                            return raw, None
                        print("  [WARN] 请输入序号或模型 ID")

    return _ask("模型 ID（如 x-ai/grok-4.20）"), None


def _resolve_vision_flag(provider: str, model: str, known: bool | None, args) -> bool:
    if args.vision:
        return True
    if args.text:
        return False
    if known is not None:
        hint = "是" if known else "否"
        answer = _ask(f"该模型是否原生多模态（支持图片输入）？[y/N] 在线目录判定: {hint}", "Y" if known else "N")
        return answer.upper().startswith("Y")
    answer = _ask(f"{provider}/{model} 是否原生多模态（支持图片输入）？[y/N]", "N")
    return answer.upper().startswith("Y")


# ---------------------------------------------------------------- 写入动作


def _build_edits(provider: str, model: str, vision: bool, keyword: str, set_default: bool) -> list[dict]:
    """构造待执行的改动清单（先全部算好，再统一落盘）。"""
    edits: list[dict] = []

    def _add(path: Path, header: str, line: str, desc: str, kind: str = "append"):
        edits.append(
            {
                "path": path,
                "header": header,
                "line": line,
                "desc": desc,
                "kind": kind,
                "rel": path.relative_to(REPO_ROOT).as_posix(),
            }
        )

    _add(
        SETTINGS_MODEL,
        rf'"{re.escape(provider)}"\s*:\s*\[',
        f'        "{model}",',
        f"PROVIDER_DEFAULT_MODELS['{provider}'] 追加型号",
    )

    if vision:
        _add(
            MODEL_CAPABILITIES,
            r"VISION_MODEL_KEYWORDS[^=]*=\s*\(",
            f'    "{keyword}",',
            "VISION_MODEL_KEYWORDS 追加多模态关键词",
        )
        _add(
            VISION_ROUTING_TEST,
            r"multimodal\s*=\s*\[",
            f'        "cloud:{provider}:{model}",',
            "视觉路由测试追加多模态用例",
        )
        if model != keyword:
            _add(
                VISION_ROUTING_TEST,
                r"multimodal\s*=\s*\[",
                f'        "{model}",',
                "视觉路由测试追加裸模型名用例",
            )
    else:
        _add(
            VISION_ROUTING_TEST,
            r"text_models\s*=\s*\[",
            f'        "{model}",',
            "视觉路由测试追加纯文本用例",
        )

    # OpenRouter 连通性测试与是否多模态无关，只要是 openrouter 池里的型号都应纳入
    if provider == "openrouter":
        _add(
            OPENROUTER_VERIFY,
            r"MODELS\s*=\s*\[",
            f'    "{model}",',
            "OpenRouter 连通性测试追加型号",
        )

    if set_default:
        edits.append(
            {
                "path": MODEL_ROUTING_YAML,
                "header": None,
                "provider": provider,
                "model": model,
                "desc": f"model_routing.yaml 把 provider_default_models['{provider}'] 设为该型号",
                "kind": "yaml_default",
                "rel": MODEL_ROUTING_YAML.relative_to(REPO_ROOT).as_posix(),
            }
        )

    return edits


def _apply_edits(edits: list[dict], dry_run: bool) -> list[str]:
    """按文件分组执行改动，返回实际发生变化的相对路径列表。"""
    by_path: dict[Path, list[dict]] = {}
    for edit in edits:
        by_path.setdefault(edit["path"], []).append(edit)

    changed: list[str] = []
    for path, group in by_path.items():
        original = path.read_text(encoding="utf-8")
        text = original
        applied: list[str] = []
        for edit in group:
            if edit["kind"] == "yaml_default":
                text, ok = _upsert_yaml_default(text, edit["provider"], edit["model"])
            else:
                text, ok = _append_line(text, edit["header"], edit["line"])
            label = "[将写入]" if dry_run else "[写入]"
            applied.append(f"    {label if ok else '[跳过 已存在]'} {edit['desc']}")
            if ok and edit["rel"] not in changed:
                changed.append(edit["rel"])

        print(f"\n  {path.relative_to(REPO_ROOT).as_posix()}")
        for line in applied:
            print(line)

        if not dry_run and text != original:
            path.write_text(text, encoding="utf-8")

    if dry_run:
        print("\n[DRY-RUN] 未写入任何文件")
        return []
    return changed


# ---------------------------------------------------------------- 记录与验证


def _today() -> tuple[str, str]:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from core.utils.time.time_utils import today_str  # noqa: PLC0415

        date_text = today_str()
    except Exception:  # noqa: BLE001
        date_text = datetime.now().strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[datetime.now().weekday()]
    return date_text, weekday


def _write_record(provider: str, model: str, vision: bool, changed: list[str]) -> None:
    date_text, weekday = _today()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").lower()
    payload_path = PAYLOAD_DIR / f"_payload_register_{provider}_{safe}_{date_text.replace('-', '')}.json"

    mode_text = "原生多模态（发图走一阶段直通）" if vision else "纯文本模型"
    payload = {
        "updates": [
            {
                "date": date_text,
                "weekday": weekday,
                "title": f"注册 {provider} 模型 {model}",
                "background": f"通过 scripts/model_registry/register_cloud_model.py 注册新模型：provider={provider}，model={model}，{mode_text}。",
                "fixes": [f"{path}: {edit_desc}" for path, edit_desc in zip(changed, ["自动追加注册项"] * len(changed))]
                or ["无文件改动（全部注册项已存在）"],
                "verification": [
                    "venv_core\\Scripts\\python.exe scripts\\model_registry\\register_cloud_model.py --list -> 确认模型已在注册池内"
                ],
                "notes": [
                    "本次由注册脚本自动写入，只做注册不改业务路由；需要切场景请改 config/yaml/sections/model_routing.yaml 对应项"
                ],
            }
        ]
    }
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n[OK] 已生成记录载荷: {payload_path.relative_to(REPO_ROOT).as_posix()}")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "doc_records" / "update_project_records.py"),
            "--payload-file",
            str(payload_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(result.stdout.strip() or result.stderr.strip())


def _run_verify() -> None:
    print("\n[验证] 运行 tests/scripts/verify_vision_routing.py")
    result = subprocess.run(
        [sys.executable, str(VISION_ROUTING_TEST)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tail = "\n".join((result.stdout or "").strip().splitlines()[-8:])
    print(tail or result.stderr)
    print(f"[验证] 退出码 {result.returncode}")


# ---------------------------------------------------------------- 主流程


def _print_list(providers: dict[str, str], registered: dict[str, list[str]]) -> None:
    print("\n当前已注册的 provider 与模型：")
    for name in sorted(providers):
        models = registered.get(name) or []
        key_state = "已配 Key" if os.getenv(_api_key_env(name)) else "未配 Key"
        print(f"\n  {name}  [{key_state}]  base_url={providers[name]}")
        for model in models:
            print(f"    - {model}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="交互式注册云端模型（provider -> 模型 -> 自动写入全部注册点）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--provider", help="供应商，如 openrouter / deepseek / siliconflow")
    parser.add_argument("--model", help="模型 ID，如 x-ai/grok-4.20")
    parser.add_argument("--vision", action="store_true", help="标记为原生多模态模型")
    parser.add_argument("--text", action="store_true", help="标记为纯文本模型")
    parser.add_argument("--vision-keyword", help="写入多模态名单的关键词，默认取模型 ID 最后一段")
    parser.add_argument("--set-default", action="store_true", help="同时设为 provider_default_models 默认值")
    parser.add_argument("--search", nargs="?", const="", help="在 OpenRouter 在线目录按关键字搜索后选择")
    parser.add_argument("--offline", action="store_true", help="不联网，跳过在线目录")
    parser.add_argument("--yes", action="store_true", help="非交互式确认")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写文件")
    parser.add_argument("--verify", action="store_true", help="写完后自动跑视觉路由验证脚本")
    parser.add_argument("--record", action="store_true", help="写入 docs/updates/ 当天文件（默认行为，此处显式声明）")
    parser.add_argument("--no-record", action="store_true", help="跳过写入 docs/updates/ 当天文件")
    parser.add_argument("--list", action="store_true", help="只列出已注册 provider 与模型后退出")
    args = parser.parse_args()

    providers, registered = _load_provider_tables()

    if args.list:
        _print_list(providers, registered)
        return 0

    provider = (args.provider or "").strip()
    if not provider:
        provider = _choose_provider(providers, registered)
    provider = provider.lower()
    if provider not in providers:
        print(f"[FAIL] 未知 provider: {provider}")
        print(f"       可选: {', '.join(sorted(providers))}")
        return 1

    model, known_vision = _choose_model(provider, args)
    model = (model or "").strip()
    if not model:
        print("[FAIL] 未提供模型 ID")
        return 1
    if '"' in model:
        print("[FAIL] 模型 ID 不能包含双引号")
        return 1

    vision = _resolve_vision_flag(provider, model, known_vision, args)
    keyword = (args.vision_keyword or "").strip() or model.rsplit("/", 1)[-1]

    print("\n" + "=" * 68)
    print(f"将注册: cloud:{provider}:{model}")
    print(f"多模态: {'是' if vision else '否'}" + (f"（关键词 {keyword}）" if vision else ""))
    print("=" * 68)

    edits = _build_edits(provider, model, vision, keyword, args.set_default)
    if not args.yes and not args.dry_run:
        answer = _ask("确认写入？[Y/n]", "Y")
        if not answer.upper().startswith("Y"):
            print("[取消] 未做任何改动")
            return 0

    changed = _apply_edits(edits, args.dry_run)

    if args.verify and not args.dry_run:
        _run_verify()

    if not args.no_record and not args.dry_run:
        _write_record(provider, model, vision, changed)

    print("\n完成。提示：")
    print("  - 配置改动需重启后端才生效")
    print(f"  - 业务里用模型路径 cloud:{provider}:{model} 即可选中")
    print("  - 要设为某场景默认，改 config/yaml/sections/model_routing.yaml 对应项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
