"""重新生成指定日期的日记摘要 (diary_summary.json)

用法:
    python scripts/regenerate_diary_summary.py              # 默认重新生成昨天
    python scripts/regenerate_diary_summary.py 2026-06-17   # 指定日期
"""
import asyncio
import os
import sys
import json

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from datetime import datetime, timedelta  # noqa: E402
from core.utils.time_utils import get_diary_target_date  # noqa: E402


async def main(date_str: str) -> int:
    from core.services.journal.service import get_journal_service
    from core.services.journal.storage import JournalStorage

    service = get_journal_service()
    storage: JournalStorage = service.storage

    # 清除摘要缓存，确保真正重新生成
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for scope in ("aveline", "ling", "user", "any"):
        cache_key = f"{dt.strftime('%Y-%m-%d')}:{scope}"
        storage._summary_cache.pop(cache_key, None)

    print(f"=== 重新生成日记摘要: {date_str} ===")

    # 先看看当天有多少日记条目
    entries = await storage.get_entries(dt)
    print(f"当天日记条目数: {len(entries)}")
    for entry in entries:
        print(f"  [{entry.time_str}] ({entry.type}) {entry.content[:60]}...")

    # 清理旧的 daily_summary 类型日记条目：
    # 历史 bug 曾把Ling的每日总结写成 source=aveline 落进 aveline 目录，
    # 或把Ling的条目跨 persona 去重掉。若不清除，force 重生成后 _append_daily_summary_diary_entry
    # 的按 persona 去重会命中旧条目而跳过写入，导致内容仍停留在旧版本。
    from core.utils.data_paths import get_aveline_data_dir, get_ling_data_dir, get_user_data_dir

    cleaned = 0
    for scope_dir in (get_aveline_data_dir(), get_ling_data_dir(), get_user_data_dir()):
        diary_dir = (
            scope_dir / "daily" / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d") / "diary"
        )
        if not diary_dir.exists():
            continue
        for entry_file in diary_dir.glob("entry_*.json"):
            try:
                payload = json.loads(entry_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("type") or "") == "daily_summary":
                entry_file.unlink(missing_ok=True)
                cleaned += 1
    if cleaned:
        print(f"已清理 {cleaned} 条旧的 daily_summary 日记条目")
        # 清缓存，避免 get_entries 返回旧内容
        for scope in ("aveline", "ling", "user", "any"):
            storage._summary_cache.pop(f"{dt.strftime('%Y-%m-%d')}:{scope}", None)

    # 强制重新生成 Aveline 日记
    print("\n=== Aveline 日记 ===")
    aveline_summary = await service.generate_daily_summary(date_str, force=True, persona="aveline")
    print(f"日期: {aveline_summary.date}")
    print(f"摘要: {aveline_summary.summary[:200]}...")
    print(f"明日基调: {aveline_summary.tomorrow_tone}")
    stats = aveline_summary.stats or {}
    print(f"chat_turn_count: {stats.get('chat_turn_count', 'N/A')}")

    # 强制重新生成 Ling日记
    print("\n=== Ling日记 ===")
    ling_summary = await service.generate_daily_summary(date_str, force=True, persona="ling")
    # 8/14 曾出现Ling与 Aveline 摘要逐字相同（疑似 LLM 重复输出），命中时换温度重试
    aveline_text = str(getattr(aveline_summary, "summary", "") or "").strip()
    ling_text = str(getattr(ling_summary, "summary", "") or "").strip()
    if ling_text and ling_text == aveline_text:
        print("警告: Ling与 Aveline 摘要逐字相同，换温度重试Ling...")
        ling_summary = await service.generate_daily_summary(
            date_str, force=True, persona="ling", temperature=0.8
        )
    print(f"日期: {ling_summary.date}")
    print(f"摘要: {ling_summary.summary[:200]}...")
    print(f"明日基调: {ling_summary.tomorrow_tone}")
    stats = ling_summary.stats or {}
    print(f"chat_turn_count: {stats.get('chat_turn_count', 'N/A')}")

    # 验证文件是否写入
    for scope in ("aveline", "ling"):
        filepath = storage.get_daily_dir(dt, scope=scope) / "diary_summary.json"
        if filepath.exists():
            print(f"\n[{scope}] 文件已写入: {filepath}")
            data = json.loads(filepath.read_text(encoding="utf-8"))
            gen_time = datetime.fromtimestamp(data.get("generated_at", 0))
            print(f"  generated_at 对应时间: {gen_time.strftime('%Y-%m-%d %H:%M:%S')}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # 默认昨天
        target = (get_diary_target_date() - timedelta(days=1)).strftime("%Y-%m-%d")
    raise SystemExit(asyncio.run(main(target)))
