"""验证 nightly 记忆蒸馏批量改造。

改造前问题：
- distill_memories_async 对每条待蒸馏记忆单独发一次 LLM 请求（159 次请求/晚）。
- 每条 prompt 的 user 内容都不同，只有 system 前缀共享，命中率被摊薄到 ~40%。

改造后方案：
- 多条记忆合并为一次请求（默认每批 10 条），system 固定 + user 带编号消息列表。
- 请求数降为 ceil(N/10)，system 前缀跨批/跨用户固定，提升 DeepSeek prompt caching 命中。
- 短内容（<20 字符）直接落盘不消耗 LLM 请求；批量请求失败时回退逐条蒸馏。

本脚本不发送真实 LLM 请求，仅做静态结构与批量执行行为验证：
1. 批量 prompt 常量存在且结构正确（system 固定 / user 模板含 {count} {items}）
2. generate_batch_distillation_prompt 返回 [system, user] 双段，system 跨批一致
3. parse_batch_distillation_response 正常解析 / 乱序编号 / 缺失条目 / 空响应
4. distill_memories_async 分批执行：一次请求覆盖整批、短内容不调 LLM
5. 批量请求失败时回退逐条（_distill_one_async 仍工作）
6. config 默认值含 distillation_batch_size

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.nightly_prompt_cache.verify_batch_distillation
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ─────────────────────────────────────────────────────────
# 1. Prompt 常量结构验证
# ─────────────────────────────────────────────────────────

def test_batch_prompt_constants() -> None:
    """验证批量蒸馏 prompt 常量存在且结构正确"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_BATCH_USER_TEMPLATE,
        MEMORY_DISTILLATION_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_USER_TEMPLATE,
    )

    # 批量 system 非空且不含动态占位符（必须可跨批命中缓存）
    assert isinstance(MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT, str) and \
        MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT.strip()
    assert "{count}" not in MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT
    assert "{items}" not in MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT
    assert "{content}" not in MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT

    # 批量 user 模板必须含 {count} 和 {items} 占位符
    assert "{count}" in MEMORY_DISTILLATION_BATCH_USER_TEMPLATE
    assert "{items}" in MEMORY_DISTILLATION_BATCH_USER_TEMPLATE

    # 批量 system 与单条 system 不应完全相同（批量有逐条输出要求）
    assert MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT != MEMORY_DISTILLATION_SYSTEM_PROMPT
    # 单条模板仍保留（向后兼容）
    assert "{content}" in MEMORY_DISTILLATION_USER_TEMPLATE

    print("[OK] 批量蒸馏 prompt 常量结构正确（system 固定、user 含 {count}/{items}）")


def test_batch_prompt_messages_shape() -> None:
    """验证 generate_batch_distillation_prompt 返回 [system, user]，system 跨批一致"""
    from memory.nightly.task_runner import NightlyTaskRunner

    def _make_message(content: str) -> Dict[str, Any]:
        return {"id": f"msg_{content[:4]}", "content": content}

    batches = [
        [_make_message("用户今天聊了关于项目的进展 A"),
         _make_message("用户分享了周末出游的照片 B")],
        [_make_message("完全不同的对话内容 C"),
         _make_message("另外一组差异很大的内容 D")],
        [_make_message("第三条内容 E")],
    ]

    system_parts: List[str] = []
    for batch in batches:
        msgs = NightlyTaskRunner.generate_batch_distillation_prompt(batch)
        assert isinstance(msgs, list) and len(msgs) == 2
        assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
        system_parts.append(msgs[0]["content"])

        user_content: str = msgs[1]["content"]
        assert f"共 {len(batch)} 条" in user_content
        # 每条内容必须带【条目N】编号出现
        for index, message in enumerate(batch, start=1):
            assert f"【条目{index}】" in user_content
            assert message["content"] in user_content

    # system 跨批必须完全一致 → 可命中 DeepSeek 前缀缓存
    assert system_parts[0] == system_parts[1] == system_parts[2], \
        "批量蒸馏 system 必须跨批一致"

    print(f"[OK] generate_batch_distillation_prompt 返回 [system,user]，"
          f"system 跨 {len(batches)} 批一致 ({len(system_parts[0])} chars)")


# ─────────────────────────────────────────────────────────
# 2. 批量响应解析验证
# ─────────────────────────────────────────────────────────

def _make_response(pairs: List[Tuple[int, str]]) -> str:
    """构造批量响应：[(编号, 段内容), ...]"""
    parts = []
    for index, segment in pairs:
        parts.append(f"【条目{index}】\n{segment}")
    return "\n\n".join(parts)


