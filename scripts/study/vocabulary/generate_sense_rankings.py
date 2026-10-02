"""离线生成 vocabulary learner-sense ranking 草案。

本脚本是维护工具，不会被正常词书构建、runtime loader 或客户端 import。
它只允许 LLM 对 ECDICT 已有 candidate 做分组/排序，不允许新增翻译；输出默认
写到 ``output/`` 供人工 review，不能直接覆盖正式 ranking 配置。

示例：
    python scripts/study/vocabulary/generate_sense_rankings.py \
        --endpoint https://example.com/v1/chat/completions \
        --model some-model \
        --words perspective,figure,point
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.study.vocabulary.sense_ranking import (  # noqa: E402
    compile_sense_rankings,
)
from scripts.study.vocabulary.wordbook_builder import (  # noqa: E402
    DEFAULT_ECDICT_PATH,
    DEFAULT_OVERRIDES_PATH,
    load_ecdict_rows,
    load_overrides,
    parse_translations,
)

PROMPT_VERSION = 1
VALID_TIERS = frozenset({"core", "common", "specialized", "rare"})
ALIAS_SPLIT_RE = re.compile(r"[；;，,、/]+")
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "output" / "vocabulary_sense_rankings.generated.json"
)

SYSTEM_PROMPT = """You rank existing dictionary senses for an English vocabulary-learning app.
The goal is learner priority, not dictionary source order and not raw corpus count alone.
Consider modern real usage, generality, learner usefulness, semantic centrality, POS, and
whether a meaning is specialized, technical, literary, or rare.

