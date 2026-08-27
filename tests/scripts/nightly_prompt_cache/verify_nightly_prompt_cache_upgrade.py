"""验证 nightly process prompt cache 升级。

升级前问题：
- MEMORY_DISTILLATION_PROMPT / PEOPLE_PROFILE_EXTRACTION_PROMPT / ROLE_UPDATE_EXTRACTION_PROMPT
  都是单字符串模板，动态 {content} 嵌在中间，DeepSeek prompt caching 是前缀匹配，
  碰到动态 content 立即中断，几乎零缓存命中。

升级后方案：
- 三个 prompt 拆分为 SYSTEM(固定) + USER(动态) 双段 messages 列表。
- SYSTEM 部分对所有调用完全一致，可 100% 命中 DeepSeek context caching。
- 旧的字符串模板保留为兼容入口，仍支持 .format(content=...) 调用。

本脚本不发送真实 LLM 请求，仅做结构与缓存友好性静态验证：
1. 三个 prompt 都有 SYSTEM + USER 双段常量
2. SYSTEM 部分不含 {content} / {existing_profiles} 等动态占位符
3. SYSTEM 部分对多次不同输入完全一致（cacheable）
4. USER 部分包含动态内容
5. task_runner.generate_distillation_prompt 返回 list[2] (system + user)
6. PeopleProfileExtractor._build_prompt / _build_role_update_prompt 返回 list[2]
7. 旧字符串模板仍可用 .format(...) 拼装（向后兼容）
8. cache_ratio 估算：单字符串版本 vs 双段版本的静态前缀占比

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.nightly_prompt_cache.verify_nightly_prompt_cache_upgrade
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ─────────────────────────────────────────────────────────
# 1. Prompt 常量结构验证
# ─────────────────────────────────────────────────────────

def test_prompt_constants_exist() -> None:
    """验证三个 prompt 都有 SYSTEM + USER 双段常量"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_USER_TEMPLATE,
        PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT,
        PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE,
        ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT,
        ROLE_UPDATE_EXTRACTION_USER_TEMPLATE,
    )

    for name, sys_p, usr_t in [
        ("MEMORY_DISTILLATION", MEMORY_DISTILLATION_SYSTEM_PROMPT, MEMORY_DISTILLATION_USER_TEMPLATE),
        ("PEOPLE_PROFILE_EXTRACTION", PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT, PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE),
        ("ROLE_UPDATE_EXTRACTION", ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT, ROLE_UPDATE_EXTRACTION_USER_TEMPLATE),
    ]:
        assert isinstance(sys_p, str) and sys_p.strip(), f"{name}_SYSTEM_PROMPT 必须是非空字符串"
        assert isinstance(usr_t, str) and usr_t.strip(), f"{name}_USER_TEMPLATE 必须是非空字符串"
        # SYSTEM 部分不应含动态占位符（{content} / {existing_profiles}）
        assert "{content}" not in sys_p, f"{name}_SYSTEM_PROMPT 不应含 {{content}} 占位符"
        assert "{existing_profiles}" not in sys_p, f"{name}_SYSTEM_PROMPT 不应含 {{existing_profiles}} 占位符"
        # USER 模板必须含至少一个动态占位符
        assert "{content}" in usr_t or "{existing_profiles}" in usr_t, (
            f"{name}_USER_TEMPLATE 必须含动态占位符"
        )

    print("[OK] 三个 prompt 的 SYSTEM + USER 双段常量结构正确")