def test_parse_batch_normal() -> None:
    """正常顺序响应解析"""
    from memory.nightly.task_runner import NightlyTaskRunner

    response = _make_response([
        (1, "【梗概】：讨论了项目排期\n【关键词】：项目,排期,进度"),
        (2, "【梗概】：聊了周末爬山\n【关键词】：爬山,周末,天气"),
    ])
    results = NightlyTaskRunner.parse_batch_distillation_response(response)

    assert set(results.keys()) == {1, 2}
    assert results[1][0] == "讨论了项目排期"
    assert "项目" in results[1][1]
    assert results[2][0] == "聊了周末爬山"
    assert "爬山" in results[2][1]

    print(f"[OK] 批量解析正常：{len(results)} 条全部提取成功")


def test_parse_batch_out_of_order() -> None:
    """乱序编号仍按编号归位（不依赖位置）"""
    from memory.nightly.task_runner import NightlyTaskRunner

    response = _make_response([
        (3, "【梗概】：第三条内容\n【关键词】：三,内容"),
        (1, "【梗概】：第一条内容\n【关键词】：一,内容"),
    ])
    results = NightlyTaskRunner.parse_batch_distillation_response(response)

    assert results[1][0] == "第一条内容"
    assert results[3][0] == "第三条内容"
    assert 2 not in results

    print("[OK] 乱序编号正确归位")


def test_parse_batch_missing_entry() -> None:
    """某条解析为空时跳过该条，不影响其他条目"""
    from memory.nightly.task_runner import NightlyTaskRunner

    response = _make_response([
        (1, "【梗概】：有效条目\n【关键词】：有效"),
        (2, "模型没有输出该条的有效格式内容"),
    ])
    results = NightlyTaskRunner.parse_batch_distillation_response(response)

    assert 1 in results
    assert 2 not in results, "解析失败条目应被跳过"

    print("[OK] 缺失/无效条目被跳过，有效条目保留")


def test_parse_batch_empty_or_garbage() -> None:
    """空响应 / 无【条目N】响应返回空字典"""
    from memory.nightly.task_runner import NightlyTaskRunner

    assert NightlyTaskRunner.parse_batch_distillation_response("") == {}
    assert NightlyTaskRunner.parse_batch_distillation_response("模型拒绝回答") == {}

    print("[OK] 空响应 / 无编号响应安全返回空字典")


# ─────────────────────────────────────────────────────────
# 3. distill_memories_async 分批执行验证
# ─────────────────────────────────────────────────────────

class _FakeScheduler:
    """模拟 scheduler.submit_llm_task，记录调用并返回配置好的响应。"""

    def __init__(self, responses: Optional[List[Any]] = None) -> None:
        self.responses: List[Any] = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def submit_llm_task(self, prompt: Any, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return _AsyncChunks(response)
        return _AsyncChunks("")


class _AsyncChunks:
    """把字符串包成 async generator，模拟流式 chunk。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        yield self._text


class _FakeManager:
    """模拟记忆管理器，记录 update_memory_distillation 调用。"""

    def __init__(self, memory: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.memory: Dict[str, Dict[str, Any]] = dict(memory or {})
        self.updates: List[Dict[str, Any]] = []

    @property
    def lock(self) -> MagicMock:
        return MagicMock()

    @property
    def weighted_memories(self) -> Dict[str, Dict[str, Any]]:
        return self.memory

    def update_memory_distillation(
        self,
        msg_id: str,
        summary: str,
        keywords: List[str],
        distillation_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self.updates.append(
            {
                "id": msg_id,
                "summary": summary,
                "keywords": keywords,
                "distillation_metadata": distillation_metadata,
            }
        )
        return True


def _make_memories(count: int, content_len: int = 60) -> Dict[str, Dict[str, Any]]:
    """构造 count 条待蒸馏记忆，content 长度满足 ≥20 字符阈值。"""
    # timestamp 用 2 小时前：早于 1h 蒸馏阈值（进入队列）且晚于 24h 窗口（不被丢弃）。
    # 注意不能贴边界（如 1h 整），否则与 threshold_ts 浮点相等时会因 ULP 舍入被偶发跳过。
    ts = time.time() - 7200
    memories = {}
    for i in range(count):
        memories[f"m{i}"] = {
            "id": f"m{i}",
            "content": f"用户聊了测试内容{i}" + "详细描述。" * content_len,
            "timestamp": ts,
            "is_distilled": False,
        }
    return memories


def _run_distill(config: Dict[str, Any], manager: Any, scheduler: Any) -> int:
    """在打桩 get_global_scheduler 的前提下运行 distill_memories_async。"""
    from memory.nightly.task_runner import NightlyTaskRunner

    runner = NightlyTaskRunner(config)
    with patch(
        "memory.nightly.task_runner.get_global_scheduler",
        return_value=scheduler,
    ):
        return asyncio.run(runner.distill_memories_async("user_a", manager))


def test_distill_batched_request_count() -> None:
    """10 条记忆应合并为 1 次请求（batch_size=10）"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    batch_response = "\n\n".join(
        f"【条目{i}】\n【梗概】：摘要内容{i}\n【关键词】：关键词{i}"
        for i in range(1, 11)
    )
    scheduler = _FakeScheduler([batch_response])
    manager = _FakeManager(_make_memories(10))

    _run_distill(DEFAULT_NIGHTLY_CONFIG, manager, scheduler)

    assert len(scheduler.calls) == 1, f"10 条记忆应合并为 1 次请求，实际 {len(scheduler.calls)} 次"
    # 请求应使用批量 prompt（system 固定）
    sys_content = scheduler.calls[0]["prompt"][0]["content"]
    assert "【条目" in sys_content or "逐条" in sys_content

    # 10 条全部更新成功
    assert len(manager.updates) == 10, f"应更新 10 条记忆，实际 {len(manager.updates)}"
    assert manager.updates[0]["summary"] == "摘要内容1"
    assert manager.updates[9]["summary"] == "摘要内容10"

    print("[OK] 10 条记忆合并为 1 次请求（改造前为 10 次），10 条全部更新")


