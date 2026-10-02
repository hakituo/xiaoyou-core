"""清洗聊天历史记录中的 VOICE 标签美元符号污染。

背景：
    Active Care 主动关怀发出去的回复里，LLM 偶尔会输出 `$[VOICE]$` 这种
    被美元符号包裹的标签（疑似 markdown 数学公式定界符被误用）。现有标签
    剥离正则只认 `[VOICE]` / `［VOICE］`，不匹配带 `$` 的变体，导致：
      1. 标签原样留在文本里发出去，TTS 把 `$` 念成"美元"；
      2. 带标签的文本被写进 chat_history，下一次 Active Care 决策时把这条
         脏历史塞进 prompt，LLM 看到这种格式跟着学，形成上下文污染循环。

本脚本：
    扫描 companion_data 下所有 chat_history 目录的 .jsonl 文件，把每条
    记录 content 字段里 `$[VOICE...]$` 形式的污染，去掉两侧美元符号，还原
    成正常的 `[VOICE...]` 标签（保留语音消息语义）。不动裸 `[VOICE]` 标签
    （那是正常的语音消息记录），然后原子写回。

用法：
    # 先预览（不写文件）
    python scripts/maintenance/clean_voice_tag_pollution.py --dry-run
    # 实际执行
    python scripts/maintenance/clean_voice_tag_pollution.py

兼容 Windows / Linux。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COMPANION_DATA_DIR = PROJECT_ROOT / "companion_data"

from core.services.active_care.postprocess.tag_sanitizer import TagSanitizer  # noqa: E402


def clean_content(content: str) -> str:
    """清理 content 中的标签污染，返回清理后的文本。

    复用运行时的 TagSanitizer，保证一次性清洗与线上后处理行为完全一致
    （单一真相源），避免出现"清洗脚本认得的形态"和"线上清理的形态"不一致。
    """
    if not content:
        return content
    return TagSanitizer.sanitize(content)


def process_file(file_path: Path, dry_run: bool) -> tuple[int, int]:
    """处理单个 jsonl 文件，返回 (总行数, 被清理的行数)。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except Exception as e:
        print(f"  [跳过] 读取失败 {file_path}: {e}", file=sys.stderr)
        return (0, 0)

    total = len(raw_lines)
    changed = 0
    new_lines: list[str] = []

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            new_lines.append(raw)
            continue
        try:
            payload = json.loads(stripped)
        except Exception:
            # 非 JSON 行原样保留
            new_lines.append(raw)
            continue

        content = payload.get("content")
        if not isinstance(content, str):
            new_lines.append(raw)
            continue

        cleaned = clean_content(content)
        if cleaned != content:
            changed += 1
            payload["content"] = cleaned
            new_lines.append(json.dumps(payload, ensure_ascii=False) + "\n")
        else:
            new_lines.append(raw)

    if changed == 0:
        return (total, 0)

    if not dry_run:
        # 原子写回：先写临时文件再替换
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                f.writelines(new_lines)
            tmp_path.replace(file_path)
        except Exception as e:
            print(f"  [错误] 写回失败 {file_path}: {e}", file=sys.stderr)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return (total, 0)

    return (total, changed)


def iter_chat_history_files() -> list[Path]:
    """枚举需要清洗的 .jsonl 文件。

    两类来源都要覆盖，否则污染闭环切不干净：
      1. chat_history/**/*.jsonl            —— 会话历史（会被当成最近对话塞进 prompt）
      2. daily/*/events/active_care_actions.jsonl —— 主动关怀发送记录
         （之前漏了这一类，导致 chat_history 清干净了、发送记录里仍留着脏数据）
    """
    if not COMPANION_DATA_DIR.exists():
        return []
    results: list[Path] = []
    for chat_root in COMPANION_DATA_DIR.rglob("chat_history"):
        if not chat_root.is_dir():
            continue
        results.extend(chat_root.rglob("*.jsonl"))

    seen = {p.resolve() for p in results}
    for events_root in COMPANION_DATA_DIR.rglob("events"):
        if not events_root.is_dir():
            continue
        for candidate in events_root.glob("active_care_actions.jsonl"):
            if candidate.resolve() not in seen:
                seen.add(candidate.resolve())
                results.append(candidate)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗聊天历史中的 VOICE 标签污染")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览将清理哪些文件/条数，不写回磁盘",
    )
    args = parser.parse_args()

    if not COMPANION_DATA_DIR.exists():
        print(f"未找到数据目录: {COMPANION_DATA_DIR}", file=sys.stderr)
        return 1

    files = iter_chat_history_files()
    if not files:
        print("未找到任何 chat_history .jsonl 文件，无需清理。")
        return 0

    print(f"扫描到 {len(files)} 个 jsonl 文件")
    if args.dry_run:
        print("[DRY-RUN 模式] 不会写回文件\n")
    else:
        print("[执行模式] 将原子写回被清理的文件\n")

    total_files = 0
    total_events = 0
    total_changed = 0
    affected_files: list[tuple[Path, int, int]] = []

    for fp in files:
        total_files += 1
        total, changed = process_file(fp, dry_run=args.dry_run)
        total_events += total
        if changed > 0:
            total_changed += changed
            affected_files.append((fp, total, changed))

    print("=" * 60)
    print(f"扫描文件数: {total_files}")
    print(f"扫描事件数: {total_events}")
    print(f"被污染事件数: {total_changed}")
    print(f"受影响文件数: {len(affected_files)}")
    if affected_files:
        print("\n受影响文件明细 (文件 / 总行 / 污染行):")
        for fp, total, changed in affected_files:
            try:
                rel = fp.relative_to(PROJECT_ROOT)
            except ValueError:
                rel = fp
            print(f"  {rel}  {total} / {changed}")

    if args.dry_run and total_changed > 0:
        print("\n这是预览。去掉 --dry-run 实际执行清理。")
    elif not args.dry_run and total_changed > 0:
        print("\n清理完成。")
    else:
        print("\n未发现 VOICE 标签污染，数据已是干净的。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
