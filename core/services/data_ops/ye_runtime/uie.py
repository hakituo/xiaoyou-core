"""叶运行态 UIE 字段选择、抽取与 span 合并。"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

from core.services.data_ops.ye_runtime.document import _clean_text
from core.services.data_ops.ye_runtime.merge import _add_candidate
from core.utils.logger import get_logger

logger = get_logger("YeRuntimeState")


def _select_uie_fields(text: str, config: Mapping[str, Any]) -> set[str]:
    if config.get("scene_write_mode", "automatic") == "tool":
        return set()
    uie_config = config.get("uie")
    if not text or not isinstance(uie_config, Mapping) or not uie_config.get("enabled", False):
        return set()
    fields: set[str] = set()
    if any(marker in text for marker in ("在", "到", "回", "路上")):
        fields.update(("location", "activity"))
    if "穿" in text or any(marker in text for marker in ("衣服", "裙", "裤", "T恤", "外套")):
        fields.add("clothing")
    if any(marker in text for marker in ("旁边", "身边", "一起", "舍友", "同学", "老师")):
        fields.add("people_present")
    if any(marker in text for marker in ("困", "累", "疼", "不舒服", "开心", "难过", "烦", "焦虑")):
        fields.add("physical_state")
    if any(marker in text for marker in ("拿着", "带着", "手里", "收着")):
        fields.add("current_possessions")
    return fields


async def _extract_uie_changes(
    text: str,
    fields: set[str],
    config: Mapping[str, Any],
    *,
    uie_extractor: Any,
) -> dict[str, list[dict[str, Any]]]:
    uie_config = config.get("uie")
    if not isinstance(uie_config, Mapping):
        return {}
    schema_map = uie_config.get("schema_by_field")
    if not isinstance(schema_map, Mapping):
        return {}
    schemas: list[str] = []
    for field in fields:
        for schema in schema_map.get(field, []):
            schema_text = str(schema).strip()
            if schema_text and schema_text not in schemas:
                schemas.append(schema_text)
    if not schemas:
        return {}

    try:
        extractor = uie_extractor
        if extractor is None:
            from core.services.data_ops.uie_extractor import get_uie_extractor

            extractor = await asyncio.to_thread(get_uie_extractor)
        raw_result = await asyncio.to_thread(extractor.extract, text, schemas)
    except Exception as exc:  # noqa: BLE001
        logger.debug("叶 runtime state UIE 提取失败，保留规则结果: %s", exc)
        return {}

    threshold = float(uie_config.get("min_probability", 0.5) or 0.5)
    changes: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        accepted = []
        for schema in schema_map.get(field, []):
            for item in raw_result.get(schema, []) if isinstance(raw_result, Mapping) else []:
                if not isinstance(item, Mapping):
                    continue
                value = _uie_item_value(text, item)
                probability = float(item.get("probability") or 0.0)
                if value and probability >= threshold:
                    accepted.append(
                        {
                            "value": value,
                            "confidence": probability,
                            "start": item.get("start"),
                            "end": item.get("end"),
                        }
                    )
        if accepted:
            best = _merge_uie_spans(text, field, accepted)
            _add_candidate(
                changes,
                field,
                best["value"],
                "assistant_uie",
                best["confidence"],
            )
    return changes


def _uie_item_value(text: str, item: Mapping[str, Any]) -> str:
    decoded = re.sub(
        r"(?<=[\u3400-\u9fffA-Za-z0-9])\s+(?=[\u3400-\u9fffA-Za-z0-9])",
        "",
        _clean_text(item.get("text")),
    )
    try:
        start = int(item.get("start"))
        end = int(item.get("end"))
    except (TypeError, ValueError):
        return decoded
    if start < 0 or end < start or end >= len(text):
        return decoded
    source = text[start : end + 1].strip(" ，。！？?,")

    def compare(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    return source if source and compare(source) == compare(decoded) else decoded


def _merge_uie_spans(
    text: str, field: str, accepted: list[dict[str, Any]]
) -> dict[str, Any]:
    best = max(accepted, key=lambda item: float(item["confidence"]))
    if field not in {"clothing", "current_possessions"}:
        return best
    positioned = []
    for item in accepted:
        try:
            start = int(item.get("start"))
            end = int(item.get("end"))
        except (TypeError, ValueError):
            continue
        if 0 <= start <= end < len(text):
            positioned.append((start, end, item))
    positioned.sort(key=lambda value: (value[0], value[1]))
    if len(positioned) < 2:
        return best
    selected = [positioned[0]]
    for candidate in positioned[1:]:
        gap = candidate[0] - selected[-1][1] - 1
        if 0 <= gap <= 3:
            selected.append(candidate)
    if len(selected) < 2:
        return best
    start = selected[0][0]
    end = selected[-1][1]
    return {
        "value": text[start : end + 1].strip(" ，。！？?,"),
        "confidence": min(float(item[2]["confidence"]) for item in selected),
    }
