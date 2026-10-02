# -*- coding: utf-8 -*-
"""peer_chat 后处理 hooks 测试（peer_script_hooks.py）。

覆盖 core/services/active_care/peer_chat/peer_script_hooks.py 的：
- run_peer_post_hooks：写日记 / 巡检 / 剧本落库 / mention 触发主动关怀
- _maybe_trigger_peer_chat_patrol：无异常短路、有异常触发巡检并写记忆
- build_patrol_persona：从人设配置拼巡检上下文 + 各种缺字段降级
- _write_patrol_report_to_memory：报告格式化与写记忆

为什么值得测：这些是"剧本发出去之后的副作用"。它们全部包在 try/except 里，
失败只打 warning —— 也就是说，写错了不会有任何显式报错，只表现为
"日记没写""主人没收到通知""巡检报告丢了"。属于典型的静默失效区。

设计要点：
- 全部外部服务用替身，不写真实记忆、不触发真实巡检；
- 断言集中在"该调的方法被调了 / 参数对不对 / 异常时是否被吞掉"。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.services.active_care.peer_chat import peer_script_hooks as hooks_mod
from core.services.active_care.peer_chat.peer_script_hooks import (
    build_patrol_persona,
    run_peer_post_hooks,
)


class _StubHost:
    """替身宿主：记录 write_diary_entry / trigger_message 调用。"""

    def __init__(self):
        self.diary: List[Dict[str, Any]] = []
        self.triggered: List[Dict[str, Any]] = []

    async def write_diary_entry(self, entry_type, title, thought=""):
        self.diary.append(
            {"entry_type": entry_type, "title": title, "thought": thought}
        )

    async def trigger_message(self, **kwargs):
        self.triggered.append(kwargs)


class _StubAvelineService:
    """替身 Aveline 服务：记录 append_proactive_message 调用。"""

    def __init__(self, fail=False):
        self.messages: List[Dict[str, Any]] = []
        self._fail = fail

    async def append_proactive_message(self, conversation_id, content, thought=""):
        if self._fail:
            raise RuntimeError("会话存储不可用")
        self.messages.append(
            {
                "conversation_id": conversation_id,
                "content": content,
                "thought": thought,
            }
        )


class _StubHealService:
    """替身巡检服务。"""

    def __init__(self, stats=None, results=None, fail=False):
        self._stats = stats or {}
        self._results = results if results is not None else []
        self._fail = fail
        self.check_calls: List[Dict[str, Any]] = []

    def get_stats(self):
        if self._fail:
            raise RuntimeError("巡检服务不可用")
        return dict(self._stats)

    async def trigger_check(self, persona_context=""):
        self.check_calls.append({"persona_context": persona_context})
        return list(self._results)


class _StubMemoryManager:
    """替身加权记忆管理器。"""

    def __init__(self, fail=False):
        self.entries: List[Dict[str, Any]] = []
        self._fail = fail

    def add_memory(self, **kwargs):
        if self._fail:
            raise RuntimeError("记忆写入失败")
        self.entries.append(kwargs)


CFG = {
    "role_name": "Aveline",
    "peer_name": "Ling",
    "role_persona_fn": "core_aveline.json",
    "peer_persona_fn": "core_ling.json",
    "master_qq_id": "10001",
}

SCRIPT = [
    {"role": "aveline", "content": "今天吃什么"},
    {"role": "ling", "content": "随便，你决定"},
]


def _patch_services(
    monkeypatch,
    *,
    aveline=None,
    heal=None,
    memory=None,
    metrics=None,
):
    """把 hooks 里所有延迟导入的外部服务替换为替身。"""
    import core.core_engine.service_singletons as singletons

    monkeypatch.setattr(
        singletons, "get_aveline_service", lambda: aveline or _StubAvelineService()
    )

    import core.services.auto_heal.heal_service as heal_mod

    monkeypatch.setattr(
        heal_mod,
        "get_auto_heal_service",
        lambda: heal if heal is not None else _StubHealService(),
    )

    import memory.weighted_memory_manager as wmm

    monkeypatch.setattr(
        wmm,
        "get_weighted_memory_manager",
        lambda scope: memory if memory is not None else _StubMemoryManager(),
    )

    if metrics is not None:
        import core.services.active_care.peer_chat.peer_chat_metrics as metrics_mod

        monkeypatch.setattr(
            metrics_mod, "get_peer_chat_metrics", lambda: metrics
        )


# ============================================================
# run_peer_post_hooks
# ============================================================

class TestRunPeerPostHooks:
    """后处理主流程。"""

    async def test_writes_diary_entry(self, monkeypatch):
        """总是先写一条普通日记，标题含轮数。"""
        _patch_services(monkeypatch)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="",
            host=host,
        )

        assert len(host.diary) == 1
        entry = host.diary[0]
        assert entry["entry_type"] == "peer_chat"
        assert entry["title"] == "和Ling聊了2轮"
        assert "主动找Ling聊天" in entry["thought"]

    async def test_diary_summary_uses_first_line_content(self, monkeypatch):
        """日记 thought 取剧本首句内容（截断 30 字）。"""
        _patch_services(monkeypatch)
        host = _StubHost()
        long_first = "第" * 50

        await run_peer_post_hooks(
            script=[{"role": "aveline", "content": long_first}],
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="",
            host=host,
        )

        thought = host.diary[0]["thought"]
        assert len(thought) <= len("主动找Ling聊天: ") + 30

    async def test_empty_script_diary_still_written(self, monkeypatch):
        """空剧本时日记仍要写（轮数 0），不能因无内容跳过。"""
        _patch_services(monkeypatch)
        host = _StubHost()

        await run_peer_post_hooks(
            script=[],
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="",
            host=host,
        )

        assert host.diary[0]["title"] == "和Ling聊了0轮"

    async def test_saves_script_lines_with_correct_labels(self, monkeypatch):
        """剧本逐句落库，说话人按 role_id 映射到中文名。"""
        aveline = _StubAvelineService()
        _patch_services(monkeypatch, aveline=aveline)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="",
            host=host,
        )

        assert len(aveline.messages) == 2
        assert aveline.messages[0]["content"] == "Aveline: 今天吃什么"
        assert aveline.messages[1]["content"] == "Ling: 随便，你决定"
        # 会话 id 用发起方角色
        assert aveline.messages[0]["conversation_id"] == "peer_aveline"

    async def test_empty_content_lines_are_skipped(self, monkeypatch):
        """空内容行不落库（不产生只有前缀的空消息）。"""
        aveline = _StubAvelineService()
        _patch_services(monkeypatch, aveline=aveline)
        host = _StubHost()

        await run_peer_post_hooks(
            script=[
                {"role": "aveline", "content": "有内容"},
                {"role": "ling", "content": ""},
            ],
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="",
            host=host,
        )

        assert len(aveline.messages) == 1

    async def test_script_save_failure_is_swallowed(self, monkeypatch):
        """落库失败只记 warning，不影响后续 mention 通知。"""
        aveline = _StubAvelineService(fail=True)
        _patch_services(monkeypatch, aveline=aveline)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=True,
            notify_content="记得吃药",
            host=host,
        )

        # 落库失败但通知仍触发了
        assert len(host.triggered) == 1

    async def test_no_notification_when_flag_false(self, monkeypatch):
        """should_notify_user=False 时不触发主动关怀。"""
        _patch_services(monkeypatch)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=False,
            notify_content="记得吃药",
            host=host,
        )

        assert host.triggered == []

    async def test_notification_payload(self, monkeypatch):
        """通知参数：类型、mock 输入、persona 文件名都要正确。"""
        _patch_services(monkeypatch)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=True,
            notify_content="记得吃药",
            host=host,
        )

        call = host.triggered[0]
        assert call["sys_prompt_type"] == "share_peer_chat"
        assert "记得吃药" in call["user_input_mock"]
        assert "和Ling聊了2轮" in call["user_input_mock"]
        assert call["persona_filename"] == "core_aveline.json"
        # 指令里必须包含"不要暴露私聊细节"的约束
        assert "不要暴露" in call["specific_instruction"]

    async def test_notification_increments_metric(self, monkeypatch):
        """通知触发时打点 mention_triggered。"""
        metrics = _StubMetrics()
        _patch_services(monkeypatch, metrics=metrics)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=True,
            notify_content="记得吃药",
            host=host,
        )

        assert metrics.counters.get("mention_triggered") == 1

    async def test_notification_failure_is_swallowed(self, monkeypatch):
        """通知失败只记 warning，不让异常冒泡。"""
        _patch_services(monkeypatch)
        host = _StubHost()

        async def _boom(**kwargs):
            raise RuntimeError("通知通道不可用")

        host.trigger_message = _boom

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=True,
            notify_content="记得吃药",
            host=host,
        )  # 不应抛异常

    async def test_metric_failure_does_not_block_notification(self, monkeypatch):
        """打点异常不能挡住通知（内层 try 单独兜）。"""
        metrics = _StubMetrics(fail=True)
        _patch_services(monkeypatch, metrics=metrics)
        host = _StubHost()

        await run_peer_post_hooks(
            script=SCRIPT,
            role_id="aveline",
            peer_role_id="ling",
            cfg=CFG,
            should_notify_user=True,
            notify_content="记得吃药",
            host=host,
        )

        assert len(host.triggered) == 1


class _StubMetrics:
    """替身指标器。"""

    def __init__(self, fail=False):
        self.counters: Dict[str, int] = {}
        self._fail = fail

    def incr(self, key, value=1):
        if self._fail:
            raise RuntimeError("打点失败")
        self.counters[key] = self.counters.get(key, 0) + value


# ============================================================
# _maybe_trigger_peer_chat_patrol
# ============================================================

class TestMaybeTriggerPatrol:
    """互聊后代码巡检。"""

    async def test_skips_when_service_missing(self, monkeypatch):
        """巡检服务不可用时直接返回。"""
        import core.services.auto_heal.heal_service as heal_mod

        monkeypatch.setattr(heal_mod, "get_auto_heal_service", lambda: None)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")
        # 无异常即通过

    async def test_skips_when_no_anomalies(self, monkeypatch):
        """无异常且无待审批时不触发巡检（避免每次互聊都跑一遍）。"""
        heal = _StubHealService(
            stats={"patches_by_status": {}, "error_stats": {"total_anomalies": 0}}
        )
        _patch_services(monkeypatch, heal=heal)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")

        assert heal.check_calls == []

    async def test_triggers_when_anomalies_exist(self, monkeypatch):
        """有异常时触发巡检，并传入角色上下文。"""
        heal = _StubHealService(
            stats={
                "patches_by_status": {},
                "error_stats": {"total_anomalies": 3},
            },
            results=[],
        )
        _patch_services(monkeypatch, heal=heal)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")

        assert len(heal.check_calls) == 1
        assert "Aveline" in heal.check_calls[0]["persona_context"]

    async def test_triggers_when_pending_approval_exists(self, monkeypatch):
        """有等待审批的补丁时也要触发（即使没有新异常）。"""
        heal = _StubHealService(
            stats={
                "patches_by_status": {"awaiting_approval": 2},
                "error_stats": {"total_anomalies": 0},
            },
            results=[],
        )
        _patch_services(monkeypatch, heal=heal)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")

        assert len(heal.check_calls) == 1

    async def test_writes_report_when_results_found(self, monkeypatch):
        """巡检有结果时写记忆。"""
        heal = _StubHealService(
            stats={"error_stats": {"total_anomalies": 1}},
            results=[
                {
                    "severity": "high",
                    "title": "空指针风险",
                    "auto_fixable": True,
                }
            ],
        )
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, heal=heal, memory=memory)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")

        assert len(memory.entries) == 1
        assert "Aveline做了一次代码巡检" in memory.entries[0]["content"]

    async def test_no_report_when_results_empty(self, monkeypatch):
        """巡检无新结果时不写记忆。"""
        heal = _StubHealService(
            stats={"error_stats": {"total_anomalies": 1}}, results=[]
        )
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, heal=heal, memory=memory)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")

        assert memory.entries == []

    async def test_service_exception_is_swallowed(self, monkeypatch):
        """巡检服务异常时被吞掉（互聊后处理不能拖垮主流程）。"""
        heal = _StubHealService(fail=True)
        _patch_services(monkeypatch, heal=heal)

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")
        # 无异常即通过

    async def test_service_exception_logs_when_debug_enabled(self, monkeypatch):
        """debug.peer_script 打开时，巡检触发失败要落日志便于排查。"""
        heal = _StubHealService(fail=True)
        _patch_services(monkeypatch, heal=heal)

        monkeypatch.setattr(hooks_mod, "is_debug_enabled", lambda key: True)
        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(hooks_mod, "logger", _Logger())

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")
        assert any("巡检触发失败" in str(args) for _, args in logged)

    async def test_report_write_failure_logs_when_debug_enabled(
        self, monkeypatch
    ):
        """debug.peer_script 打开时，巡检报告写入记忆失败要落日志。"""
        heal = _StubHealService(
            stats={"error_stats": {"total_anomalies": 1}},
            results=[
                {"severity": "high", "title": "空指针风险", "auto_fixable": True}
            ],
        )
        # 记忆写入必失败 → 命中 _write_patrol_report_to_memory 的 except
        _patch_services(monkeypatch, heal=heal, memory=_StubMemoryManager(fail=True))

        monkeypatch.setattr(hooks_mod, "is_debug_enabled", lambda key: True)
        logged = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    logged.append((name, args))

                return _record

        monkeypatch.setattr(hooks_mod, "logger", _Logger())

        await hooks_mod._maybe_trigger_peer_chat_patrol("aveline", "Aveline")
        assert any("巡检报告写入记忆失败" in str(args) for _, args in logged)


# ============================================================
# build_patrol_persona
# ============================================================

class TestBuildPatrolPersona:
    """巡检角色上下文构建。"""

    def test_uses_ling_persona_for_ling(self, monkeypatch):
        """ling 走 core_ling.json。"""
        captured = {}

        class _PM:
            def load_persona_config(self, filename):
                captured["filename"] = filename
                return {"system_prompt": "你是Ling。"}

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        result = build_patrol_persona("ling", "Ling")

        assert captured["filename"] == "core_ling.json"
        assert "你是Ling。" in result
        assert "代码巡检" in result

    def test_uses_aveline_persona_for_other_roles(self, monkeypatch):
        """非 ling 角色走 core_aveline.json。"""
        captured = {}

        class _PM:
            def load_persona_config(self, filename):
                captured["filename"] = filename
                return {"system_prompt": "你是Aveline。"}

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        build_patrol_persona("aveline", "Aveline")

        assert captured["filename"] == "core_aveline.json"

    def test_fallback_when_config_missing(self, monkeypatch):
        """人设配置读不到时给出最小上下文。"""

        class _PM:
            def load_persona_config(self, filename):
                return None

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        result = build_patrol_persona("aveline", "Aveline")

        assert result == "你的名字是Aveline。你现在在帮主人做代码巡检和审阅工作。"

    def test_builds_from_identity_when_no_system_prompt(self, monkeypatch):
        """无 system_prompt 时用 identity 的 cn_name + context 拼。"""

        class _PM:
            def load_persona_config(self, filename):
                return {
                    "identity": {
                        "cn_name": "Aveline",
                        "context": "你是Master创造的极客女友。",
                    }
                }

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        result = build_patrol_persona("aveline", "Aveline")

        assert "你的名字是Aveline。你是Master创造的极客女友。" in result

    def test_includes_traits_and_style(self, monkeypatch):
        """性格特征与说话风格按上限截取后拼入。"""

        class _PM:
            def load_persona_config(self, filename):
                return {
                    "identity": {
                        "cn_name": "Aveline",
                        "context": "上下文",
                        "personality_traits": ["a", "b", "c", "d", "e", "f", "g"],
                    },
                    "language_style": {
                        "syntax_constraints": ["s1", "s2", "s3", "s4"]
                    },
                }

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        result = build_patrol_persona("aveline", "Aveline")

        # 性格最多 5 个，风格最多 3 个
        assert "你的性格特征：a、b、c、d、e。" in result
        assert "你的说话风格：s1、s2、s3。" in result
        assert "f" not in result.split("你的说话风格")[0].split("你的性格特征")[1]
        assert "s4" not in result

    def test_falls_back_to_role_name_when_no_names(self, monkeypatch):
        """identity 里没有名字时用传入的 role_name。"""

        class _PM:
            def load_persona_config(self, filename):
                return {"identity": {"context": "某段上下文"}}

        import core.character.managers.persona_manager as pm_mod

        monkeypatch.setattr(pm_mod, "get_persona_manager", lambda: _PM())

        result = build_patrol_persona("aveline", "Aveline")

        assert "你的名字是Aveline。" in result

    def test_exception_returns_fallback(self, monkeypatch):
        """人设管理器异常时返回兜底文本。"""
        import core.character.managers.persona_manager as pm_mod

        def _boom():
            raise RuntimeError("人设管理器不可用")

        monkeypatch.setattr(pm_mod, "get_persona_manager", _boom)

        result = build_patrol_persona("aveline", "Aveline")

        assert result == "你的名字是Aveline。你现在在帮主人做代码巡检和审阅工作。"


# ============================================================
# _write_patrol_report_to_memory
# ============================================================

class TestWritePatrolReportToMemory:
    """巡检报告写记忆。"""

    async def test_writes_formatted_report(self, monkeypatch):
        """报告含角色名、异常数与逐条明细。"""
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, memory=memory)

        await hooks_mod._write_patrol_report_to_memory(
            "Aveline",
            [
                {"severity": "high", "title": "空指针风险", "auto_fixable": True},
                {"severity": "low", "title": "日志缺失", "auto_fixable": False},
            ],
        )

        assert len(memory.entries) == 1
        content = memory.entries[0]["content"]
        assert "Aveline做了一次代码巡检，发现 2 个异常" in content
        assert "[high] 空指针风险（可自动修复）" in content
        assert "[low] 日志缺失（需人工处理）" in content

    async def test_caps_at_five_items(self, monkeypatch):
        """明细最多取前 5 条（防记忆条目过长）。"""
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, memory=memory)

        results = [
            {"severity": "low", "title": f"问题{i}", "auto_fixable": False}
            for i in range(8)
        ]
        await hooks_mod._write_patrol_report_to_memory("Aveline", results)

        content = memory.entries[0]["content"]
        assert "问题0" in content
        assert "问题4" in content
        assert "问题5" not in content

    async def test_missing_fields_use_defaults(self, monkeypatch):
        """缺 severity / title 时用兜底文案。"""
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, memory=memory)

        await hooks_mod._write_patrol_report_to_memory("Aveline", [{}])

        content = memory.entries[0]["content"]
        assert "[unknown] 未知异常（需人工处理）" in content

    async def test_metadata_fields(self, monkeypatch):
        """写入记忆的元数据字段完整。"""
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, memory=memory)

        await hooks_mod._write_patrol_report_to_memory(
            "Aveline", [{"severity": "high", "title": "x", "auto_fixable": True}]
        )

        entry = memory.entries[0]
        assert entry["source"] == "patrol_report"
        assert entry["category"] == "auto_heal"
        assert entry["scopes"] == ["local"]
        assert entry["is_important"] is False
        assert entry["metadata"]["type"] == "patrol_report"
        assert entry["metadata"]["patrol_by"] == "Aveline"
        assert entry["metadata"]["anomaly_count"] == 1

    async def test_skips_when_manager_unavailable(self, monkeypatch):
        """记忆管理器不可用时静默跳过。"""
        import memory.weighted_memory_manager as wmm

        monkeypatch.setattr(wmm, "get_weighted_memory_manager", lambda scope: None)

        await hooks_mod._write_patrol_report_to_memory("Aveline", [{"title": "x"}])
        # 无异常即通过

    async def test_write_failure_is_swallowed(self, monkeypatch):
        """写记忆失败被吞掉（不影响主流程）。"""
        memory = _StubMemoryManager(fail=True)
        _patch_services(monkeypatch, memory=memory)

        await hooks_mod._write_patrol_report_to_memory("Aveline", [{"title": "x"}])
        # 无异常即通过

    async def test_empty_results_still_writes_summary(self, monkeypatch):
        """空结果也写一条（异常数 0），保持调用契约一致。"""
        memory = _StubMemoryManager()
        _patch_services(monkeypatch, memory=memory)

        await hooks_mod._write_patrol_report_to_memory("Aveline", [])

        assert "发现 0 个异常" in memory.entries[0]["content"]