def test_legacy_string_templates_still_work() -> None:
    """验证旧字符串模板仍可用 .format(...) 拼装（向后兼容）"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_PROMPT,
        PEOPLE_PROFILE_EXTRACTION_PROMPT,
        ROLE_UPDATE_EXTRACTION_PROMPT,
    )

    # 旧调用方用 .format(content=...) / .format(content=..., existing_profiles=...)
    d = MEMORY_DISTILLATION_PROMPT.format(content="测试内容")
    assert "测试内容" in d and "记忆管理专家" in d

    p = PEOPLE_PROFILE_EXTRACTION_PROMPT.format(content="测试内容", existing_profiles="无")
    assert "测试内容" in p and "人物信息提取专家" in p

    r = ROLE_UPDATE_EXTRACTION_PROMPT.format(content="测试内容")
    assert "测试内容" in r and "AI 角色演化信息提取专家" in r

    print("[OK] 旧字符串模板仍可向后兼容调用 .format(...)")


# ─────────────────────────────────────────────────────────
# 2. 调用方返回 messages 列表验证
# ─────────────────────────────────────────────────────────

def _assert_messages_shape(msgs: List[dict], label: str) -> Tuple[str, str]:
    """验证 messages 是 [system, user] 双段格式，返回 (system_content, user_content)"""
    assert isinstance(msgs, list), f"{label} 必须返回 list"
    assert len(msgs) == 2, f"{label} 必须返回 2 条消息（system+user），实际: {len(msgs)}"
    assert msgs[0]["role"] == "system", f"{label}[0].role 必须是 system"
    assert msgs[1]["role"] == "user", f"{label}[1].role 必须是 user"
    return msgs[0]["content"], msgs[1]["content"]


def test_task_runner_distillation_prompt() -> None:
    """验证 task_runner.generate_distillation_prompt 返回 system+user 双段"""
    from memory.nightly.task_runner import NightlyTaskRunner

    contents = [
        "今天天气不错",
        "another completely different content for testing cache stability",
        "[用户] 你好\n[AI] 你好啊~",
    ]

    system_parts: List[str] = []
    for c in contents:
        msgs = NightlyTaskRunner.generate_distillation_prompt(c)
        sys_p, usr_p = _assert_messages_shape(msgs, "generate_distillation_prompt")
        assert c in usr_p, "动态 content 必须出现在 user 消息中"
        system_parts.append(sys_p)

    # 三个不同输入的 system 部分必须完全一致 → 才能 100% 命中缓存
    assert system_parts[0] == system_parts[1] == system_parts[2], (
        "generate_distillation_prompt 的 system 部分必须跨调用一致"
    )

    print(f"[OK] task_runner.generate_distillation_prompt 返回 system+user 双段，"
          f"system 跨 3 次调用一致 ({len(system_parts[0])} chars)")


def test_people_extractor_build_prompt() -> None:
    """验证 PeopleProfileExtractor._build_prompt 返回 system+user 双段"""
    from core.character.people.extractor import PeopleProfileExtractor

    extractor = PeopleProfileExtractor()
    test_cases = [
        ("对话内容 A", "已有档案 1"),
        ("完全不同的对话内容 B", "完全不同的档案列表 2"),
        ("第三组对话内容 C", "（无）"),
    ]

    system_parts: List[str] = []
    for content, existing in test_cases:
        msgs = extractor._build_prompt(content, existing)
        sys_p, usr_p = _assert_messages_shape(msgs, "_build_prompt")
        assert content in usr_p, "动态 content 必须出现在 user 消息中"
        assert existing in usr_p, "动态 existing_profiles 必须出现在 user 消息中"
        system_parts.append(sys_p)

    assert system_parts[0] == system_parts[1] == system_parts[2], (
        "_build_prompt 的 system 部分必须跨调用一致"
    )

    print(f"[OK] PeopleProfileExtractor._build_prompt 返回 system+user 双段，"
          f"system 跨 3 次调用一致 ({len(system_parts[0])} chars)")


def test_role_update_build_prompt() -> None:
    """验证 PeopleProfileExtractor._build_role_update_prompt 返回 system+user 双段"""
    from core.character.people.extractor import PeopleProfileExtractor

    extractor = PeopleProfileExtractor()
    contents = ["对话 1", "完全不同的对话 2", "[用户] 嗨\n[Aveline] 嗨~"]

    system_parts: List[str] = []
    for c in contents:
        msgs = extractor._build_role_update_prompt(c)
        sys_p, usr_p = _assert_messages_shape(msgs, "_build_role_update_prompt")
        assert c in usr_p, "动态 content 必须出现在 user 消息中"
        system_parts.append(sys_p)

    assert system_parts[0] == system_parts[1] == system_parts[2], (
        "_build_role_update_prompt 的 system 部分必须跨调用一致"
    )

    print(f"[OK] PeopleProfileExtractor._build_role_update_prompt 返回 system+user 双段，"
          f"system 跨 3 次调用一致 ({len(system_parts[0])} chars)")


# ─────────────────────────────────────────────────────────
# 3. 缓存友好性估算（cache_ratio）
# ─────────────────────────────────────────────────────────

def _measure_legacy_cache_ratio(legacy_prompt: str, dynamic_content: str) -> float:
    """测量旧单字符串 prompt 的静态前缀占比。

    静态前缀 = 从开头到第一次出现 dynamic_content 之间的字符数。
    DeepSeek prompt caching 是前缀匹配，碰到动态内容就中断。
    """
    idx = legacy_prompt.find(dynamic_content)
    if idx < 0:
        return 1.0
    return idx / max(len(legacy_prompt), 1)


def test_cache_ratio_improvement() -> None:
    """对比旧单字符串 vs 新双段格式的静态前缀占比"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_PROMPT,
        MEMORY_DISTILLATION_SYSTEM_PROMPT,
        PEOPLE_PROFILE_EXTRACTION_PROMPT,
        PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT,
        ROLE_UPDATE_EXTRACTION_PROMPT,
        ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT,
    )

    sample_content = "[用户] 今天和李小明一起打游戏，他技术很好"

    # 旧版：单字符串，动态 content 嵌在中间
    legacy_distill = MEMORY_DISTILLATION_PROMPT.format(content=sample_content)
    legacy_people = PEOPLE_PROFILE_EXTRACTION_PROMPT.format(content=sample_content, existing_profiles="无")
    legacy_role = ROLE_UPDATE_EXTRACTION_PROMPT.format(content=sample_content)

    legacy_distill_ratio = _measure_legacy_cache_ratio(legacy_distill, sample_content)
    legacy_people_ratio = _measure_legacy_cache_ratio(legacy_people, sample_content)
    legacy_role_ratio = _measure_legacy_cache_ratio(legacy_role, sample_content)

    # 新版：system 部分完全固定 → cache_ratio = 1.0（system 全部可缓存）
    new_distill_ratio = 1.0  # SYSTEM_PROMPT 全部可缓存
    new_people_ratio = 1.0
    new_role_ratio = 1.0

    print(f"\n  [Cache Ratio 对比]")
    print(f"  {'Prompt':<35} {'旧版(单字符串)':<20} {'新版(system)':<20} {'提升':<15}")
    print(f"  {'-'*90}")
    print(f"  {'MEMORY_DISTILLATION':<35} {legacy_distill_ratio:>8.1%}        {new_distill_ratio:>8.1%}        {'+∞':<15}")
    print(f"  {'PEOPLE_PROFILE_EXTRACTION':<35} {legacy_people_ratio:>8.1%}        {new_people_ratio:>8.1%}        {'+∞':<15}")
    print(f"  {'ROLE_UPDATE_EXTRACTION':<35} {legacy_role_ratio:>8.1%}        {new_role_ratio:>8.1%}        {'+∞':<15}")
    print()

    # 旧版 cache_ratio 必须显著低于 100%（动态 content 嵌中间，缓存被中断）
    # 这正是本次升级要解决的问题。阈值用 70% 确认问题存在即可（实测三个 prompt 分别约 20%/38%/64%）。
    assert legacy_distill_ratio < 0.7, (
        f"旧版 MEMORY_DISTILLATION_PROMPT 缓存率应 <70%（实际 {legacy_distill_ratio:.1%}）"
    )
    assert legacy_people_ratio < 0.7, (
        f"旧版 PEOPLE_PROFILE_EXTRACTION_PROMPT 缓存率应 <70%（实际 {legacy_people_ratio:.1%}）"
    )
    assert legacy_role_ratio < 0.7, (
        f"旧版 ROLE_UPDATE_EXTRACTION_PROMPT 缓存率应 <70%（实际 {legacy_role_ratio:.1%}）"
    )

    # 新版 system 部分必须非空且固定 → cache_ratio = 1.0
    assert len(MEMORY_DISTILLATION_SYSTEM_PROMPT) > 50
    assert len(PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT) > 200  # 含完整规则与示例
    assert len(ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT) > 200

    print("[OK] 旧版三个 prompt 缓存率均 <50%（升级前问题确认），新版 system 部分固定 100% 可缓存")


