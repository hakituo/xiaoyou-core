# -*- coding: utf-8 -*-
"""验证Chiba真实聊天记录已成功导入 weighted memory 且可检索。

背景：1.txt 的真实聊天记录通过 scripts/import/import_chiba_chat_to_memory.py
导入到 shared__scope__chiba 的加权记忆（category=sensitive，可检索、持久化，
不注入短期对话上下文）。

检查项：
1. 落盘文件存在且非空（weighted/sensitive/ 子目录）
2. 记录数 > 0，且 category 均为 sensitive、import_source 均为 chiba_chat_history
3. 权重符合预期（3.0 + 0.8*4.0 = 6.2）
4. 时间戳为真实聊天时间（非导入时间）
5. 通过 manager.get_weighted_memories 可检索到记录
6. 语义/关键词搜索能命中（如"奴隶卡"、"吐钱"等真实话题）

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\memory\\verify_chiba_weighted_import.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

USER_ID = "shared__scope__chiba"
WEIGHTED_ROOT = PROJECT_ROOT / "companion_data" / "chiba_data" / "memories" / "weighted"
MAIN_FILE = WEIGHTED_ROOT / f"{USER_ID}_weighted.json"
SENSITIVE_FILE = WEIGHTED_ROOT / "sensitive" / f"{USER_ID}_weighted.json"

EXPECTED_SOURCE = "chiba_chat_history"
EXPECTED_CATEGORY = "sensitive"
EXPECTED_WEIGHT = 3.0 + 0.8 * 4.0  # 6.2

# 用真实聊天里的高频话题做检索探针
SEARCH_QUERIES = ["奴隶卡", "上贡", "吐钱", "许可", "曝光"]

failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    print("=" * 60)
    print("Chiba真实聊天记录 → weighted memory 导入验证")
    print("=" * 60)

    # 1. 落盘文件检查
    print("\n[1/4] 落盘文件检查")
    _check("主文件存在", MAIN_FILE.exists(), str(MAIN_FILE.relative_to(PROJECT_ROOT)))
    _check("sensitive 分类文件存在", SENSITIVE_FILE.exists(),
           str(SENSITIVE_FILE.relative_to(PROJECT_ROOT)))
    if not SENSITIVE_FILE.exists():
        _check("sensitive 文件非空", False, "文件缺失，无法继续")
        _finish()
        return 1
    data = json.loads(SENSITIVE_FILE.read_text(encoding="utf-8"))
    records = data.get("weighted_memories") or []
    _check("sensitive 文件有记录", len(records) > 0, f"{len(records)} 条")
    if not records:
        _finish()
        return 1

    # 2. 记录字段检查
    print("\n[2/4] 记录字段检查")
    cats = {r.get("category") for r in records}
    sources = {(r.get("metadata") or {}).get("import_source") for r in records}
    weights = [float(r.get("weight") or 0) for r in records]
    ts_min = min(float(r.get("timestamp") or 0) for r in records)
    _check("category 全为 sensitive", cats == {EXPECTED_CATEGORY}, str(cats))
    _check("import_source 全为 chiba_chat_history", sources == {EXPECTED_SOURCE}, str(sources))
    _check("权重为 6.2", all(abs(w - EXPECTED_WEIGHT) < 1e-6 for w in weights),
           f"min={min(weights):.2f} max={max(weights):.2f}")
    _check("时间戳为真实聊天时间(2026)", ts_min >= 1780000000, f"min_ts={ts_min}")

    # 3. manager 检索检查
    print("\n[3/4] manager 检索检查")
    from memory.weighted_memory_manager import get_weighted_memory_manager
    manager = get_weighted_memory_manager(USER_ID)
    loaded = list(manager.weighted_memories.values())
    _check("manager 加载记录数 > 0", len(loaded) > 0, f"{len(loaded)} 条")
    if loaded:
        _check("manager 记录 category 均为 sensitive",
               all(r.get("category") == EXPECTED_CATEGORY for r in loaded))

    # 4. 搜索命中检查
    print("\n[4/4] 搜索命中检查")
    hit_any = False
    for q in SEARCH_QUERIES:
        try:
            results = manager.search_memories(q, limit=3) if hasattr(manager, "search_memories") else []
        except Exception:
            results = []
        hit = any(q in str(r.get("content") or "") for r in results) if results else False
        hit_any = hit_any or hit
        print(f"  查询 {q!r}: {'命中' if hit else '未命中'} ({len(results)} 条结果)")
    _check("至少一个话题查询命中真实内容", hit_any)

    _finish()
    return 0 if not failures else 1


def _finish() -> None:
    if failures:
        print(f"\n❌ 验证失败 {len(failures)} 项: {failures}")
    else:
        print("\n✅ 全部通过：Chiba真实聊天记录已进入 weighted memory 且可检索。")


if __name__ == "__main__":
    os.environ.setdefault("XIAOYOU_RUN_INTEGRATION_TESTS", "1")
    raise SystemExit(main())
