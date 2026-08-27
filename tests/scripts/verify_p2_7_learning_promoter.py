"""P2-7 验证：LearningPromoter 真正的晋升逻辑

验证要点：
1. _promote_to_rules 真正写入 project_rules.md
2. _promote_to_core_memory 通过注入的 CoreMemory 写入 MEMORY.md
3. _promote_to_prompt 真正写入 promoted_rules.md
4. 写入去重（重复晋升同一条规则不会产生重复条目）
5. 原子写入（使用 safe_write_text）
6. service.py 正确注入 CoreMemory 实例
7. 完整晋升流程：find_promotion_candidates → promote
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_promote_to_rules_writes_file() -> list[str]:
    issues: list[str] = []
    _section("测试 1：_promote_to_rules 真正写入 project_rules.md")

    from core.services.self_improvement.learning_promoter import LearningPromoter

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rules_file = tmp_path / ".trae" / "rules" / "project_rules.md"

        promoter = LearningPromoter(tmp_path, tmp_path)
        # 直接覆盖 _rules_file 路径，避免污染真实项目
        promoter._rules_file = rules_file

        rule_text = "测试规则：避免在 async 函数中调用阻塞 IO"
        success = asyncio.run(promoter._promote_to_rules(rule_text))

        if not success:
            issues.append("_promote_to_rules 返回 False")
        elif not rules_file.exists():
            issues.append("project_rules.md 文件未创建")
        else:
            content = rules_file.read_text(encoding="utf-8")
            if rule_text not in content:
                issues.append(f"规则文本未写入文件: {content}")
            else:
                _ok(f"规则已写入 project_rules.md: {rules_file}")
                _ok(f"文件内容包含规则文本（长度 {len(content)}）")

    if not issues:
        _ok("_promote_to_rules 写入验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_promote_to_rules_dedup() -> list[str]:
    issues: list[str] = []
    _section("测试 2：_promote_to_rules 去重（重复晋升不产生重复条目）")

    from core.services.self_improvement.learning_promoter import LearningPromoter

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rules_file = tmp_path / ".trae" / "rules" / "project_rules.md"

        promoter = LearningPromoter(tmp_path, tmp_path)
        promoter._rules_file = rules_file

        rule_text = "去重测试规则：始终使用 asyncio.to_thread 包装阻塞调用"

        # 第一次写入
        asyncio.run(promoter._promote_to_rules(rule_text))
        # 第二次写入相同规则
        success = asyncio.run(promoter._promote_to_rules(rule_text))

        if not success:
            issues.append("第二次晋升返回 False（去重应返回 True）")
        else:
            content = rules_file.read_text(encoding="utf-8")
            count = content.count(rule_text)
            if count != 1:
                issues.append(f"规则出现 {count} 次（应为 1 次）")
            else:
                _ok("去重成功，规则仅出现 1 次")

    if not issues:
        _ok("去重验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_promote_to_prompt_writes_file() -> list[str]:
    issues: list[str] = []
    _section("测试 3：_promote_to_prompt 真正写入 promoted_rules.md")

    from core.services.self_improvement.learning_promoter import LearningPromoter

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        prompt_file = (
            tmp_path
            / "core"
            / "agents"
            / "chat_agent_components"
            / "persona_system"
            / "prompt"
            / "promoted_rules.md"
        )

        promoter = LearningPromoter(tmp_path, tmp_path)
        promoter._prompt_rules_file = prompt_file

        rule_text = "Prompt 晋升测试：在生成代码前先验证 API 存在性"
        success = asyncio.run(promoter._promote_to_prompt(rule_text))

        if not success:
            issues.append("_promote_to_prompt 返回 False")
        elif not prompt_file.exists():
            issues.append("promoted_rules.md 文件未创建")
        else:
            content = prompt_file.read_text(encoding="utf-8")
            if rule_text not in content:
                issues.append(f"规则文本未写入 promoted_rules.md: {content}")
            else:
                _ok(f"规则已写入 promoted_rules.md: {prompt_file}")

    if not issues:
        _ok("_promote_to_prompt 写入验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_promote_to_core_memory_writes() -> list[str]:
    issues: list[str] = []
    _section("测试 4：_promote_to_core_memory 通过 CoreMemory 写入 MEMORY.md")

    from core.services.self_improvement.learning_promoter import LearningPromoter
    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        core_memory = CoreMemory(tmp_path, scope="user")
        core_memory.ensure_initialized()

        promoter = LearningPromoter(
            tmp_path, tmp_path, core_memory=core_memory
        )

        rule_text = "CoreMemory 晋升测试：使用原子写入避免文件截断"
        success = asyncio.run(promoter._promote_to_core_memory(rule_text))

        if not success:
            issues.append("_promote_to_core_memory 返回 False")
        else:
            # 验证 MEMORY.md 包含规则
            experience = asyncio.run(
                core_memory.get_section(MemorySection.EXPERIENCE)
            )
            found = any(rule_text in item for item in experience)
            if not found:
                issues.append(
                    f"规则未出现在 EXPERIENCE 分区: {experience}"
                )
            else:
                _ok("规则已写入 MEMORY.md EXPERIENCE 分区")

        # 验证注入的 CoreMemory 实例被复用
        if promoter._core_memory is not core_memory:
            issues.append("LearningPromoter 未复用注入的 CoreMemory 实例")
        else:
            _ok("LearningPromoter 复用注入的 CoreMemory 实例")

    if not issues:
        _ok("_promote_to_core_memory 写入验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_promote_to_core_memory_dedup() -> list[str]:
    issues: list[str] = []
    _section("测试 5：_promote_to_core_memory 去重")

    from core.services.self_improvement.learning_promoter import LearningPromoter
    from core.services.self_improvement.core_memory import CoreMemory, MemorySection

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        core_memory = CoreMemory(tmp_path, scope="user")
        core_memory.ensure_initialized()

        promoter = LearningPromoter(
            tmp_path, tmp_path, core_memory=core_memory
        )

        rule_text = "去重测试：MEMORY.md 不应出现重复条目"
        asyncio.run(promoter._promote_to_core_memory(rule_text))
        asyncio.run(promoter._promote_to_core_memory(rule_text))

        experience = asyncio.run(
            core_memory.get_section(MemorySection.EXPERIENCE)
        )
        count = sum(1 for item in experience if rule_text in item)
        if count != 1:
            issues.append(f"规则出现 {count} 次（应为 1 次）")
        else:
            _ok("MEMORY.md 去重成功，规则仅出现 1 次")

    if not issues:
        _ok("CoreMemory 去重验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_atomic_write_usage() -> list[str]:
    issues: list[str] = []
    _section("测试 6：晋升写入使用 safe_write_text（原子写入）")

    # 通过 AST 检查源码是否调用 safe_write_text
    import ast

    src_file = Path(
        "core/services/self_improvement/learning_promoter.py"
    )
    src = (PROJECT_ROOT / src_file).read_text(encoding="utf-8")
    tree = ast.parse(src)

    safe_write_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "safe_write_text":
                safe_write_calls += 1

    if safe_write_calls < 2:
        issues.append(
            f"safe_write_text 调用次数不足: {safe_write_calls}（应 ≥ 2，rules + prompt）"
        )
    else:
        _ok(f"safe_write_text 调用 {safe_write_calls} 次（rules + prompt）")

    # 检查 import
    if "from core.utils.atomic_io import safe_write_text" not in src:
        issues.append("缺少 safe_write_text 导入")
    else:
        _ok("safe_write_text 导入存在")

    if not issues:
        _ok("原子写入使用验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_service_injects_core_memory() -> list[str]:
    issues: list[str] = []
    _section("测试 7：service.py 正确注入 CoreMemory 实例")

    src_file = PROJECT_ROOT / "core" / "services" / "self_improvement" / "service.py"
    src = src_file.read_text(encoding="utf-8")

    if "core_memory=self._core_memory" not in src:
        issues.append("service.py 未通过 core_memory= 参数注入 CoreMemory")
    else:
        _ok("service.py 通过 core_memory= 参数注入 CoreMemory")

    # 验证 LearningPromoter 构造函数接受 core_memory 参数
    from core.services.self_improvement.learning_promoter import LearningPromoter

    sig = inspect.signature(LearningPromoter.__init__)
    if "core_memory" not in sig.parameters:
        issues.append("LearningPromoter.__init__ 缺少 core_memory 参数")
    else:
        param = sig.parameters["core_memory"]
        if param.default is not None and param.default != inspect.Parameter.empty:
            # 默认值 None 是符合预期的
            pass
        _ok(f"LearningPromoter.__init__ 接受 core_memory 参数（默认 {param.default}）")

    if not issues:
        _ok("service.py 注入验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_full_promotion_flow() -> list[str]:
    issues: list[str] = []
    _section("测试 8：完整晋升流程（find_promotion_candidates → promote）")

    from core.services.self_improvement.learning_promoter import (
        LearningPromoter,
        PROMOTION_TARGET_RULES,
        PROMOTION_TARGET_PROMPT,
        PROMOTION_TARGET_MEMORY,
    )
    from core.services.self_improvement.core_memory import CoreMemory
    from core.services.self_improvement.models import (
        EntryPriority,
        EntryStatus,
        LearningCategory,
        LearningEntry,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rules_file = tmp_path / ".trae" / "rules" / "project_rules.md"
        prompt_file = tmp_path / "prompt_dir" / "promoted_rules.md"

        core_memory = CoreMemory(tmp_path, scope="user")
        core_memory.ensure_initialized()

        promoter = LearningPromoter(
            tmp_path, tmp_path, core_memory=core_memory
        )
        promoter._rules_file = rules_file
        promoter._prompt_rules_file = prompt_file

        # 构造达到晋升阈值的 learning
        learning = LearningEntry(
            category=LearningCategory.INSIGHT,
            priority=EntryPriority.HIGH,
            summary="测试学习：避免阻塞 IO",
            details="在 async 函数中调用阻塞 IO 会卡住事件循环",
            suggested_action="使用 asyncio.to_thread 包装阻塞调用",
            recurrence_count=5,
        )
        learning.status = EntryStatus.PENDING

        candidates = asyncio.run(
            promoter.find_promotion_candidates([learning], [])
        )

        if not candidates:
            issues.append("未找到晋升候选")
        else:
            candidate = candidates[0]
            target = candidate.get("target", "")
            if target not in (
                PROMOTION_TARGET_RULES,
                PROMOTION_TARGET_PROMPT,
                PROMOTION_TARGET_MEMORY,
            ):
                issues.append(f"未知晋升目标: {target}")
            else:
                _ok(f"找到候选，目标: {target}")

                success = asyncio.run(promoter.promote(candidate))
                if not success:
                    issues.append("promote 返回 False")
                else:
                    _ok("promote 返回 True")

                    # 验证 entry 状态更新
                    if learning.status != EntryStatus.PROMOTED:
                        issues.append(
                            f"entry 状态未更新: {learning.status}"
                        )
                    else:
                        _ok("entry 状态已更新为 PROMOTED")

                    # 验证文件被写入（具体哪个文件取决于 target）
                    written = False
                    if target == PROMOTION_TARGET_RULES and rules_file.exists():
                        written = True
                    if target == PROMOTION_TARGET_PROMPT and prompt_file.exists():
                        written = True
                    if target == PROMOTION_TARGET_MEMORY:
                        # 验证 MEMORY.md
                        from core.services.self_improvement.core_memory import MemorySection
                        items = asyncio.run(
                            core_memory.get_section(MemorySection.EXPERIENCE)
                        )
                        if items:
                            written = True

                    if not written:
                        issues.append(f"目标文件未被写入（target={target}）")
                    else:
                        _ok(f"目标文件已写入（target={target}）")

    if not issues:
        _ok("完整晋升流程验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_correction_grouping() -> list[str]:
    issues: list[str] = []
    _section("测试 9：相似纠正分组并晋升")

    from core.services.self_improvement.learning_promoter import LearningPromoter
    from core.services.self_improvement.models import (
        CorrectionEntry,
        EntryStatus,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rules_file = tmp_path / ".trae" / "rules" / "project_rules.md"

        promoter = LearningPromoter(tmp_path, tmp_path)
        promoter._rules_file = rules_file

        # 构造两条相似纠正
        c1 = CorrectionEntry(
            signal_type="direct_negation",
            title="不应该使用 exec() 执行用户输入",
            correction="禁止使用 exec() 处理动态代码",
            my_error="使用了 exec()",
            root_cause="未做安全校验",
            lesson="禁止使用 exec() 处理用户输入，应改用 ast.literal_eval",
            how_to_apply="在所有 exec() 调用点替换为安全实现",
            tags=["security", "exec"],
        )
        c2 = CorrectionEntry(
            signal_type="direct_negation",
            title="exec() 是危险的",
            correction="exec() 会被注入",
            my_error="调用 exec() 处理配置",
            root_cause="安全意识不足",
            lesson="禁止使用 exec() 处理用户输入",
            how_to_apply="代码审查时检查 exec() 调用",
            tags=["security", "exec"],
        )
        c1.status = EntryStatus.PENDING
        c2.status = EntryStatus.PENDING

        candidates = asyncio.run(
            promoter.find_promotion_candidates([], [c1, c2])
        )

        if not candidates:
            issues.append("相似纠正未被识别为候选")
        else:
            _ok(f"找到 {len(candidates)} 个纠正晋升候选")
            # 执行晋升
            for cand in candidates:
                asyncio.run(promoter.promote(cand))
            if rules_file.exists():
                content = rules_file.read_text(encoding="utf-8")
                if "exec()" in content or "禁止" in content:
                    _ok("纠正规则已写入 project_rules.md")
                else:
                    issues.append(f"纠正规则未正确写入: {content}")
            else:
                issues.append("project_rules.md 未创建")

    if not issues:
        _ok("相似纠正分组验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def main() -> int:
    print("\n" + "=" * 60)
    print("P2-7 验证：LearningPromoter 真正的晋升逻辑")
    print("=" * 60)

    all_issues: list[str] = []

    all_issues.extend(test_promote_to_rules_writes_file())
    all_issues.extend(test_promote_to_rules_dedup())
    all_issues.extend(test_promote_to_prompt_writes_file())
    all_issues.extend(test_promote_to_core_memory_writes())
    all_issues.extend(test_promote_to_core_memory_dedup())
    all_issues.extend(test_atomic_write_usage())
    all_issues.extend(test_service_injects_core_memory())
    all_issues.extend(test_full_promotion_flow())
    all_issues.extend(test_correction_grouping())

    print("\n" + "=" * 60)
    if all_issues:
        print(f"❌ 验证失败：发现 {len(all_issues)} 个问题")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("✅ 所有验证通过！P2-7 实现完整且正确。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