def test_distill_small_batches() -> None:
    """25 条记忆按 batch_size=10 拆 3 批，3 次请求"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    responses = []
    for _ in range(3):
        responses.append("\n\n".join(
            f"【条目{i}】\n【梗概】：摘要{i}\n【关键词】：kw{i}"
            for i in range(1, 11)
        ))

    scheduler = _FakeScheduler(responses)
    manager = _FakeManager(_make_memories(25))

    _run_distill(DEFAULT_NIGHTLY_CONFIG, manager, scheduler)

    assert len(scheduler.calls) == 3, f"25 条应拆 3 批共 3 次请求，实际 {len(scheduler.calls)}"
    assert len(manager.updates) == 25

    print(f"[OK] 25 条记忆拆 3 批共 {len(scheduler.calls)} 次请求，25 条全部更新")


def test_distill_short_content_no_llm() -> None:
    """短内容（<20 字符）直接落盘，不发起 LLM 请求"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    ts = time.time() - 7200
    memories = {
        "short1": {"id": "short1", "content": "好", "timestamp": ts, "is_distilled": False},
        "short2": {"id": "short2", "content": "晚安", "timestamp": ts, "is_distilled": False},
    }
    scheduler = _FakeScheduler([])  # 无 LLM 响应
    manager = _FakeManager(memories)

    count = _run_distill(DEFAULT_NIGHTLY_CONFIG, manager, scheduler)

    assert len(scheduler.calls) == 0, "短内容不应发起 LLM 请求"
    assert len(manager.updates) == 2
    assert count == 2

    print("[OK] 短内容直接落盘，0 次 LLM 请求")


