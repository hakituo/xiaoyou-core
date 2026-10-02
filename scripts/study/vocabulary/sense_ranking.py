"""词书构建期的义项学习优先级排序。

这里的 ranking 表达的是 learner priority，而不是严格的 corpus sense frequency。
排序只作用于 builder 已解析出的普通释义；运行时 loader / 客户端不依赖本模块。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SENSE_RANKINGS_PATH = (
    PROJECT_ROOT / "config" / "study" / "vocabulary_sense_rankings.json"
)

_ALIAS_SPLIT_RE = re.compile(r"[；;，,、/]+")
_VERB_POS = frozenset({"v", "vt", "vi"})
_VALID_TIERS = frozenset({"core", "common", "specialized", "rare"})


def _clean_word(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_pos(value: Any) -> str:
    pos = str(value or "").strip().lower()
    return "adj" if pos == "a" else pos


def _pos_family(value: Any) -> str:
    """只合并动词细分类；绝不跨 noun / verb 等 POS 排序。"""
    pos = _normalize_pos(value)
    if pos in _VERB_POS:
        return "v"
    return pos


def _normalize_alias(value: Any) -> str:
    """只做排版归一化，不做中文关键词或语义启发式。"""
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _candidate_aliases(value: Any) -> frozenset[str]:
    text = str(value or "").strip()
    if not text:
        return frozenset()
    aliases = {_normalize_alias(text)}
    aliases.update(
        normalized
        for token in _ALIAS_SPLIT_RE.split(text)
        if (normalized := _normalize_alias(token))
    )
    return frozenset(alias for alias in aliases if alias)


def compile_sense_rankings(
    payload: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """校验并预编译 ranking 配置，构建时匹配为纯内存查找。"""
    if payload.get("version") != 1 or not isinstance(payload.get("words"), dict):
        raise ValueError("义项排序文件结构无效：需要 version=1 且 words 为对象")

    compiled: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for raw_word, raw_pos_map in payload["words"].items():
        word = _clean_word(raw_word)
        if not word or not isinstance(raw_pos_map, dict):
            raise ValueError(f"义项排序词条无效: {raw_word!r}")

        pos_map: dict[str, list[dict[str, Any]]] = {}
        for raw_pos, raw_senses in raw_pos_map.items():
            pos = _normalize_pos(raw_pos)
            if not pos or not isinstance(raw_senses, list) or not raw_senses:
                raise ValueError(f"义项排序 POS 无效: {word}/{raw_pos}")

            seen_ids: set[str] = set()
            seen_ranks: set[int] = set()
            seen_aliases: set[str] = set()
            senses: list[dict[str, Any]] = []
            for raw_sense in raw_senses:
                if not isinstance(raw_sense, dict):
                    raise ValueError(f"义项排序 sense 无效: {word}/{pos}")

                sense_id = str(raw_sense.get("sense_id", "")).strip()
                rank = raw_sense.get("rank")
                aliases = raw_sense.get("aliases_zh")
                if not sense_id or sense_id in seen_ids:
                    raise ValueError(
                        f"sense_id 缺失或重复: {word}/{pos}/{sense_id!r}"
                    )
                if (
                    not isinstance(rank, int)
                    or isinstance(rank, bool)
                    or rank <= 0
                    or rank in seen_ranks
                ):
                    raise ValueError(
                        f"rank 必须是唯一正整数: {word}/{pos}/{rank!r}"
                    )
                if not isinstance(aliases, list) or not aliases:
                    raise ValueError(
                        f"aliases_zh 不能为空: {word}/{pos}/{sense_id}"
                    )

                normalized_aliases = frozenset(
                    normalized
                    for alias in aliases
                    if (normalized := _normalize_alias(alias))
                )
                if not normalized_aliases:
                    raise ValueError(
                        f"aliases_zh 无有效值: {word}/{pos}/{sense_id}"
                    )
                duplicate_aliases = normalized_aliases & seen_aliases
                if duplicate_aliases:
                    duplicate = sorted(duplicate_aliases)[0]
                    raise ValueError(
                        f"同一 POS 下 alias 不能指向多个 sense: "
                        f"{word}/{pos}/{duplicate}"
                    )

                tier = raw_sense.get("tier")
                if tier is not None and tier not in _VALID_TIERS:
                    raise ValueError(
                        f"未知 tier: {word}/{pos}/{sense_id}/{tier!r}"
                    )
                confidence = raw_sense.get("confidence")
                if confidence is not None and (
                    isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))
                    or not 0 <= float(confidence) <= 1
                ):
                    raise ValueError(
                        f"confidence 必须在 0..1: "
                        f"{word}/{pos}/{sense_id}/{confidence!r}"
                    )

                senses.append(
                    {
                        **raw_sense,
                        "sense_id": sense_id,
                        "rank": rank,
                        "_aliases": normalized_aliases,
                    }
                )
                seen_ids.add(sense_id)
                seen_ranks.add(rank)
                seen_aliases.update(normalized_aliases)

            pos_map[pos] = sorted(senses, key=lambda item: item["rank"])
        compiled[word] = pos_map
    return compiled


def load_sense_rankings(
    path: Path = DEFAULT_SENSE_RANKINGS_PATH,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"义项排序文件结构无效: {path}")
    return compile_sense_rankings(payload)


def _rules_for_pos(
    pos: str,
    ranking: dict[str, list[dict[str, Any]]],
) -> Iterable[list[dict[str, Any]]]:
    """先用精确 POS；vt/vi 未命中时再使用通用 v 规则。"""
    exact = _normalize_pos(pos)
    if exact and exact in ranking:
        yield ranking[exact]
    if exact in {"vt", "vi"} and "v" in ranking:
        yield ranking["v"]


def _rank_for_translation(
    item: dict[str, Any],
    ranking: dict[str, list[dict[str, Any]]],
) -> int | None:
    pos = _normalize_pos(item.get("type"))
    if not pos:
        return None
    candidate_aliases = _candidate_aliases(item.get("translation"))
    if not candidate_aliases:
        return None

    for rules in _rules_for_pos(pos, ranking):
        matches = [
            rule
            for rule in rules
            if candidate_aliases & rule.get("_aliases", frozenset())
        ]
        if len(matches) == 1:
            return int(matches[0]["rank"])
        if len(matches) > 1:
            # 一条源翻译跨越多个已知 sense 时宁可保持原顺序，也不猜。
            return None
    return None


def rank_translations_by_sense(
    translations: Iterable[dict[str, Any]],
    ranking: dict[str, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    """只在同一 POS 家族的“明确匹配槽位”内部稳定重排。

    未匹配、POS 缺失或匹配歧义的 source item 保持原槽位不动；只有至少两个
    item 能明确映射到 ranking sense 时才发生交换。这样 ranking 数据不完整或
    外部词典更换时，不会把一个已知但低优先级 sense 擅自抬到未知 sense 前面。

    不同 POS 的槽位模式同样不变，因此 ``address/n`` 的 ranking 不可能影响
    ``address/v``。
    """
    result = list(translations)
    if not ranking or len(result) < 2:
        return result

    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, item in enumerate(result):
        family = _pos_family(item.get("type"))
        if not family:
            continue
        groups.setdefault(family, []).append((index, item))

    for members in groups.values():
        matched: list[tuple[int, int, int, dict[str, Any]]] = []
        for family_order, (source_index, item) in enumerate(members):
            rank = _rank_for_translation(item, ranking)
            if rank is not None:
                matched.append((source_index, rank, family_order, item))

        if len(matched) < 2:
            continue

        target_indices = [source_index for source_index, _, _, _ in matched]
        ordered_items = [
            item
            for _, _, _, item in sorted(
                matched,
                key=lambda value: (value[1], value[2]),
            )
        ]
        for target_index, item in zip(target_indices, ordered_items):
            result[target_index] = item
    return result
