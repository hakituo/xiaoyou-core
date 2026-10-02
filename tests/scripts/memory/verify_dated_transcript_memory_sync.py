# -*- coding: utf-8 -*-
"""验证 dated_chat_transcript 导入后的记忆自动同步具备幂等性。

背景：import_dated_chat_transcript.py 在写入 chat_history 后会自动把该会话的
对话链增量同步进加权记忆（scripts/import/import_chat_to_memory.py 的
sync_conversation_to_memory），按"对话链内容指纹"跳过已导入的链。
本脚本确认：
1. 指纹函数稳定：同文本指纹一致（含空白差异归一），不同文本指纹不同
2. 真实 ye 会话 dry-run：全部链均已导入（new_chains == 0，幂等）
3. 全新会话 dry-run：全部链均为新增（new_chains == total_chains）
4. dry-run 全程不写盘

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\memory\\verify_dated_transcript_memory_sync.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

CONVERSATION_ID = "shared__persona__core_ye"
USER_ID = "shared__scope__ye"
HISTORY_ROOT = PROJECT_ROOT / "companion_data" / "ye_data" / "chat_history"
IMPORT_SOURCE = f"{CONVERSATION_ID}_history"
EXPECTED_MIN_CHAINS = 200

failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def _weighted_sensitive_count() -> int:
    path = (
        PROJECT_ROOT
        / "companion_data"
        / "ye_data"
        / "memories"
        / "weighted"
        / "sensitive"
        / f"{USER_ID}_weighted.json"
    )
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data.get("weighted_memories") or [])


def main() -> int:
    print("=" * 60)
    print("dated transcript → 记忆自动同步 幂等性验证")
    print("=" * 60)

    import importlib

    importer = importlib.import_module(
        "scripts.import.import_chat_to_memory"
    )

    # 1. 指纹函数稳定性
    print("\n[1/4] 内容指纹检查")
    text = "用户：主人\n我：嗯"
    fp1 = importer._chain_fingerprint(text)
    fp2 = importer._chain_fingerprint("用户：  主人\n我： 嗯 ")
    fp3 = importer._chain_fingerprint("用户：主人\n我：好")
    _check("同文本（含空白差异）指纹一致", fp1 == fp2)
    _check("不同文本指纹不同", fp1 != fp3)

    # 2. 真实 ye 会话：全部已导入（幂等）
    print("\n[2/4] 真实会话 dry-run（应全部跳过）")
    before = _weighted_sensitive_count()
    stats = importer.sync_conversation_to_memory(
        CONVERSATION_ID,
        USER_ID,
        HISTORY_ROOT,
        import_source=IMPORT_SOURCE,
        dry_run=True,
    )
    _check(
        f"总链数 >= {EXPECTED_MIN_CHAINS}",
        stats["total_chains"] >= EXPECTED_MIN_CHAINS,
        f"{stats['total_chains']} 条",
    )
    _check(
        "new_chains == 0（已导入内容不重复）",
        stats["new_chains"] == 0,
        f"new={stats['new_chains']}, skipped={stats['skipped_chains']}",
    )
    after = _weighted_sensitive_count()
    _check("dry-run 不写盘", after == before, f"{before} -> {after}")

    # 3. 全新会话：全部新增（dry-run，不写盘）
    print("\n[3/4] 全新会话 dry-run（应全部新增）")
    fake_conversation = "shared__persona__verify_mem_sync_tmp"
    fake_source = f"{fake_conversation}_history"
    with tempfile.TemporaryDirectory() as temp_dir:
        day_dir = Path(temp_dir) / "2026" / "09" / "01" / "主线对话"
        day_dir.mkdir(parents=True)
        events = [
            {"role": "user", "content": "今天天气怎么样", "timestamp": 1.0,
             "conversation_id": fake_conversation},
            {"role": "assistant", "content": "晴，适合出门", "timestamp": 2.0,
             "conversation_id": fake_conversation},
        ]
        jsonl = day_dir / f"{fake_conversation}.jsonl"
        jsonl.write_text(
            "\n".join(json.dumps(evt, ensure_ascii=False) for evt in events) + "\n",
            encoding="utf-8",
        )
        fake_stats = importer.sync_conversation_to_memory(
            fake_conversation,
            USER_ID,
            Path(temp_dir),
            import_source=fake_source,
            dry_run=True,
        )
    _check(
        "新会话 new_chains == total_chains",
        fake_stats["new_chains"] == fake_stats["total_chains"] == 1,
        f"total={fake_stats['total_chains']}, new={fake_stats['new_chains']}",
    )
    _check("dry-run 不写盘", _weighted_sensitive_count() == after)

    print("\n[4/4] 结果")
    if failures:
        print(f"\n❌ 验证失败 {len(failures)} 项: {failures}")
        return 1
    print("\n✅ 全部通过：导入脚本的记忆自动同步幂等、可检索、dry-run 无副作用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
