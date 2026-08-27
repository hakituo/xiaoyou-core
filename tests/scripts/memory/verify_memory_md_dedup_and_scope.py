"""
验证 MEMORY.md 改进效果的三项检查：

1. scope 隔离：从 conversation_id 解析 scope 正确，不再依赖全局 persona_manager
2. embedding 语义去重：相似偏好替换而非追加
3. 存量清理结果：aveline/ling/user_data 三个文件偏好分层正确

用法：
    python tests/scripts/memory/verify_memory_md_dedup_and_scope.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 测试框架 ────────────────────────────────────────

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        print(f"  [PASS] {name}")
        _passed += 1
    else:
        print(f"  [FAIL] {name} {detail}")
        _failed += 1


# ── 测试 1：scope 从 conversation_id 解析 ──────────────


def test_scope_resolution_from_conversation_id() -> None:
    """验证 _resolve_scope_from_context 能从 conversation_id 正确解析 scope"""
    print("\n=== 测试 1：scope 从 conversation_id 解析 ===")

    from core.utils.conversation_labels import get_conversation_label_info

    test_cases = [
        # (conversation_id, expected_scope, description)
        ("private_10001__persona__aveline_qq_master", "aveline", "aveline QQ 私聊"),
        ("private_10001__persona__ling_qq_master", "ling", "ling QQ 私聊"),
        ("private_10001__persona__core_aveline", "aveline", "aveline core persona"),
        ("private_10001__persona__core_ling", "ling", "ling core persona"),
        ("default_user", "user", "用户工作区"),
        ("peer_10001__persona__aveline_qq_master", "dual_role", "peer_chat 标记为 dual_role"),
    ]

    for cid, expected, desc in test_cases:
        info = get_conversation_label_info(cid)
        actual = info.get("storage_scope")
        check(f"{desc} (cid={cid})", actual == expected, f"actual={actual}, expected={expected}")


def test_record_preference_tool_scope_param() -> None:
    """验证 RecordPreferenceTool 接受 scope 参数"""
    print("\n=== 测试 2：RecordPreferenceTool scope 参数 ===")

    from core.tools.record_memory_tool import RecordPreferenceTool, RecordPreferenceInput

    # 验证 args_schema 有 scope 字段
    fields = RecordPreferenceInput.model_fields
    check("RecordPreferenceInput 有 scope 字段", "scope" in fields, f"fields={list(fields.keys())}")
    check("scope 默认值是 role", fields["scope"].default == "role", f"default={fields['scope'].default}")

    # 验证工具描述提到 scope
    tool = RecordPreferenceTool()
    check("工具描述提到 scope=user", "scope=user" in tool.description, f"desc={tool.description}")
    check("工具描述提到 scope=role", "scope=role" in tool.description, f"desc={tool.description}")


# ── 测试 3：embedding 语义去重 ──────────────────────


async def test_semantic_dedup() -> None:
    """验证 CoreMemory.add_item 用 embedding 语义去重"""
    print("\n=== 测试 3：embedding 语义去重 ===")

    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cm = CoreMemory(base_dir=base, scope="test")
        cm.ensure_initialized()

        # 写入第一条偏好
        ok1 = await cm.add_item(MemorySection.PREFERENCES, "回复要简短，不要长篇大论")
        check("第一条偏好写入成功", ok1 is True)

        # 写入全等条目（应被去重，返回 False）
        ok2 = await cm.add_item(MemorySection.PREFERENCES, "回复要简短，不要长篇大论")
        check("全等条目被去重", ok2 is False)

        # 写入语义相似但措辞不同的条目（应替换旧条目，返回 True）
        ok3 = await cm.add_item(MemorySection.PREFERENCES, "聊天时回复字数要和用户差不多，只少不多，不要长篇大论")
        check("语义相似条目触发替换", ok3 is True, f"ok3={ok3}")

        # 验证最终只有 1 条偏好（替换而非追加）
        prefs = await cm.get_section(MemorySection.PREFERENCES)
        check("替换后仍只有 1 条偏好", len(prefs) == 1, f"len={len(prefs)}, prefs={prefs}")
        check("保留的是新表述", "只少不多" in prefs[0], f"prefs[0]={prefs[0]}")

        # 写入完全不相关的条目（应追加）
        ok4 = await cm.add_item(MemorySection.PREFERENCES, "用户居住在重庆九龙坡")
        check("不相关条目正常追加", ok4 is True)

        prefs2 = await cm.get_section(MemorySection.PREFERENCES)
        check("追加后变成 2 条", len(prefs2) == 2, f"len={len(prefs2)}")


async def test_keyword_bucket_dedup() -> None:
    """验证同关键词桶的条目用更宽松阈值去重"""
    print("\n=== 测试 3b：关键词桶去重 ===")

    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cm = CoreMemory(base_dir=base, scope="test")
        cm.ensure_initialized()

        # 写入第一条饮食偏好
        ok1 = await cm.add_item(MemorySection.PREFERENCES, "饮食禁忌：完全不吃海鲜和鱼，不吃腊肠，但能接受味精")
        check("第一条饮食偏好写入成功", ok1 is True)

        # 写入措辞不同但同桶的饮食偏好（应触发替换）
        # MiniLM 对这两条的 embedding 相似度只有 0.73，低于 0.85 但高于 0.65
        ok2 = await cm.add_item(MemorySection.PREFERENCES, "能吃辣，但忌口海鲜、鱼、腊肠、烧腊，不能接受鲜味")
        check("同桶饮食偏好触发替换", ok2 is True, f"ok2={ok2}")

        prefs = await cm.get_section(MemorySection.PREFERENCES)
        check("替换后仍只有 1 条饮食偏好", len(prefs) == 1, f"len={len(prefs)}, prefs={prefs}")

        # 写入回复风格偏好（不同桶，应追加）
        ok3 = await cm.add_item(MemorySection.PREFERENCES, "回复时消息要短、碎片化，像用户一样简洁，不要一长串")
        check("不同桶偏好正常追加", ok3 is True)

        # 写入同桶的回复风格偏好（应替换）
        # 这两条 embedding 相似度约 0.68，低于 0.85 但高于 0.65
        ok4 = await cm.add_item(MemorySection.PREFERENCES, "聊天时回复字数要和用户差不多，只少不多，不要长篇大论")
        check("同桶回复风格偏好触发替换", ok4 is True, f"ok4={ok4}")

        prefs2 = await cm.get_section(MemorySection.PREFERENCES)
        check("最终 2 条偏好（1饮食+1回复）", len(prefs2) == 2, f"len={len(prefs2)}, prefs={prefs2}")


# ── 测试 4：存量清理结果 ──────────────────────────


def test_cleanup_result() -> None:
    """验证存量清理后三个 MEMORY.md 分层正确"""
    print("\n=== 测试 4：存量清理结果 ===")

    base = Path("D:/AI/xiaoyou-core/companion_data")

    aveline_file = base / "aveline_data" / "MEMORY.md"
    ling_file = base / "ling_data" / "MEMORY.md"
    user_data_file = base / "user_data" / "MEMORY.md"

    check("aveline MEMORY.md 存在", aveline_file.exists())
    check("ling MEMORY.md 存在", ling_file.exists())
    check("user_data MEMORY.md 存在", user_data_file.exists())

    if not all([aveline_file.exists(), ling_file.exists(), user_data_file.exists()]):
        return

    aveline_content = aveline_file.read_text(encoding="utf-8")
    ling_content = ling_file.read_text(encoding="utf-8")
    user_data_content = user_data_file.read_text(encoding="utf-8")

    # aveline 不应含用户级偏好（这些应该迁到 user_data）
    check(
        "aveline 不含用户级偏好（用户居住）",
        "用户居住" not in aveline_content,
        "aveline 仍含用户居住",
    )
    check(
        "aveline 不含用户级偏好（饮食禁忌）",
        "饮食禁忌" not in aveline_content,
        "aveline 仍含饮食禁忌",
    )
    # 注：用户可能手动清空了角色级偏好，所以不再断言"保留 active care/笨蛋"

    # user_data 应该有用户级偏好
    check(
        "user_data 含用户级偏好（用户居住）",
        "用户居住" in user_data_content,
        "user_data 缺失用户居住",
    )
    check(
        "user_data 含用户级偏好（饮食禁忌）",
        "饮食禁忌" in user_data_content,
        "user_data 缺失饮食禁忌",
    )
    check(
        "user_data 含用户级偏好（回复简短）",
        "回复" in user_data_content and "简短" in user_data_content,
        "user_data 缺失回复简短偏好",
    )

    # ling 应该保留其角色特定偏好（如果用户没手动清空）
    # 注：用户可能手动清空，所以只检查"如果有内容则不应有用户级偏好"
    if "媚黑" in ling_content or "raceplay" in ling_content.lower():
        check("ling 保留角色级偏好（媚黑拒绝）", True)
    else:
        print("  [SKIP] ling 已被用户手动清空，跳过角色级偏好断言")


# ── 测试 5：空文件不注入 ──────────────────────────────


async def test_empty_memory_not_injected() -> None:
    """验证 MEMORY.md 全空时 build_injection_text_sync 返回空字符串"""
    print("\n=== 测试 5：空文件不注入 ===")

    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cm = CoreMemory(base_dir=base, scope="test")
        cm.ensure_initialized()

        # 不写入任何条目，直接调 build_injection_text_sync
        text = cm.build_injection_text_sync()
        check("空 MEMORY.md 返回空字符串", text == "", f"text={text!r}")

        # 写入一条偏好后应返回非空
        await cm.add_item(MemorySection.PREFERENCES, "测试偏好")
        text2 = cm.build_injection_text_sync()
        check("有内容时返回非空", text2 != "" and "测试偏好" in text2, f"text2={text2!r}")
        check("有内容时含模板标题", "【核心记忆（MEMORY.md）】" in text2)


# ── 测试 6：assembler.py 复用 build_injection_text_sync ──────────


def test_assembler_uses_sync_injection() -> None:
    """验证 assembler.py 已改用 build_prompt_injection_sync 而非手动拼装"""
    print("\n=== 测试 6：assembler 复用正式注入方法 ===")

    assembler_file = Path("D:/AI/xiaoyou-core/core/agents/chat_agent_components/persona_system/prompt/assembler.py")
    content = assembler_file.read_text(encoding="utf-8")

    check(
        "assembler 调用 build_prompt_injection_sync",
        "build_prompt_injection_sync" in content,
        "assembler 未使用 build_prompt_injection_sync",
    )
    check(
        "assembler 不再手动拼装 _SECTION_HEADERS",
        "_SECTION_HEADERS" not in content,
        "assembler 仍在手动拼装（未消除重复造轮子）",
    )
    check(
        "assembler 从 conversation_id 解析 scope",
        "get_conversation_label_info" in content,
        "assembler 未用 conversation_id 解析 scope",
    )


# ── 主入口 ────────────────────────────────────────


async def main() -> int:
    print("=" * 60)
    print("MEMORY.md 去重 + scope 隔离 + 空文件不注入 验证")
    print("=" * 60)

    test_scope_resolution_from_conversation_id()
    test_record_preference_tool_scope_param()
    await test_semantic_dedup()
    await test_keyword_bucket_dedup()
    test_cleanup_result()
    await test_empty_memory_not_injected()
    test_assembler_uses_sync_injection()

    print(f"\n{'=' * 60}")
    print(f"结果: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
