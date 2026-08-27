"""验证 LLM 合并 MEMORY.md 偏好的逻辑

mock LLM 返回，测试：
1. 正常合并（3 条回复简短 → 1 条）
2. 无重复（LLM 返回空 merge_groups）
3. 格式错误（LLM 返回非 JSON）
4. 索引越界（LLM 返回不存在的编号）
5. 组间冲突（同一条目被分到两个组）
6. CoreMemory.llm_merge_preferences 端到端（mock LLM）
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_passed = 0
_failed = 0


def check(name: bool, ok: bool, err: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {err}")


# ── 测试 1：正常合并 ──────────────────────────────────


async def test_normal_merge() -> None:
    """3 条回复简短 + 1 条饮食 + 1 条住址，LLM 正确分组合并"""
    print("\n=== 测试 1：正常合并 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = [
        "回复要简短，不要长篇大论",
        "聊天时回复字数要和用户差不多，只少不多",
        "回复时消息要短、碎片化，像用户一样简洁",
        "饮食禁忌：完全不吃海鲜和鱼，但能接受味精",
        "用户居住在重庆九龙坡",
    ]

    # mock LLM 返回：合并前 3 条
    mock_response = '{"merge_groups": [{"indices": [1, 2, 3], "merged_text": "回复要简短精炼，字数尽量少于用户的消息，像用户一样碎片化简洁，不要长篇大论"}]}'

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    check("移除 2 条", removed == 2, f"removed={removed}")
    check("剩 3 条", len(new_items) == 3, f"len={len(new_items)}")
    check("含合并后文本", "简短精炼" in new_items[0], f"new_items[0]={new_items[0]}")
    check("保留饮食条目", any("海鲜" in i for i in new_items))
    check("保留住址条目", any("重庆" in i for i in new_items))


# ── 测试 2：无重复 ────────────────────────────────────


async def test_no_duplicates() -> None:
    """LLM 返回空 merge_groups，应原样返回"""
    print("\n=== 测试 2：无重复 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["用户居住在重庆", "用户喜欢猫", "用户是程序员"]
    mock_response = '{"merge_groups": []}'

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    check("不移除", removed == 0)
    check("原样返回", new_items == items)
    check("诊断标记 no_valid_groups", diag.get("skipped") == "no_valid_groups" or diag.get("valid_groups_count") == 0)


# ── 测试 3：格式错误 ──────────────────────────────────


async def test_malformed_response() -> None:
    """LLM 返回非 JSON，应安全跳过"""
    print("\n=== 测试 3：格式错误 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["偏好1", "偏好2", "偏好3"]
    mock_response = "这不是JSON，只是随便说说"

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    check("不移除", removed == 0)
    check("原样返回", new_items == items)


# ── 测试 4：索引越界 ──────────────────────────────────


async def test_index_out_of_range() -> None:
    """LLM 返回不存在的编号，应忽略越界索引，有效条目够 2 条才合并"""
    print("\n=== 测试 4：索引越界 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["偏好1", "偏好2", "偏好3"]
    # 编号 5 和 99 不存在，1/2/3 有效（3 条够合并）
    mock_response = '{"merge_groups": [{"indices": [1, 5, 99, 2], "merged_text": "合并12"}]}'

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    # 1 和 2 有效（2 条），合并成 1 条；3 保留
    check("移除 1 条", removed == 1, f"removed={removed}")
    check("剩 2 条", len(new_items) == 2, f"len={len(new_items)}")
    check("含合并文本", "合并12" in new_items)


# ── 测试 5：组间冲突 ──────────────────────────────────


async def test_group_conflict() -> None:
    """同一条目被分到两个组，应只保留第一个组"""
    print("\n=== 测试 5：组间冲突 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["偏好A", "偏好B", "偏好C", "偏好D"]
    # 条目 2 同时在两组里
    mock_response = '{"merge_groups": [{"indices": [1, 2], "merged_text": "合并AB"}, {"indices": [2, 3], "merged_text": "合并BC"}]}'

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    # 第一组 [1,2] 合并成"合并AB"，第二组 [2,3] 因 2 已被消费而跳过
    # 结果：["合并AB", "偏好C", "偏好D"]
    check("移除 1 条", removed == 1, f"removed={removed}")
    check("剩 3 条", len(new_items) == 3, f"len={len(new_items)}")
    check("保留合并AB", "合并AB" in new_items)
    check("保留偏好C", "偏好C" in new_items)
    check("保留偏好D", "偏好D" in new_items)


# ── 测试 6：CoreMemory 端到端 ─────────────────────────


async def test_core_memory_e2e() -> None:
    """mock LLM，验证 CoreMemory.llm_merge_preferences 端到端落盘

    直接操作 _sections 绕过 embedding 去重（这里测的是 LLM 合并逻辑，不是 embedding）
    """
    print("\n=== 测试 6：CoreMemory 端到端 ===")
    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cm = CoreMemory(base_dir=base, scope="test")
        cm.ensure_initialized()

        # 直接塞 3 条进 PREFERENCES（绕过 add_item 的 embedding 去重）
        # 模拟"embedding + 关键词桶漏判后，夜间 LLM 兜底合并"的场景
        cm._sections[MemorySection.PREFERENCES] = [
            "回复要简短",
            "回复字数少一点",  # 跟上一条同义，但假设 embedding 漏判了
            "用户居住在重庆",
        ]
        cm._invalidate_section_cache(MemorySection.PREFERENCES)
        cm._save_sync()

        mock_response = '{"merge_groups": [{"indices": [1, 2], "merged_text": "回复要简短精炼，字数尽量少"}]}'

        with patch(
            "core.services.self_improvement.core_memory_llm_merge._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await cm.llm_merge_preferences()

        check("合并成功", result.get("removed") == 1, f"result={result}")
        check("before=3", result.get("before") == 3)
        check("after=2", result.get("after") == 2)

        # 重新加载验证落盘
        cm2 = CoreMemory(base_dir=base, scope="test")
        await cm2.load()
        prefs = cm2._sections.get(MemorySection.PREFERENCES, [])
        check("落盘后 2 条偏好", len(prefs) == 2, f"prefs={prefs}")
        check("含合并文本", any("简短精炼" in p for p in prefs))
        check("保留住址", any("重庆" in p for p in prefs))


# ── 测试 7：LLM 无响应 ────────────────────────────────


async def test_llm_no_response() -> None:
    """LLM 返回 None（调用失败），应安全跳过"""
    print("\n=== 测试 7：LLM 无响应 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["偏好1", "偏好2"]

    with patch(
        "core.services.self_improvement.core_memory_llm_merge._call_llm",
        new_callable=AsyncMock,
        return_value=None,
    ):
        new_items, removed, diag = await llm_merge_preferences(items)

    check("不移除", removed == 0)
    check("原样返回", new_items == items)
    check("诊断标记 llm_no_response", diag.get("skipped") == "llm_no_response")


# ── 测试 8：少于 2 条跳过 ─────────────────────────────


async def test_too_few_items() -> None:
    """只有 1 条偏好时直接跳过，不调 LLM"""
    print("\n=== 测试 8：少于 2 条跳过 ===")
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    items = ["只有一条偏好"]
    new_items, removed, diag = await llm_merge_preferences(items)
    check("不移除", removed == 0)
    check("原样返回", new_items == items)
    check("诊断标记 too_few_items", diag.get("skipped") == "too_few_items")


async def main() -> int:
    print("=" * 60)
    print("LLM 合并 MEMORY.md 偏好 验证")
    print("=" * 60)

    await test_normal_merge()
    await test_no_duplicates()
    await test_malformed_response()
    await test_index_out_of_range()
    await test_group_conflict()
    await test_core_memory_e2e()
    await test_llm_no_response()
    await test_too_few_items()

    print(f"\n{'=' * 60}")
    print(f"结果: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
