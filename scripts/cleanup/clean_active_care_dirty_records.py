"""清理 Active Care 生成的脏记录。

默认仅预览；传入 ``--apply`` 后才会写回，并在写入前逐文件备份。
内置规则覆盖错误相对节日日期、已确认的抽象到期提醒、错误睡眠判断和
未知角色误挂消息。也可通过 ``--pattern`` 添加生成侧文本正则。
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.atomic_io import safe_json_dump, safe_write_text  # noqa: E402


_PATH_DATE_RE = re.compile(r"(?:^|[\\/])(20\d{2})[\\/](\d{1,2})[\\/](\d{1,2})(?:[\\/]|$)")
_CORRECTION_MARKERS = ("不是", "不对", "记错", "纠正", "老是说", "还早", "并非")
_KNOWN_VAGUE_OUTPUTS = {
    "哼，就你话多。",
    "哼，就你话多。[VOICE]",
    "喂，起来了。",
    "喂，起来了。[VOICE]",
    "嗯，你睡吧，我继续学习去了。",
    "你正在睡觉呢，我不多打扰了。继续学习中，有事叫我。晚安",
}


@dataclass
class Finding:
    """单条清理命中信息。"""

    path: Path
    action: str
    reason: str
    snippet: str


def _qixi_date(year: int) -> date | None:
    """计算指定年份七夕的公历日期。"""
    try:
        from lunar_python import Lunar

        solar = Lunar.fromYmd(year, 7, 7).getSolar()
        return date(solar.getYear(), solar.getMonth(), solar.getDay())
    except Exception:
        return None


def _record_date(record: dict[str, Any], path: Path) -> date | None:
    """按 timestamp、created_at、文件路径的顺序解析记录日期。"""
    timestamp = record.get("timestamp")
    if isinstance(timestamp, (int, float)):
        try:
            return datetime.fromtimestamp(float(timestamp)).date()
        except (OSError, OverflowError, ValueError):
            pass

    for key in ("created_at", "date"):
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass

    match = _PATH_DATE_RE.search(str(path))
    if match:
        try:
            return date(*(int(value) for value in match.groups()))
        except ValueError:
            return None
    return None


def _strip_thought_prefix(text: str) -> str:
    return re.sub(r"^（心想：[^）]+）\s*", "", str(text or "").strip()).strip()


def _sanitize_invalid_qixi_sentences(text: str, reference_date: date | None) -> str:
    """从长篇日记中移除错误节日断言所在句，保留其余内容。"""
    parts = re.split(r"(?<=[。！？!?])", str(text or ""))
    kept = []
    for part in parts:
        is_correction = any(marker in part for marker in _CORRECTION_MARKERS)
        if not is_correction and _invalid_qixi_claim(part, reference_date):
            continue
        kept.append(part)
    return "".join(kept).strip()


def _invalid_qixi_claim(text: str, reference_date: date | None) -> bool:
    """判断文本中的相对七夕断言是否与权威农历日期冲突。"""
    compact = re.sub(r"\s+", "", str(text or ""))
    if "七夕" not in compact:
        return False
    if reference_date is None:
        # 没有日期的持久状态不应保留会过期的相对节日断言。
        return bool(re.search(r"(?:今天|明天).{0,10}七夕|七夕.{0,10}(?:今天|明天)", compact))

    festival_date = _qixi_date(reference_date.year)
    if festival_date is None:
        return False
    # “明天是七夕前一天”并不是“明天是七夕”，不能按错误断言清理。
    if re.search(r"明天.{0,12}七夕前|七夕前.{0,12}明天", compact):
        return False
    says_tomorrow = bool(re.search(r"明天.{0,10}七夕|七夕.{0,10}明天", compact))
    says_today = bool(re.search(r"今天.{0,10}七夕|七夕.{0,10}今天|七夕也", compact))
    return (says_tomorrow and reference_date + timedelta(days=1) != festival_date) or (
        says_today and reference_date != festival_date
    )


def _is_generated_record(record: dict[str, Any]) -> bool:
    role = str(record.get("role") or "").lower()
    source = str(record.get("source") or "").lower()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metadata_source = str(metadata.get("source") or "").lower()
    if role == "user" or source == "user":
        return False
    return role in {"assistant", "system"} or source == "active_care" or metadata_source == "active_care"


def _dirty_reason(
    record: dict[str, Any],
    path: Path,
    custom_patterns: Iterable[re.Pattern[str]],
) -> str:
    """返回生成记录的脏数据原因；未命中返回空字符串。"""
    if not _is_generated_record(record):
        return ""
    content = str(record.get("content") or record.get("summary") or "").strip()
    if not content:
        return ""
    body = _strip_thought_prefix(content)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    thought = str(record.get("thought") or metadata.get("thought") or "")
    if body in _KNOWN_VAGUE_OUTPUTS:
        return "已确认的抽象或错误睡眠主动消息"
    if "activity_transition_busy_xiaolu" in f"{thought}\n{content}":
        return "未知角色消息误挂到当前 persona"
    # 对话中的纠正/复盘文本保留；日记 tomorrow_tone 会在字段级单独处理。
    is_correction = any(marker in body for marker in _CORRECTION_MARKERS)
    if not is_correction and _invalid_qixi_claim(body, _record_date(record, path)):
        return "相对七夕日期与权威农历日期冲突"
    for pattern in custom_patterns:
        if pattern.search(body):
            return f"命中自定义正则: {pattern.pattern}"
    return ""


def _clean_node(
    node: Any,
    path: Path,
    findings: list[Finding],
    custom_patterns: Iterable[re.Pattern[str]],
) -> tuple[Any, bool]:
    """递归清理 JSON 节点，返回（新节点，是否变化）。"""
    changed = False
    if isinstance(node, list):
        cleaned_items = []
        for item in node:
            if isinstance(item, dict):
                reason = _dirty_reason(item, path, custom_patterns)
                if reason:
                    findings.append(
                        Finding(path, "删除记录", reason, str(item.get("content") or "")[:160])
                    )
                    changed = True
                    continue
            cleaned, item_changed = _clean_node(item, path, findings, custom_patterns)
            cleaned_items.append(cleaned)
            changed = changed or item_changed
        return cleaned_items, changed

    if not isinstance(node, dict):
        return node, False

    result = copy.deepcopy(node)
    reference_date = _record_date(result, path)

    # 日记正文保留有用叙事，只删错误日期断言所在句。
    is_diary_data = (
        "diary" in {part.lower() for part in path.parts}
        or "diary" in path.name.lower()
        or str(result.get("category") or "").lower() == "diary"
    )
    if is_diary_data:
        for field in ("content", "summary", "readable_summary", "readable_title"):
            value = result.get(field)
            if not isinstance(value, str):
                continue
            sanitized = _sanitize_invalid_qixi_sentences(value, reference_date)
            if sanitized != value:
                findings.append(Finding(path, "清理字段", f"{field} 含错误相对节日日期", value[:160]))
                result[field] = sanitized
                changed = True

    # tomorrow_tone 是面向次日的策略字段，一旦含错误日期便整字段清空，
    # 避免残余叙事继续被 Active Care 当成当天事实。
    tone = result.get("tomorrow_tone")
    if isinstance(tone, str) and _invalid_qixi_claim(tone, _record_date(result, path)):
        findings.append(Finding(path, "清空字段", "tomorrow_tone 含错误相对节日日期", tone[:160]))
        result["tomorrow_tone"] = ""
        changed = True

    recent = result.get("recent_sent_contents")
    if isinstance(recent, list):
        kept = []
        for text in recent:
            body = _strip_thought_prefix(str(text or ""))
            if body in _KNOWN_VAGUE_OUTPUTS or _invalid_qixi_claim(body, None):
                findings.append(Finding(path, "删除状态项", "持久状态含过期或抽象主动消息", body[:160]))
                changed = True
            else:
                kept.append(text)
        result["recent_sent_contents"] = kept

    last_sent_content = result.get("last_sent_content")
    if isinstance(last_sent_content, str):
        body = _strip_thought_prefix(last_sent_content)
        if body in _KNOWN_VAGUE_OUTPUTS or _invalid_qixi_claim(body, None):
            findings.append(Finding(path, "清空字段", "last_sent_content 含脏主动消息", body[:160]))
            result["last_sent_content"] = ""
            changed = True

    today_events = result.get("today_sent_events")
    if isinstance(today_events, list):
        kept_events = []
        for event in today_events:
            body = _strip_thought_prefix(str(event.get("content") or "")) if isinstance(event, dict) else ""
            if body in _KNOWN_VAGUE_OUTPUTS or _invalid_qixi_claim(body, _record_date(event, path)):
                findings.append(Finding(path, "删除状态事件", "today_sent_events 含脏主动消息", body[:160]))
                changed = True
            else:
                kept_events.append(event)
        result["today_sent_events"] = kept_events

    for key, value in list(result.items()):
        if key in {
            "tomorrow_tone",
            "recent_sent_contents",
            "last_sent_content",
            "today_sent_events",
        }:
            continue
        cleaned, item_changed = _clean_node(value, path, findings, custom_patterns)
        result[key] = cleaned
        changed = changed or item_changed
    return result, changed


def _load_and_clean(
    path: Path,
    findings: list[Finding],
    custom_patterns: Iterable[re.Pattern[str]],
) -> tuple[Any, bool, bool]:
    """读取并清理文件，返回（内容、是否变化、是否 JSONL）。"""
    if path.suffix.lower() == ".jsonl":
        records = []
        changed = False
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                findings.append(Finding(path, "跳过", f"第 {line_number} 行不是合法 JSON", line[:160]))
                records.append(line)
                continue
            reason = _dirty_reason(record, path, custom_patterns) if isinstance(record, dict) else ""
            if reason:
                findings.append(Finding(path, "删除 JSONL 行", reason, str(record.get("content") or "")[:160]))
                changed = True
                continue
            records.append(record)
        return records, changed, True

    data = json.loads(path.read_text(encoding="utf-8"))
    cleaned, changed = _clean_node(data, path, findings, custom_patterns)
    return cleaned, changed, False


def _write_cleaned(path: Path, content: Any, is_jsonl: bool) -> None:
    if is_jsonl:
        lines = [item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for item in content]
        safe_write_text("\n".join(lines) + ("\n" if lines else ""), path)
    else:
        safe_json_dump(content, path)


def _cancel_legacy_auto_plan_reminders(
    path: Path,
    findings: list[Finding],
) -> tuple[Any, bool]:
    """把旧版 AI 自动计划遗留的待发硬提醒标记为完成。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return data, False
    result = copy.deepcopy(data)
    changed = False
    for item in result:
        if not isinstance(item, dict) or str(item.get("status") or "") != "pending":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if (
            str(metadata.get("source") or "").strip().lower() == "daily_task"
            and str(metadata.get("delivery_mode") or "").strip().lower() != "hard"
        ):
            item["status"] = "completed"
            item["cleanup_reason"] = "legacy_auto_plan_reminder"
            findings.append(
                Finding(
                    path,
                    "取消待发提醒",
                    "旧版 AI 自动计划不再作为硬提醒发送",
                    str(item.get("message") or "")[:160],
                )
            )
            changed = True
    return result, changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="预览或清理 Active Care 生成的脏记录")
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT / "companion_data" / "aveline_data",
        help="要扫描的数据根目录",
    )
    parser.add_argument("--apply", action="store_true", help="实际写回；默认只预览")
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="额外删除生成侧记录的文本正则，可重复传入",
    )
    parser.add_argument("--backup-dir", type=Path, help="备份目录；默认放在 companion_data/backups 下")
    parser.add_argument(
        "--cancel-legacy-auto-plan-reminders",
        action="store_true",
        help="同时取消 user_data/reminders.json 中旧版自动计划的待发硬提醒",
    )
    parser.add_argument(
        "--reminders-file",
        type=Path,
        default=PROJECT_ROOT / "companion_data" / "user_data" / "reminders.json",
        help="Workspace 提醒文件路径",
    )
    parser.add_argument(
        "--skip-record-scan",
        action="store_true",
        help="不扫描角色记录，只处理显式指定的提醒清理任务",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"数据根目录不存在: {root}")
    patterns = [re.compile(value) for value in args.pattern]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = (args.backup_dir or root.parent / "backups" / "dirty_record_cleanup" / timestamp).resolve()

    findings: list[Finding] = []
    changed_files: list[tuple[Path, Any, bool, Path]] = []
    if not args.skip_record_scan:
        for path in sorted((*root.rglob("*.json"), *root.rglob("*.jsonl"))):
            try:
                cleaned, changed, is_jsonl = _load_and_clean(path, findings, patterns)
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(Finding(path, "跳过", f"读取失败: {exc}", ""))
                continue
            if changed:
                changed_files.append((path, cleaned, is_jsonl, path.relative_to(root)))

    if args.cancel_legacy_auto_plan_reminders:
        reminders_path = args.reminders_file.resolve()
        if reminders_path.is_file():
            try:
                cleaned, changed = _cancel_legacy_auto_plan_reminders(
                    reminders_path, findings
                )
                if changed:
                    changed_files.append(
                        (reminders_path, cleaned, False, Path("user_data/reminders.json"))
                    )
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(Finding(reminders_path, "跳过", f"读取失败: {exc}", ""))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 命中 {len(findings)} 项，涉及 {len(changed_files)} 个文件")
    for item in findings:
        try:
            relative = item.path.relative_to(root)
        except ValueError:
            relative = Path("user_data") / item.path.name
        print(f"- {item.action} | {relative} | {item.reason} | {item.snippet}")

    if args.apply and changed_files:
        for path, cleaned, is_jsonl, backup_relative in changed_files:
            backup_path = backup_dir / backup_relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            _write_cleaned(path, cleaned, is_jsonl)
        print(f"已写回 {len(changed_files)} 个文件；原文件备份：{backup_dir}")
    elif not args.apply:
        print("这是预览，没有修改文件。确认后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