def test_distill_batch_failure_fallback() -> None:
    """批量请求抛异常时回退逐条蒸馏"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    memories = _make_memories(5)
    # 批量请求抛异常 → 触发回退；回退时每条再发一次请求
    scheduler = _FakeScheduler([RuntimeError("批量请求失败")])
    manager = _FakeManager(memories)

    count = _run_distill(DEFAULT_NIGHTLY_CONFIG, manager, scheduler)

    # 批量 1 次 + 回退 5 次
    assert len(scheduler.calls) == 6, f"应批量1次+回退5次共6次请求，实际 {len(scheduler.calls)}"
    # 回退后单条响应为空 → summary 为空 → 不更新（符合旧逻辑）
    assert len(manager.updates) == 0
    assert count == 0

    print(f"[OK] 批量失败回退逐条（共 {len(scheduler.calls)} 次请求），行为符合预期")


def test_group_by_time_gap() -> None:
    """按时间间隔分组：间隔超过 gap 拆开，组内升序"""
    from memory.nightly.task_runner import NightlyTaskRunner

    base = time.time() - 7200
    messages = [
        {"id": "a", "content": "第一段消息1", "timestamp": base},
        {"id": "b", "content": "第一段消息2", "timestamp": base + 60},        # 间隔 1min
        {"id": "c", "content": "第二段消息1", "timestamp": base + 3600},     # 间隔 ~59min > 30min
        {"id": "d", "content": "第二段消息2", "timestamp": base + 3600 + 120},  # 间隔 2min
    ]
    # 乱序输入，验证内部排序
    groups = NightlyTaskRunner.group_memories_by_time(
        [messages[3], messages[0], messages[2], messages[1]],
        gap_seconds=1800,  # 30 分钟
        max_group_size=100,
    )

    assert len(groups) == 2, f"应拆为 2 组，实际 {len(groups)}"
    assert [m["id"] for m in groups[0]] == ["a", "b"]
    assert [m["id"] for m in groups[1]] == ["c", "d"]

    print("[OK] 间隔超过 30 分钟拆分为 2 组，组内按时间升序")


def test_group_by_time_max_size() -> None:
    """组内超过 max_group_size 再切分"""
    from memory.nightly.task_runner import NightlyTaskRunner

    base = time.time() - 7200
    messages = [
        {"id": f"m{i}", "content": f"连续消息{i}", "timestamp": base + i * 10}
        for i in range(25)  # 全在 10s 间隔内，时间上连续
    ]
    groups = NightlyTaskRunner.group_memories_by_time(messages, gap_seconds=1800, max_group_size=10)

    assert len(groups) == 3, f"25 条连续消息按 10 条上限应拆 3 组，实际 {len(groups)}"
    assert [len(g) for g in groups] == [10, 10, 5]

    print("[OK] 组内超过 10 条再切分：[10, 10, 5]")


def test_distill_grouped_by_time() -> None:
    """distill_memories_async 按时间分组：两段对话各 1 次请求"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    base = time.time() - 10800  # 3 小时前：两段对话都早于 1h 阈值、晚于 24h 窗口
    memories = {}
    for i in range(5):
        memories[f"s1_{i}"] = {
            "id": f"s1_{i}", "content": f"第一段对话内容{i}描述描述描述描述描述描述描述描述",
            "timestamp": base + i * 60, "is_distilled": False,
        }
    for i in range(5):
        memories[f"s2_{i}"] = {
            "id": f"s2_{i}", "content": f"第二段对话内容{i}描述描述描述描述描述描述描述描述",
            "timestamp": base + 3600 + i * 60, "is_distilled": False,
        }

    responses = []
    for seg in ("第一段摘要", "第二段摘要"):
        responses.append("\n\n".join(
            f"【条目{i}】\n【梗概】：{seg}{i}\n【关键词】：kw{i}"
            for i in range(1, 6)
        ))
    scheduler = _FakeScheduler(responses)
    manager = _FakeManager(memories)

    _run_distill(DEFAULT_NIGHTLY_CONFIG, manager, scheduler)

    assert len(scheduler.calls) == 2, f"两段对话应各 1 次请求，实际 {len(scheduler.calls)}"
    assert len(manager.updates) == 10
    # 第一段更新为第一段摘要
    assert manager.updates[0]["summary"] == "第一段摘要1"

    print("[OK] 按时间分组的对话段各合并为 1 次请求（共 2 次），10 条全部更新")


def test_config_group_gap_default() -> None:
    """config 默认值包含 distillation_group_gap_minutes"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    assert DEFAULT_NIGHTLY_CONFIG.get("distillation_group_gap_minutes") == 30

    print("[OK] DEFAULT_NIGHTLY_CONFIG 含 distillation_group_gap_minutes=30")


def test_config_batch_size_default() -> None:
    """config 默认值包含 distillation_batch_size"""
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    assert DEFAULT_NIGHTLY_CONFIG.get("distillation_batch_size") == 10

    print("[OK] DEFAULT_NIGHTLY_CONFIG 含 distillation_batch_size=10")


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────

def main() -> None:
    tests = [
        test_batch_prompt_constants,
        test_batch_prompt_messages_shape,
        test_parse_batch_normal,
        test_parse_batch_out_of_order,
        test_parse_batch_missing_entry,
        test_parse_batch_empty_or_garbage,
        test_distill_batched_request_count,
        test_distill_small_batches,
        test_distill_short_content_no_llm,
        test_distill_batch_failure_fallback,
        test_group_by_time_gap,
        test_group_by_time_max_size,
        test_distill_grouped_by_time,
        test_config_group_gap_default,
        test_config_batch_size_default,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {test.__name__}: {exc}")
    print(f"\n共 {len(tests)} 个用例，通过 {passed} 个")
    if passed != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    main()
