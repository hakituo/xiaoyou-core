"""检查 thinking 类记忆的蒸馏质量。

扫描 companion_data 下所有 thinking 子目录的 weighted 文件，重点检查：
1. content 字段是否为空（已知 bug：thinking 消息 content 可能被清空，原文落到 readable_summary）
2. 已蒸馏样本的 summary / keywords 质量
3. 统计空 content 但 readable_summary 有内容的情况

只读，不写任何文件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(r"d:\AI\xiaoyou-core\companion_data")


def collect_thinking_files() -> List[Path]:
    files: List[Path] = []
    for thinking_dir in ROOT.rglob("memories/weighted/thinking"):
        if not thinking_dir.is_dir():
            continue
        files.extend(thinking_dir.glob("*.json"))
    return files


def load_memories(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[LOAD-ERR] {path}: {exc}")
        return {}


def to_bool(val: Any) -> bool:
    """weighted_memories 文件里布尔值经常存成字符串 'True'/'False'，统一转。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def to_str(val: Any) -> str:
    """文件里 None 也常存成字符串 'None'，转回空串。"""
    if val is None:
        return ""
    if isinstance(val, str):
        if val.strip().lower() in ("none", "null"):
            return ""
        return val
    return str(val)


def truncate(text: str, n: int = 200) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "..."


def main() -> None:
    files = collect_thinking_files()
    print(f"=== 共发现 {len(files)} 个 thinking 类 weighted 文件 ===\n")

    total_all = 0
    distilled_total = 0
    empty_content_total = 0
    empty_but_readable_total = 0  # content 空，但 readable_summary 有内容

    for path in files:
        data = load_memories(path)
        if not isinstance(data, dict):
            continue
        memories = data.get("weighted_memories") or data.get("memories") or []
        if not isinstance(memories, list):
            if isinstance(memories, dict):
                memories = list(memories.values())
            else:
                continue

        items = [m for m in memories if isinstance(m, dict)]
        if not items:
            continue

        # 统计各种情况
        has_content = [m for m in items if to_str(m.get("content"))]
        empty_content = [m for m in items if not to_str(m.get("content"))]
        empty_but_readable = [
            m for m in empty_content
            if to_str(m.get("readable_summary")) or to_str(m.get("readable_title"))
        ]
        distilled = [m for m in items if to_bool(m.get("is_distilled"))]

        total_all += len(items)
        distilled_total += len(distilled)
        empty_content_total += len(empty_content)
        empty_but_readable_total += len(empty_but_readable)

        rel_path = path.relative_to(ROOT)
        print(f"--- {rel_path} ---")
        print(
            f"  总数: {len(items)} | 有 content: {len(has_content)} | "
            f"空 content: {len(empty_content)} | 空但有 readable: {len(empty_but_readable)} | "
            f"已蒸馏: {len(distilled)}"
        )

        # 情况 A：content 空但 readable_summary 有内容 —— 展示前 3 条
        if empty_but_readable:
            print(f"\n  [A] content 空、readable_summary 有内容（前 3 条）:")
            for i, m in enumerate(empty_but_readable[:3]):
                rs = to_str(m.get("readable_summary"))
                mid = to_str(m.get("id", ""))
                distilled_flag = to_bool(m.get("is_distilled"))
                summary = to_str(m.get("summary"))
                print(f"    [{i+1}] id={mid[:8]}  is_distilled={distilled_flag}")
                print(f"        readable_summary ({len(rs)} 字): {truncate(rs, 200)}")
                if summary:
                    print(f"        summary 字段 ({len(summary)} 字): {truncate(summary, 200)}")
                print()

        # 情况 B：已蒸馏且有 content —— 展示前 5 条
        distilled_with_content = [m for m in distilled if to_str(m.get("content"))]
        if distilled_with_content:
            print(f"  [B] 已蒸馏且有 content（前 5 条）:")
            for i, m in enumerate(distilled_with_content[:5]):
                content = to_str(m.get("content", ""))
                summary = to_str(m.get("summary", ""))
                keywords = m.get("keywords", []) or []
                if isinstance(keywords, str):
                    keywords = [keywords]
                meta = m.get("metadata", {}) or {}
                source = to_str(m.get("source", "")) or to_str(meta.get("source", ""))
                mid = to_str(m.get("id", ""))

                print(f"    [{i+1}] id={mid[:8]}  source={source}")
                print(f"        原文 ({len(content)} 字): {truncate(content, 180)}")
                print(f"        梗概 ({len(summary)} 字): {truncate(summary, 200)}")
                print(f"        关键词: {keywords}")
                if summary and content:
                    ratio = (1 - len(summary) / max(len(content), 1)) * 100
                    print(f"        压缩率: {ratio:.1f}%")
                print()

        # 情况 C：已蒸馏但 content 空 —— 展示前 3 条，看 summary 字段
        distilled_empty_content = [m for m in distilled if not to_str(m.get("content"))]
        if distilled_empty_content:
            print(f"  [C] 已蒸馏但 content 空（前 3 条）:")
            for i, m in enumerate(distilled_empty_content[:3]):
                rs = to_str(m.get("readable_summary"))
                summary = to_str(m.get("summary"))
                keywords = m.get("keywords", []) or []
                if isinstance(keywords, str):
                    keywords = [keywords]
                mid = to_str(m.get("id", ""))
                print(f"    [{i+1}] id={mid[:8]}")
                print(f"        readable_summary ({len(rs)} 字): {truncate(rs, 150)}")
                print(f"        summary ({len(summary)} 字): {truncate(summary, 200)}")
                print(f"        关键词: {keywords}")
                print()

        print()

    print("=" * 70)
    print(
        f"汇总：总记忆 {total_all} | 已蒸馏 {distilled_total} | "
        f"空 content {empty_content_total} | 空但有 readable {empty_but_readable_total}"
    )


if __name__ == "__main__":
    main()