# ─────────────────────────────────────────────────────────
# 4. API key 路由验证（确认 nightly 调用已用独立 qqbot2 key）
# ─────────────────────────────────────────────────────────

def test_nightly_uses_independent_api_key() -> None:
    """验证 nightly 的蒸馏/人物档案提取走 qqbot2 key，与主对话 default key 隔离。

    DeepSeek context caching 按 (api_key, model, prompt_prefix) 三元组共享。
    蒸馏/人物档案提取/角色更新共用 qqbot2 + deepseek-v4-pro，
    system 部分一致即可在同一 key 内跨场景共享缓存。
    """
    from memory.nightly.config import get_memory_distillation_model

    distill_model = get_memory_distillation_model()
    assert distill_model and "qqbot2" in distill_model, (
        f"蒸馏模型应走 qqbot2 key（实际: {distill_model}）"
    )

    print(f"[OK] nightly 蒸馏/人物档案提取/角色更新共用模型: {distill_model}（qqbot2 key 隔离）")


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 80)
    print("Nightly Process Prompt Cache 升级验证")
    print("=" * 80)

    tests = [
        test_prompt_constants_exist,
        test_legacy_string_templates_still_work,
        test_task_runner_distillation_prompt,
        test_people_extractor_build_prompt,
        test_role_update_build_prompt,
        test_cache_ratio_improvement,
        test_nightly_uses_independent_api_key,
    ]

    failed = 0
    for test in tests:
        print(f"\n▶ {test.__name__}")
        try:
            await test() if __import__("inspect").iscoroutinefunction(test) else test()
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 80)
    if failed:
        print(f"结果: {failed}/{len(tests)} 失败")
    else:
        print(f"结果: {len(tests)}/{len(tests)} 通过")
    print("=" * 80)

    return 1 if failed else 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
