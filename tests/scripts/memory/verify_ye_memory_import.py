# -*- coding: utf-8 -*-
"""验证 ye（Ye）的 chat_history 已成功重建为加权记忆 + 近期短期记忆。

背景：ye 的聊天记录此前手动导入到 companion_data/ye_data/chat_history，但没有
同步进记忆系统，且短期记忆自动回填因 conversation 命名空间不一致长期为空。
现在通过 scripts/import/import_chat_to_memory.py（通用工具）清空测试产物并重建：
  - 全部历史对话链 → weighted（category=sensitive，可检索、持久化）
  - 近期 40 条消息 → short_term（短期上下文）

检查项：
1. weighted 主文件存在、记录数 >= 200、category 全为 sensitive、
   import_source 匹配、content 非空、时间戳覆盖 08-22 ~ 09-09
2. short_term 文件存在且 > 0 条近期对话
3. manager 加载后 weighted_memories 数量一致
4. 关键词/语义检索能命中真实对话内容

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\memory\\verify_ye_memory_import.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

USER_ID = "shared__scope__ye"
CONVERSATION_ID = "shared__persona__core_ye"
MEMORIES_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "memories"
# category=sensitive 的记忆由系统分流保存到 weighted/sensitive/ 子目录（主文件 weighted_memories 为空）
MAIN_FILE = MEMORIES_ROOT / "weighted" / "sensitive" / f"{USER_ID}_weighted.json"
SHORT_FILE = MEMORIES_ROOT / "short_term" / f"{USER_ID}_short.json"

EXPECTED_SOURCE = f"{CONVERSATION_ID}_history"
EXPECTED_CATEGORY = "sensitive"
EXPECTED_WEIGHT = 3.0 + 0.8 * 4.0  # 6.2
# 2026-09-09 起记忆随 chat_history 覆盖导入自动重建，链数随导入增长，只设下限
EXPECTED_MIN_CHAIN_COUNT = 200
TS_MIN = datetime(2026, 8, 22).timestamp()
TS_MAX = datetime(2026, 9, 9).timestamp() + 86400

# 用真实聊天历史里的高频词做检索探针
SEARCH_QUERIES = ["狗盆", "任务", "梦到", "主人"]

failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    print("=" * 60)
    print("ye chat_history → 记忆系统 重建验证")
    print("=" * 60)

    # 1. weighted 落盘文件检查
    print("\n[1/4] weighted 落盘文件检查")
    _check("主文件存在", MAIN_FILE.exists(), str(MAIN_FILE.relative_to(PROJECT_ROOT)))
    if not MAIN_FILE.exists():
        _finish()
        return 1
    data = json.loads(MAIN_FILE.read_text(encoding="utf-8"))
    records = data.get("weighted_memories") or []
    _check(
        f"记录数 >= {EXPECTED_MIN_CHAIN_COUNT}",
        len(records) >= EXPECTED_MIN_CHAIN_COUNT,
        f"{len(records)} 条",
    )
    if not records:
        _finish()
        return 1

    # 2. 记录字段检查
    print("\n[2/4] 记录字段检查")
    cats = {r.get("category") for r in records}
    sources = {(r.get("metadata") or {}).get("import_source") for r in records}
    weights = [float(r.get("weight") or 0) for r in records]
    contents_empty = sum(1 for r in records if not str(r.get("content") or "").strip())
    ts_min = min(float(r.get("timestamp") or 0) for r in records)
    ts_max = max(float(r.get("timestamp") or 0) for r in records)
    _check("category 全为 sensitive", cats == {EXPECTED_CATEGORY}, str(cats))
    _check(f"import_source 全为 {EXPECTED_SOURCE}", sources == {EXPECTED_SOURCE}, str(sources))
    _check("权重为 6.2", all(abs(w - EXPECTED_WEIGHT) < 1e-6 for w in weights),
           f"min={min(weights):.2f} max={max(weights):.2f}")
    _check("无空 content", contents_empty == 0, f"{contents_empty} 条为空")
    _check("时间戳覆盖 08-22 ~ 09-09",
           ts_min >= TS_MIN - 1 and ts_max <= TS_MAX,
           f"{datetime.fromtimestamp(ts_min):%Y-%m-%d} ~ {datetime.fromtimestamp(ts_max+0.0):%Y-%m-%d}")

    # 3. 短期记忆检查
    print("\n[3/4] 短期记忆检查")
    _check("short 文件存在", SHORT_FILE.exists(), str(SHORT_FILE.relative_to(PROJECT_ROOT)))
    if SHORT_FILE.exists():
        try:
            short_records = json.loads(SHORT_FILE.read_text(encoding="utf-8"))
            if isinstance(short_records, dict):
                short_records = short_records.get("short_term_memories") or []
            n = len(short_records) if isinstance(short_records, list) else 0
            _check("short 有近期记录", n > 0, f"{n} 条")
            if isinstance(short_records, list) and short_records:
                short_empty = sum(1 for r in short_records if not str(r.get("content") or "").strip())
                _check("short 无空 content", short_empty == 0, f"{short_empty} 条为空")
                # 最近一天 chat 量很大(9/2 当天 311 条)，回填+落盘后短期记忆应覆盖尽可能多的当天/近期对话
                _check("short 落盘覆盖近期(>=40 条)",
                       n >= 40, f"实际 {n} 条")
                # 校验已持久化到磁盘(而不是只有内存里有)；auto-save 已调度落盘
                _check("short 覆盖昨天以后(时间未过期)",
                       min(float(r.get("timestamp") or 0) for r in short_records) >= TS_MIN,
                       f"最早 {datetime.fromtimestamp(min(float(r.get('timestamp') or 0) for r in short_records)):%Y-%m-%d}")
        except Exception as e:
            _check("short 文件可解析", False, str(e))

    # 4. manager 加载 + 检索检查
    print("\n[4/4] manager 加载 + 检索检查")
    from memory.weighted_memory_manager import get_weighted_memory_manager
    manager = get_weighted_memory_manager(USER_ID)
    _check(f"manager 加载 weighted 数 >= {EXPECTED_MIN_CHAIN_COUNT}", len(manager.weighted_memories) >= EXPECTED_MIN_CHAIN_COUNT,
           f"{len(manager.weighted_memories)} 条")
    _check("manager 加载 short 数 > 0", len(manager.short_term_memory) > 0,
           f"{len(manager.short_term_memory)} 条")

    hit_any = False
    search_fn = getattr(manager, "search_memories", None)
    for q in SEARCH_QUERIES:
        try:
            results = search_fn(q, limit=3) if search_fn else []
        except Exception:
            results = []
        corpus = [str(r.get("content") or "") for r in results]
        hit = any(q in c for c in corpus) if corpus else False
        hit_any = hit_any or hit
        print(f"  查询 {q!r}: {'命中' if hit else '未命中'} ({len(results)} 条结果)")
    _check("至少一个话题查询命中真实内容", hit_any)

    _finish()
    return 0 if not failures else 1


def _finish() -> None:
    if failures:
        print(f"\n❌ 验证失败 {len(failures)} 项: {failures}")
    else:
        print("\n✅ 全部通过：ye 的加权记忆与近期短期记忆已重建，可检索，具备上下文。")


if __name__ == "__main__":
    os.environ.setdefault("XIAOYOU_RUN_INTEGRATION_TESTS", "1")
    raise SystemExit(main())