Hard constraints:
- Use ONLY the supplied candidates. Never invent, rewrite, delete, or translate a meaning.
- Every candidate_id must appear exactly once in the output.
- You may group multiple candidate_ids when they express the same English sense.
- Do not combine genuinely different senses merely because their Chinese wording overlaps.
- rank=1 is the sense a general modern-English learner should learn first.
- sense_id must be a short stable English snake_case semantic label.
- tier must be one of: core, common, specialized, rare.
- confidence must be a number from 0 to 1.
- Return JSON only, with this shape:
  {"senses":[{"sense_id":"...","rank":1,"tier":"core",
  "candidate_ids":["c0"],"confidence":0.95}]}
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="离线用 LLM 为现有词典义项生成 learner-priority ranking 草案"
    )
    parser.add_argument("--ecdict", type=Path, default=DEFAULT_ECDICT_PATH)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument(
        "--endpoint",
        required=True,
        help="OpenAI-compatible chat-completions 完整 URL",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="从该环境变量读取 API key；留空变量值时不发送 Authorization",
    )
    parser.add_argument(
        "--words",
        default="",
        help="逗号分隔词头；为空时从 ECDICT 顺序扫描多义词",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def _ranking_pos(value: Any) -> str:
    pos = str(value or "").strip().lower()
    if pos == "a":
        return "adj"
    if pos in {"v", "vt", "vi"}:
        return "v"
    return pos


def _candidate_groups(
    rows: list[dict[str, str]],
    selected_words: set[str],
    overridden_words: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    explicit_selection = bool(selected_words)

    for row in rows:
        word = str(row.get("word", "")).strip().lower()
        if not word:
            continue
        if explicit_selection and word not in selected_words:
            continue
        if not explicit_selection and word in overridden_words:
            continue

        general, _, _ = parse_translations(row.get("translation", ""))
        by_pos: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        for source_index, item in enumerate(general):
            pos = _ranking_pos(item.get("type"))
            translation = str(item.get("translation", "")).strip()
            # 没有可靠 POS 就不猜，交给原词典顺序或人工 override。
            if not pos or not translation:
                continue
            by_pos.setdefault(pos, []).append(
                {
                    "id": f"c{source_index}",
                    "translation": translation,
                }
            )

        for pos, candidates in by_pos.items():
            if len(candidates) < 2:
                continue
            groups.append(
                {
                    "word": word,
                    "pos": pos,
                    "candidates": candidates,
                }
            )
            if limit > 0 and len(groups) >= limit:
                return groups
    return groups


def _request_json(
    endpoint: str,
    model: str,
    api_key: str,
    group: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    user_payload = {
        "word": group["word"],
        "pos": group["pos"],
        "candidates": group["candidates"],
    }
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 请求失败: {exc}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"LLM 响应缺少 choices[0].message.content: {payload}") from exc
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        )
    if not isinstance(content, str):
        raise ValueError("LLM message.content 不是字符串")

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("LLM 输出必须是 JSON object")
    return result


def _validate_result(
    group: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_senses = result.get("senses")
    if not isinstance(raw_senses, list) or not raw_senses:
        raise ValueError("LLM 输出缺少非空 senses")

    candidate_ids = {item["id"] for item in group["candidates"]}
    seen_candidates: set[str] = set()
    seen_sense_ids: set[str] = set()
    seen_ranks: set[int] = set()
    senses: list[dict[str, Any]] = []

    for raw in raw_senses:
        if not isinstance(raw, dict):
            raise ValueError("sense 必须是 object")
        sense_id = str(raw.get("sense_id", "")).strip()
        rank = raw.get("rank")
        tier = raw.get("tier")
        confidence = raw.get("confidence")
        ids = raw.get("candidate_ids")

        if not re.fullmatch(r"[a-z][a-z0-9_]*", sense_id):
            raise ValueError(f"非法 sense_id: {sense_id!r}")
        if sense_id in seen_sense_ids:
            raise ValueError(f"重复 sense_id: {sense_id}")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            raise ValueError(f"非法 rank: {rank!r}")
        if rank in seen_ranks:
            raise ValueError(f"重复 rank: {rank}")
        if tier not in VALID_TIERS:
            raise ValueError(f"非法 tier: {tier!r}")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise ValueError(f"非法 confidence: {confidence!r}")
        if not isinstance(ids, list) or not ids or not all(isinstance(v, str) for v in ids):
            raise ValueError(f"candidate_ids 非法: {ids!r}")

        unknown = set(ids) - candidate_ids
        duplicate = set(ids) & seen_candidates
        if unknown:
            raise ValueError(f"LLM 创造了不存在的 candidate: {sorted(unknown)}")
        if duplicate:
            raise ValueError(f"candidate 被重复归类: {sorted(duplicate)}")

        seen_sense_ids.add(sense_id)
        seen_ranks.add(rank)
        seen_candidates.update(ids)
        senses.append(
            {
                "sense_id": sense_id,
                "rank": rank,
                "tier": tier,
                "candidate_ids": list(ids),
                "confidence": float(confidence),
            }
        )

    missing = candidate_ids - seen_candidates
    if missing:
        raise ValueError(f"LLM 删除/遗漏了 candidate: {sorted(missing)}")
    return sorted(senses, key=lambda item: item["rank"])


def _aliases_for_candidates(
    candidates: list[dict[str, str]],
    ids: list[str],
) -> list[str]:
    by_id = {item["id"]: item["translation"] for item in candidates}
    aliases: list[str] = []
    seen: set[str] = set()
    for candidate_id in ids:
        translation = by_id[candidate_id]
        values = [translation, *ALIAS_SPLIT_RE.split(translation)]
        for value in values:
            alias = value.strip()
            key = re.sub(r"\s+", "", alias.lower())
            if alias and key not in seen:
                seen.add(key)
                aliases.append(alias)
    return aliases


def _ranking_entry(
    group: dict[str, Any],
    senses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "sense_id": sense["sense_id"],
            "rank": sense["rank"],
            "tier": sense["tier"],
            "aliases_zh": _aliases_for_candidates(
                group["candidates"], sense["candidate_ids"]
            ),
            "source": ["offline_llm"],
            "confidence": sense["confidence"],
        }
        for sense in senses
    ]


def _input_hash(groups: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        groups,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    args = _parse_args()
    if args.limit == 0 or args.limit < -1:
        raise SystemExit("--limit 必须为正整数或 -1（不限制）")

    selected_words = {
        word.strip().lower()
        for word in args.words.split(",")
        if word.strip()
    }
    rows = load_ecdict_rows(args.ecdict)
    overrides = load_overrides(args.overrides)
    groups = _candidate_groups(
        rows,
        selected_words,
        set(overrides),
        0 if args.limit == -1 else args.limit,
    )
    if not groups:
        print("没有找到满足条件的同 POS 多义词 candidate。")
        return 0

    api_key = os.getenv(args.api_key_env, "") if args.api_key_env else ""
    words: OrderedDict[str, dict[str, list[dict[str, Any]]]] = OrderedDict()
    for index, group in enumerate(groups, start=1):
        result = _request_json(
            args.endpoint,
            args.model,
            api_key,
            group,
            args.timeout,
        )
        senses = _validate_result(group, result)
        words.setdefault(group["word"], {})[group["pos"]] = _ranking_entry(
            group, senses
        )
        print(
            f"[{index}/{len(groups)}] {group['word']}/{group['pos']}: "
            f"{len(group['candidates'])} candidates -> {len(senses)} senses"
        )

    payload: dict[str, Any] = {
        "version": 1,
        "profile": "general_learner",
        "description": (
            "离线 LLM 基于现有词典 candidate 生成的 learner-priority 草案；"
            "需人工 review 后再合入正式 vocabulary_sense_rankings.json。"
        ),
        "generator": {
            "model": args.model,
            "endpoint": args.endpoint,
            "prompt_version": PROMPT_VERSION,
            "input_sha256": _input_hash(groups),
        },
        "words": words,
    }

    # 用正式 builder 同一 schema validator 做最后一道检查；不会联网。
    compile_sense_rankings(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"已生成待审查草案: {args.output}")
    print("正常词书构建不会自动读取该草案；人工 review 后再合入正式配置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
