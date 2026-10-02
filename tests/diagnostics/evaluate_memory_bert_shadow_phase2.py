import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


TEST_CASES = [
    ("明天下午两点要开项目复盘会，记得准备汇报", "work"),
    ("最近在复习线性代数和概率论，准备下周考试", "learning"),
    ("今天喉咙很痛，还发烧了，想去医院看看", "health"),
    ("昨天晚上追完了一部新动漫，音乐也很好听", "entertainment"),
    ("这个月房租和信用卡都要还，预算有点紧", "finance"),
    ("早上起床做了早餐，晚上还得去超市买菜", "daily"),
    ("客户要求本周五之前交付新版本功能", "work"),
    ("最近在学 FastAPI 和异步编程，准备做个项目", "learning"),
    ("医生说要注意血压，最近得坚持运动", "health"),
    ("周末想和朋友去看电影顺便吃火锅", "entertainment"),
    ("刚刚买了新的显卡，准备升级一下电脑", "tech"),
    ("银行卡账单提醒我这个月支出超了", "finance"),
    ("今天下雨，出门的时候别忘了带伞", "daily"),
    ("老板让我整理发布计划和风险清单", "work"),
    ("我在看算法题，准备刷完这套训练营", "learning"),
    ("昨晚失眠到三点，今天整个人都没精神", "health"),
    ("最近在玩一款剧情游戏，配乐特别上头", "entertainment"),
    ("准备做一份年度理财规划，控制消费", "finance"),
    ("晚上想早点睡，明天还得早起赶地铁", "daily"),
    ("在研究向量检索和语义召回的实现方式", "tech"),
]


def _patch_memory_dirs(module, history_root: Path):
    import memory.core.manager_init_ops as manager_init_ops

    original = {
        "HISTORY_DIR": module.HISTORY_DIR,
        "DEFAULT_HISTORY_DIR": module.DEFAULT_HISTORY_DIR,
        "LONG_TERM_DIR": module.LONG_TERM_DIR,
        "WEIGHTED_MEMORY_DIR": module.WEIGHTED_MEMORY_DIR,
        "SHORT_TERM_DIR": module.SHORT_TERM_DIR,
        "SENSITIVE_DIR": module.SENSITIVE_DIR,
        "READABLE_DIR": module.READABLE_DIR,
        "get_memories_dir_for_conversation": manager_init_ops.get_memories_dir_for_conversation,
    }
    module.HISTORY_DIR = history_root
    module.DEFAULT_HISTORY_DIR = history_root.resolve()
    module.LONG_TERM_DIR = history_root / "long_term"
    module.WEIGHTED_MEMORY_DIR = history_root / "weighted"
    module.SHORT_TERM_DIR = history_root / "short_term"
    module.SENSITIVE_DIR = history_root / "sensitive"
    module.READABLE_DIR = history_root / "readable"
    manager_init_ops.get_memories_dir_for_conversation = lambda _conversation_id: str(history_root)
    return original


def _restore_memory_dirs(module, original: dict):
    import memory.core.manager_init_ops as manager_init_ops

    for key, value in original.items():
        if key == "get_memories_dir_for_conversation":
            manager_init_ops.get_memories_dir_for_conversation = value
            continue
        setattr(module, key, value)


def run_check() -> int:
    import memory.weighted_memory_manager as memory_module

    with tempfile.TemporaryDirectory() as tmpdir:
        history_root = Path(tmpdir) / "history"
        history_root.mkdir(parents=True, exist_ok=True)
        original_dirs = _patch_memory_dirs(memory_module, history_root)
        manager = None
        try:
            manager = memory_module.WeightedMemoryManager(
                user_id="bert_shadow_phase2_eval",
                auto_save_interval=0,
                skip_auto_reclassify=True,
            )
            manager.clear_memory(mode="all")
            memory_ids = []
            for idx, (content, _) in enumerate(TEST_CASES):
                memory_ids.append(
                    manager.add_memory(
                        content=content,
                        source="user",
                        metadata={
                            "defer_analysis": True,
                            "case_id": f"phase2_{idx}",
                        },
                    )
                )

            result = manager.process_pending_analysis(limit=64)
            if int(result.get("processed") or 0) < len(TEST_CASES):
                print("FAIL: process_pending_analysis 未处理完 Phase 2 测例")
                return 2

            memories = {item.get("id"): item for item in manager.get_weighted_memories(limit=128)}
            rule_uncategorized = 0
            bert_uncategorized = 0
            category_conflicts = 0
            matched_expected = 0
            bert_shadow_count = 0

            for memory_id, (_, expected_category) in zip(memory_ids, TEST_CASES):
                memory = memories.get(memory_id)
                if not isinstance(memory, dict):
                    print("FAIL: 无法读取 Phase 2 评测记忆")
                    return 3
                metadata = memory.get("metadata") or {}
                analysis_meta = metadata.get("analysis_meta") or {}
                rule_block = analysis_meta.get("rule") or {}
                bert_block = analysis_meta.get("bert_shadow") or {}
                if not isinstance(rule_block, dict) or not isinstance(bert_block, dict):
                    print("FAIL: 缺少 rule 或 bert_shadow 分析块")
                    return 4
                if not str(bert_block.get("input_text") or "").startswith("标题："):
                    print("FAIL: BERT 输入不是清洗后的可读文本")
                    return 5
                if str(bert_block.get("status") or "") != "ok":
                    print("FAIL: BERT 影子分类未成功产出")
                    return 6
                if "ai_shadow" not in metadata:
                    print("FAIL: 未复用 ai_shadow 管线")
                    return 7

                rule_category = str(rule_block.get("category") or "uncategorized")
                bert_category = str(bert_block.get("category") or "uncategorized")
                if rule_category == "uncategorized":
                    rule_uncategorized += 1
                if bert_category == "uncategorized":
                    bert_uncategorized += 1
                if rule_category != bert_category:
                    category_conflicts += 1
                if bert_category == expected_category:
                    matched_expected += 1
                bert_shadow_count += 1

            if bert_shadow_count != len(TEST_CASES):
                print("FAIL: BERT 影子分类产出数量异常")
                return 8
            if bert_uncategorized > rule_uncategorized:
                print("FAIL: BERT 未压低 uncategorized")
                return 9
            if matched_expected < 12:
                print("FAIL: BERT 影子分类命中期望类别过少")
                return 10

            payload = {
                "total_cases": len(TEST_CASES),
                "bert_shadow_count": bert_shadow_count,
                "rule_uncategorized": rule_uncategorized,
                "bert_uncategorized": bert_uncategorized,
                "category_conflicts": category_conflicts,
                "matched_expected": matched_expected,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("OK: Phase 2 BERT 影子分类已接入记忆分析流程")
            return 0
        finally:
            if manager is not None:
                manager.shutdown()
            _restore_memory_dirs(memory_module, original_dirs)


if __name__ == "__main__":
    raise SystemExit(run_check())
