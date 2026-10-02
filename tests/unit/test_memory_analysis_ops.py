"""``memory.core.analysis_ops`` 单元测试。

设计要点：
- 全部使用纯替身对象（``_FakeManager`` 等）驱动被测函数，不加载真实记忆后端、
  不落盘、不联网、不调用真实 BERT/LLM，因此可稳定复跑。
- ``_run_bert_shadow_analysis`` 内部是延迟导入 ``core.services.data_ops.bert_analyzer``；
  真实导入该模块需 10s+ 且会读本机配置，故这里向 ``sys.modules`` 注入假模块来拦截。
- 时钟：涉及 ``time.time()`` 的路径只断言字段被正确写入，绝不断言真实流逝时间。
- 落盘全部发生在替身对象的内存字典上，不触碰项目真实记忆目录。
"""

from __future__ import annotations

import sys
import threading
import types
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import memory.core.analysis_ops as analysis_ops
from memory.core.analysis_ops import (
    DEFAULT_FUSION_CONFIG,
    FusionConfig,
    FusionResult,
    _apply_fusion_action,
    _apply_pending_analysis_result,
    _assess_risk_level,
    _build_ai_shadow_dict,
    _build_bert_shadow_input,
    _clean_category,
    _clean_topics,
    _compute_consistency_score,
    _compute_final_confidence,
    _compute_rule_score,
    _compute_stability_score,
    _compute_trigger_decision,
    _ensure_analysis_meta,
    _prepare_pending_analysis,
    _run_bert_shadow_analysis,
    _safe_float,
    _write_fusion_metadata,
    apply_ai_shadow_adjudication,
    attach_ai_shadow_result,
    count_ai_shadow_results,
    count_pending_analysis,
    get_pending_analysis_items,
    process_pending_analysis,
)


# ---------------------------------------------------------------------------
# 替身对象
# ---------------------------------------------------------------------------

class _FakeRWLock:
    """记录读/写锁获取次数的读写锁替身。"""

    def __init__(self):
        self.reads = 0
        self.writes = 0

    @contextmanager
    def read_lock(self):
        self.reads += 1
        yield

    @contextmanager
    def write_lock(self):
        self.writes += 1
        yield


class _FakeWeightCalculator:
    """记录 ``calculate_initial_weight`` 入参并返回固定权重的替身。"""

    def __init__(self, weight=1.0):
        self.weight = weight
        self.calls = []

    def calculate_initial_weight(self, content, is_important, topics, emotions):
        self.calls.append(
            {
                "content": content,
                "is_important": is_important,
                "topics": list(topics),
                "emotions": list(emotions),
            }
        )
        return self.weight


class _FakeAnalyzer:
    """记录 ``analyze`` 入参并返回固定结果的 BERT 分析器替身。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def analyze(self, text):
        self.calls.append(text)
        return self.result


class _ScriptedDict(dict):
    """按调用次序为指定 key 返回不同值的字典替身。

    用于覆盖"第一遍迭代能看到、第二遍 ``.get`` 拿到替身/非 dict"的防御分支。
    """

    def __init__(self, mapping, sequence):
        super().__init__(mapping)
        self._sequence = {k: list(v) for k, v in sequence.items()}
        self._index = {k: 0 for k in sequence}

    def get(self, key, default=None):
        seq = self._sequence.get(key)
        if seq:
            i = self._index[key]
            value = seq[min(i, len(seq) - 1)]
            self._index[key] = i + 1
            return value
        return super().get(key, default)


class _FakeManager:
    """记忆管理器替身：只暴露 analysis_ops 会触碰的属性与方法。"""

    def __init__(
        self,
        weighted=None,
        *,
        use_rw_lock=False,
        pending_count=None,
        ai_shadow_count=None,
        topics=None,
        category="uncategorized",
        emotion="neutral",
        keywords=None,
        weight=1.0,
        normalize=None,
    ):
        self.lock = threading.RLock()
        self._use_rw_lock = use_rw_lock
        if use_rw_lock:
            self._rw_lock = _FakeRWLock()
        self.weighted_memories = weighted if weighted is not None else {}
        if pending_count is not None:
            self._pending_analysis_count = pending_count
        if ai_shadow_count is not None:
            self._ai_shadow_count = ai_shadow_count
        self.category_index = defaultdict(list)
        self.topic_weights = defaultdict(float)
        self.emotion_memory_map = defaultdict(list)
        self.weight_calculator = _FakeWeightCalculator(weight)
        self._topics = list(topics or [])
        self._category = category
        self._emotion = emotion
        self._keywords = list(keywords or [])
        self._normalize = normalize
        self.keyword_dirty = []
        self.save_count = 0
        self.last_modified_time = 0.0

    # --- 规则分析依赖 ---
    def _detect_topics(self, content):
        return list(self._topics)

    def _classify_category(self, content):
        return self._category

    def _detect_emotion(self, content):
        return self._emotion

    def _extract_keywords(self, content):
        return set(self._keywords)

    def _normalize_memory_record(self, candidate):
        if self._normalize is not None:
            return self._normalize(candidate)
        return dict(candidate), {}

    # --- 索引/落盘钩子 ---
    def _mark_keyword_index_dirty_locked(self, memory_id):
        self.keyword_dirty.append(memory_id)

    def _schedule_save(self):
        self.save_count += 1


def _install_fake_bert(monkeypatch, result):
    """向 ``sys.modules`` 注入假的 bert_analyzer 模块，返回分析器替身。"""
    analyzer = _FakeAnalyzer(result)
    fake_module = types.ModuleType("core.services.data_ops.bert_analyzer")
    fake_module.get_bert_analyzer = lambda: analyzer
    monkeypatch.setitem(sys.modules, "core.services.data_ops.bert_analyzer", fake_module)
    return analyzer


def _make_memory(
    mid,
    *,
    topics=None,
    category="uncategorized",
    weight=1.0,
    memory_type="dialogue",
    ai_shadow=None,
    analysis_meta=None,
    content=None,
):
    """构造一条 weighted_memories 记录。"""
    metadata = {}
    if ai_shadow is not None:
        metadata["ai_shadow"] = ai_shadow
    if analysis_meta is not None:
        metadata["analysis_meta"] = analysis_meta
    return {
        "content": content if content is not None else f"content-{mid}",
        "topics": list(topics or []),
        "category": category,
        "weight": weight,
        "memory_type": memory_type,
        "metadata": metadata,
    }


def _make_prep(**overrides):
    """构造 ``_apply_pending_analysis_result`` 需要的 prep 字典。"""
    prep = {
        "skip": False,
        "memory_id": "m1",
        "empty_content": False,
        "content": "今天吃了饭",
        "old_category": "uncategorized",
        "topics": ["a"],
        "category": "food",
        "discourse": {"trigger_blocked": False, "contains_negation": False},
        "discourse_label": "GENERIC_CHAT",
        "emotions": ["happy"],
        "weight": 1.5,
        "search_keywords": ["k1"],
        "display_tags": ["d1"],
        "bert_input_text": "原文：今天吃了饭",
        "now_ts": 111.0,
    }
    prep.update(overrides)
    return prep


# ---------------------------------------------------------------------------
# 纯工具函数
# ---------------------------------------------------------------------------

def test_ensure_analysis_meta_creates_and_reuses():
    """缺失或类型错误时新建 dict，已存在时原样复用。"""
    metadata = {}
    created = _ensure_analysis_meta(metadata)
    assert created == {}
    assert metadata["analysis_meta"] is created

    metadata["analysis_meta"] = "not-a-dict"
    replaced = _ensure_analysis_meta(metadata)
    assert replaced == {}
    assert metadata["analysis_meta"] is replaced

    existing = {"state": "x"}
    metadata["analysis_meta"] = existing
    assert _ensure_analysis_meta(metadata) is existing


def test_safe_float_clamps_and_defaults():
    """数值裁剪到区间；不可转换时回退默认值。"""
    assert _safe_float(0.5) == 0.5
    assert _safe_float(2.0) == 1.0
    assert _safe_float(-1.0) == 0.0
    assert _safe_float("0.25") == 0.25
    assert _safe_float(5.0, 0.0, -2.0, 2.0) == 2.0
    assert _safe_float("bad", 0.7) == 0.7
    assert _safe_float(None, 0.3, -2.0, 2.0) == 0.3


def test_clean_topics_dedup_strip_limit():
    """去空、去重、保序、截断。"""
    assert _clean_topics(None) == []
    assert _clean_topics([]) == []
    assert _clean_topics([" a ", "a", "  ", "b", "c"], limit=2) == ["a", "b"]
    assert _clean_topics(["t1", "t2"], limit=8) == ["t1", "t2"]


def test_clean_category_defaults():
    """空值/空白统一回退为 uncategorized，正常值去空格。"""
    assert _clean_category(None) == "uncategorized"
    assert _clean_category("   ") == "uncategorized"
    assert _clean_category(" food ") == "food"


def test_build_ai_shadow_dict_fields():
    """字段截断与延迟取整符合约定。"""
    result = _build_ai_shadow_dict(
        topics=["t1", "t2"],
        category="food",
        confidence=0.8,
        weight_delta=0.5,
        discourse_label="QUESTION",
        state_event="MEAL_NOW",
        trigger_allowed=True,
        reason="x" * 300,
        source="llm",
        status="ok",
        latency_ms=12.345,
        updated_at=99.0,
    )
    assert result["topics"] == ["t1", "t2"]
    assert result["bert_topics"] == ["t1", "t2"]
    assert result["bert_category"] == "food"
    assert result["discourse_label"] == "QUESTION"
    assert result["state_event"] == "MEAL_NOW"
    assert result["trigger_allowed"] is True
    assert len(result["reason"]) == 256
    assert result["latency_ms"] == 12.35
    assert result["updated_at"] == 99.0
    assert result["version"] == "s_ai_shadow_v1"


def test_build_bert_shadow_input_full_and_minimal():
    """归一化结果字段齐全时拼出全部段落；缺失时只保留原文段落。"""

    def normalize_full(candidate):
        return (
            {
                "readable_title": "标题A",
                "readable_summary": "摘要B",
                "category": "food",
                "topics": ["t1", "t2"],
            },
            {},
        )

    manager = _FakeManager(normalize=normalize_full)
    text = _build_bert_shadow_input(
        manager,
        content=" 原文内容 ",
        category="food",
        topics=["t1", "t2"],
        weight=2.0,
        memory={"content": "x"},
    )
    assert "标题：标题A" in text
    assert "摘要：摘要B" in text
    assert "规则分类：food" in text
    assert "规则主题：t1、t2" in text
    assert text.endswith("原文：原文内容")

    def normalize_min(candidate):
        return ({"readable_title": "", "readable_summary": "", "category": "", "topics": []}, {})

    manager_min = _FakeManager(normalize=normalize_min)
    text_min = _build_bert_shadow_input(
        manager_min,
        content="仅原文",
        category="",
        topics=[],
        weight=0.0,
        memory={},
    )
    assert text_min == "原文：仅原文"


# ---------------------------------------------------------------------------
# BERT 影子分析
# ---------------------------------------------------------------------------

def test_run_bert_shadow_analysis_ok(monkeypatch):
    """正常结果：字段被清洗，status=ok，延迟为有限值。"""
    analyzer = _install_fake_bert(
        monkeypatch,
        {
            "topics": [" t1 ", "t1", "t2"],
            "category": " food ",
            "confidence": 1.5,
            "weight_delta": -3.0,
            "discourse_label": " QUESTION ",
            "state_event": " MEAL_NOW ",
            "source": "bert_local",
            "reason": "done",
            "trigger_allowed": True,
        },
    )
    result = _run_bert_shadow_analysis("输入文本")
    assert analyzer.calls == ["输入文本"]
    assert result["topics"] == ["t1", "t2"]
    assert result["category"] == "food"
    assert result["confidence"] == 1.0
    assert result["weight_delta"] == -2.0
    assert result["discourse_label"] == "QUESTION"
    assert result["state_event"] == "MEAL_NOW"
    assert result["status"] == "ok"
    assert result["reason"] == "done"
    assert result["input_text"] == "输入文本"
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0.0


def test_run_bert_shadow_analysis_skipped_reason(monkeypatch):
    """命中跳过原因集合时 status=skipped。"""
    _install_fake_bert(monkeypatch, {"reason": "bert_model_not_loaded"})
    result = _run_bert_shadow_analysis("文本")
    assert result["status"] == "skipped"
    assert result["reason"] == "bert_model_not_loaded"
    assert result["category"] == "uncategorized"


def test_run_bert_shadow_analysis_non_dict_result(monkeypatch):
    """分析器返回非 dict 时按空结果处理。"""
    _install_fake_bert(monkeypatch, None)
    result = _run_bert_shadow_analysis("文本")
    assert result["topics"] == []
    assert result["category"] == "uncategorized"
    assert result["confidence"] == 0.0
    assert result["reason"] == "bert_shadow"
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# 待分析计数 / 取待分析项
# ---------------------------------------------------------------------------

def test_count_pending_analysis_counter_and_scan():
    """有 O(1) 计数器时直接返回；否则遍历 metadata 统计。"""
    assert count_pending_analysis(_FakeManager(pending_count=5)) == 5

    weighted = {
        "m1": {"metadata": {"analysis_pending": True}},
        "m2": {"metadata": {"analysis_pending": True}},
        "m3": {"metadata": {"analysis_pending": False}},
        "m4": {"metadata": "not-a-dict"},
    }
    manager = _FakeManager(weighted, use_rw_lock=True)
    assert count_pending_analysis(manager) == 2
    assert manager._rw_lock.reads == 1


def test_get_pending_analysis_items_filters_sorts_limits():
    """只保留 pending 项，按时间戳升序，并截断到 limit。"""
    weighted = {
        "late": {
            "content": "c-late",
            "topics": ["t"],
            "category": "food",
            "weight": 3,
            "timestamp": 30.0,
            "metadata": {"analysis_pending": True},
        },
        "early": {
            "content": "c-early",
            "topics": ["t"],
            "category": "food",
            "weight": 1,
            "timestamp": 10.0,
            "metadata": {"analysis_pending": True},
        },
        "skip": {"content": "c", "timestamp": 5.0, "metadata": {"analysis_pending": False}},
        "bad_meta": {"content": "c", "timestamp": 1.0, "metadata": None},
    }
    manager = _FakeManager(weighted)
    items = get_pending_analysis_items(manager, limit=1)
    assert [item["memory_id"] for item in items] == ["early"]
    assert items[0]["content"] == "c-early"
    assert items[0]["rule_topics"] == ["t"]
    assert items[0]["rule_category"] == "food"
    assert items[0]["rule_weight"] == 1.0

    both = get_pending_analysis_items(manager, limit=0)
    assert [item["memory_id"] for item in both] == ["early"]


# ---------------------------------------------------------------------------
# attach_ai_shadow_result / count_ai_shadow_results
# ---------------------------------------------------------------------------

def test_attach_ai_shadow_result_missing_memory():
    """目标记忆不存在或非 dict 时返回 False。"""
    manager = _FakeManager({"m1": "not-a-dict"})
    assert attach_ai_shadow_result(
        manager, "m1", ai_topics=["t"], ai_category="food", ai_confidence=0.5
    ) is False
    assert manager.save_count == 0


def test_attach_ai_shadow_result_new_and_counter():
    """首次写入 ai_shadow 时递增计数器并写入 analysis_meta。"""
    memory = {"metadata": {}, "weight": 1.0}
    manager = _FakeManager({"m1": memory}, ai_shadow_count=0)
    ok = attach_ai_shadow_result(
        manager,
        "m1",
        ai_topics=["t1", "t2"],
        ai_category="food",
        ai_confidence=1.5,
        ai_weight_delta=-3.0,
        ai_discourse_label="",
        ai_state_event="",
        ai_trigger_allowed=True,
        ai_reason="r",
        latency_ms=1.234,
    )
    assert ok is True
    assert manager._ai_shadow_count == 1
    metadata = memory["metadata"]
    shadow = metadata["ai_shadow"]
    assert shadow["topics"] == ["t1", "t2"]
    assert shadow["category"] == "food"
    assert shadow["confidence"] == 1.0
    assert shadow["weight_delta"] == -2.0
    assert shadow["discourse_label"] == "GENERIC_CHAT"
    assert shadow["state_event"] == "NONE"
    assert shadow["trigger_allowed"] is True
    assert shadow["latency_ms"] == 1.23
    assert shadow["history"] == []
    assert metadata["analysis_meta"]["ai_shadow"] is shadow
    assert metadata["analysis_meta"]["state"] == "ai_shadow_done"
    assert metadata["analysis_meta"]["updated_at"] == shadow["updated_at"]
    assert manager.keyword_dirty == ["m1"]
    assert manager.last_modified_time == shadow["updated_at"]
    assert manager.save_count == 1


def test_attach_ai_shadow_result_history_rotation():
    """已存在 ai_shadow 时把上一版压入 history，并只保留最近 3 条。"""
    prev = {
        "topics": ["old"],
        "category": "food",
        "confidence": 0.4,
        "history": [
            {"topics": ["h1"], "category": "c", "confidence": 0.1},
            {"topics": ["h2"], "category": "c", "confidence": 0.2},
            {"topics": ["h3"], "category": "c", "confidence": 0.3},
        ],
    }
    memory = {"metadata": {"ai_shadow": prev}, "weight": 1.0}
    manager = _FakeManager({"m1": memory}, ai_shadow_count=0)
    assert attach_ai_shadow_result(
        manager, "m1", ai_topics=["new"], ai_category="drink", ai_confidence=0.9
    ) is True
    # 已有 ai_shadow -> 不再递增计数器
    assert manager._ai_shadow_count == 0
    history = memory["metadata"]["ai_shadow"]["history"]
    assert len(history) == 3
    assert history[0]["topics"] == ["h2"]
    assert history[1]["topics"] == ["h3"]
    assert history[2] == {"topics": ["old"], "category": "food", "confidence": 0.4}


def test_attach_ai_shadow_result_non_dict_metadata():
    """metadata 非 dict 时被替换为新的 dict，仍能成功写入。"""
    memory = {"metadata": None}
    manager = _FakeManager({"m1": memory})
    assert attach_ai_shadow_result(
        manager, "m1", ai_topics=[], ai_category="", ai_confidence=0.0
    ) is True
    assert memory["metadata"]["ai_shadow"]["category"] == "uncategorized"
    assert manager.save_count == 1


def test_count_ai_shadow_results_counter_and_scan():
    """有计数器时直接返回；否则遍历统计 dict 形态的 ai_shadow。"""
    assert count_ai_shadow_results(_FakeManager(ai_shadow_count=7)) == 7

    weighted = {
        "m1": {"metadata": {"ai_shadow": {"a": 1}}},
        "m2": {"metadata": {"ai_shadow": "not-a-dict"}},
        "m3": {"metadata": "not-a-dict"},
        "m4": {"metadata": {}},
    }
    manager = _FakeManager(weighted, use_rw_lock=True)
    assert count_ai_shadow_results(manager) == 1
    assert manager._rw_lock.reads == 1


# ---------------------------------------------------------------------------
# 打分函数
# ---------------------------------------------------------------------------

def test_compute_rule_score():
    """主题数强度 + 分类强度按权重加和。"""
    assert _compute_rule_score([], "uncategorized") == 0.0
    assert _compute_rule_score([f"t{i}" for i in range(8)], "food") == 1.0
    assert _compute_rule_score(["t1", "t2", "t3", "t4"], "food") == 0.7


def test_compute_consistency_score_empty_and_partial():
    """空主题集一致性视为 1.0；部分重合按 Jaccard 计算。"""
    full = _compute_consistency_score([], [], "food", "food", "GENERIC_CHAT", "GENERIC_CHAT")
    assert full == 1.0

    partial = _compute_consistency_score(
        ["a", "b"], ["b", "c"], "food", "drink", "GENERIC_CHAT", "QUESTION"
    )
    assert partial == round(DEFAULT_FUSION_CONFIG.consistency_topic / 3.0, 4)


def test_compute_stability_score():
    """无历史给 0.7；有历史按完全一致占比计算。"""
    assert _compute_stability_score(["a"], "food", []) == 0.7
    history = [
        {"topics": ["a"], "category": "food"},
        {"topics": ["b"], "category": "food"},
        {"topics": None, "category": None},
    ]
    assert _compute_stability_score(["a"], "food", history) == round(1.0 / 3.0, 4)


def test_compute_final_confidence():
    """四项加权求和并裁剪到 [0,1]。"""
    assert _compute_final_confidence(1.0, 1.0, 1.0, 1.0) == 1.0
    assert _compute_final_confidence(0.0, 0.0, 0.0, 0.0) == 0.0
    assert _compute_final_confidence(1.0, 0.0, 0.0, 0.0) == 0.4


def test_compute_trigger_decision_all_branches():
    """覆盖 deny / allow / manual_review 三条分支。"""
    # 规则被屏蔽 -> deny，且规则信号归零
    decision, confidence = _compute_trigger_decision(
        rule_blocked=True,
        rule_state_event="MEAL_NOW",
        rule_discourse_label="QUESTION",
        ai_trigger_allowed=True,
        ai_state_event="MEAL_NOW",
        s_consistency=1.0,
    )
    assert decision == "deny"
    assert confidence == round(0.35 + 0.15 + 0.10, 4)

    # AI 未授权 -> deny
    decision, _ = _compute_trigger_decision(
        rule_blocked=False,
        rule_state_event="MEAL_NOW",
        rule_discourse_label="GENERIC_CHAT",
        ai_trigger_allowed=False,
        ai_state_event="MEAL_NOW",
        s_consistency=1.0,
    )
    assert decision == "deny"

    # AI 无状态事件 -> deny
    decision, _ = _compute_trigger_decision(
        rule_blocked=False,
        rule_state_event="MEAL_NOW",
        rule_discourse_label="GENERIC_CHAT",
        ai_trigger_allowed=True,
        ai_state_event="NONE",
        s_consistency=1.0,
    )
    assert decision == "deny"

    # 信号一致且高分 -> allow
    decision, confidence = _compute_trigger_decision(
        rule_blocked=False,
        rule_state_event="MEAL_NOW",
        rule_discourse_label="GENERIC_CHAT",
        ai_trigger_allowed=True,
        ai_state_event="MEAL_NOW",
        s_consistency=1.0,
    )
    assert decision == "allow"
    assert confidence == 1.0

    # 分数低于阈值 -> manual_review
    decision, confidence = _compute_trigger_decision(
        rule_blocked=False,
        rule_state_event="NONE",
        rule_discourse_label="GENERIC_CHAT",
        ai_trigger_allowed=True,
        ai_state_event="MEAL_NOW",
        s_consistency=0.0,
    )
    assert decision == "manual_review"
    assert confidence == round(0.35 * 0.40 + 0.35, 4)
    assert confidence < DEFAULT_FUSION_CONFIG.trigger_allow_threshold


def test_assess_risk_level_branches():
    """风险分类/记忆类型抬升阈值；uncategorized 提升分支；普通分支。"""
    assert _assess_risk_level("preference", "food", "dialogue", 0.75, 0.5) == (
        "high",
        0.9,
        0.7,
    )
    assert _assess_risk_level("food", "sensitive", "dialogue", 0.95, 0.5) == (
        "high",
        0.95,
        0.7,
    )
    assert _assess_risk_level("food", "food", "profile", 0.6, 0.4) == ("high", 0.9, 0.7)
    assert _assess_risk_level("uncategorized", "food", "dialogue", 0.75, 0.3) == (
        "promote_uncategorized",
        0.75,
        0.45,
    )
    assert _assess_risk_level("food", "food", "dialogue", 0.75, 0.5) == (
        "normal",
        0.75,
        0.5,
    )


# ---------------------------------------------------------------------------
# _apply_fusion_action
# ---------------------------------------------------------------------------

def test_apply_fusion_action_override():
    """达到覆盖阈值且允许覆盖时改写字段并记录快照。"""
    memory = {"metadata": {"seed": 1}, "topics": ["old"], "category": "food", "weight": 2.0}
    action, changed, rolled_back = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["old"],
        original_category="food",
        original_weight=2.0,
        ai_topics=["new1", "new2"],
        ai_category="drink",
        weight_delta=1.0,
        final_confidence=0.9,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=True,
        rollback_snapshot={},
        now_ts=123.0,
    )
    assert (action, changed, rolled_back) == ("override", True, False)
    assert memory["topics"] == ["new1", "new2"]
    assert memory["category"] == "drink"
    assert memory["weight"] == 3.0
    snapshot = memory["metadata"]["analysis_meta"]["override_snapshot"]
    assert snapshot == {
        "topics": ["old"],
        "category": "food",
        "weight": 2.0,
        "captured_at": 123.0,
    }


def test_apply_fusion_action_override_without_ai_fields():
    """AI 未给主题/分类/权重增量时，字段保持原值但仍算覆盖。"""
    memory = {"metadata": {}, "topics": ["old"], "category": "food", "weight": 2.0}
    action, changed, _ = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["old"],
        original_category="food",
        original_weight=2.0,
        ai_topics=[],
        ai_category="",
        weight_delta=0.0,
        final_confidence=0.95,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=True,
        rollback_snapshot={},
        now_ts=1.0,
    )
    assert (action, changed) == ("override", True)
    assert memory["topics"] == ["old"]
    assert memory["category"] == "food"
    assert memory["weight"] == 2.0


def test_apply_fusion_action_supplement_promote():
    """补充分支：合并主题、提升 uncategorized、写入 display_tags。"""
    memory = {
        "metadata": {},
        "topics": ["old"],
        "category": "uncategorized",
        "weight": 1.0,
        "display_tags": ["d1"],
    }
    action, changed, _ = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["old"],
        original_category="uncategorized",
        original_weight=1.0,
        ai_topics=["new", "old"],
        ai_category="food",
        weight_delta=0.5,
        final_confidence=0.6,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=False,
        rollback_snapshot={},
        now_ts=1.0,
    )
    assert (action, changed) == ("supplement", True)
    assert memory["topics"] == ["old", "new"]
    assert memory["category"] == "food"
    assert memory["weight"] == 1.5
    assert memory["display_tags"] == ["d1", "new", "old"]


def test_apply_fusion_action_supplement_keeps_category():
    """已分类时补充分支不改分类，且 display_tags 缺失时按空列表处理。"""
    memory = {"metadata": {}, "topics": ["old"], "category": "food", "weight": 1.0}
    action, changed, _ = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["old"],
        original_category="food",
        original_weight=1.0,
        ai_topics=["new"],
        ai_category="drink",
        weight_delta=0.0,
        final_confidence=0.6,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=False,
        rollback_snapshot={},
        now_ts=1.0,
    )
    assert (action, changed) == ("supplement", True)
    assert memory["category"] == "food"
    assert memory["weight"] == 1.0
    assert memory["display_tags"] == ["new"]


def test_apply_fusion_action_rollback():
    """低于补充阈值且存在快照时回滚，并清掉快照。"""
    memory = {
        "metadata": {"analysis_meta": {"override_snapshot": {"topics": ["s"], "category": "food"}}},
        "topics": ["cur"],
        "category": "drink",
        "weight": 5.0,
    }
    action, changed, rolled_back = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["cur"],
        original_category="drink",
        original_weight=5.0,
        ai_topics=[],
        ai_category="uncategorized",
        weight_delta=0.0,
        final_confidence=0.1,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=False,
        rollback_snapshot={"topics": ["s"], "category": "food", "weight": "3.0"},
        now_ts=1.0,
    )
    assert (action, changed, rolled_back) == ("rollback", True, True)
    assert memory["topics"] == ["s"]
    assert memory["category"] == "food"
    assert memory["weight"] == 3.0
    assert "override_snapshot" not in memory["metadata"]["analysis_meta"]


def test_apply_fusion_action_rollback_bad_weight():
    """快照权重无法转 float 时回退到原始权重。"""
    memory = {"metadata": {}, "topics": ["cur"], "category": "drink", "weight": 5.0}
    action, changed, rolled_back = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["cur"],
        original_category="drink",
        original_weight=5.0,
        ai_topics=[],
        ai_category="uncategorized",
        weight_delta=0.0,
        final_confidence=0.1,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=False,
        rollback_snapshot={"topics": ["s"], "category": "food", "weight": "bad"},
        now_ts=1.0,
    )
    assert (action, changed, rolled_back) == ("rollback", True, True)
    assert memory["weight"] == 5.0


def test_apply_fusion_action_reject():
    """既不够阈值也没有快照时不动记忆。"""
    memory = {"metadata": {}, "topics": ["cur"], "category": "food", "weight": 1.0}
    action, changed, rolled_back = _apply_fusion_action(
        memory=memory,
        memory_id="m1",
        original_topics=["cur"],
        original_category="food",
        original_weight=1.0,
        ai_topics=["x"],
        ai_category="drink",
        weight_delta=1.0,
        final_confidence=0.1,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.5,
        allow_override=True,
        rollback_snapshot={},
        now_ts=1.0,
    )
    assert (action, changed, rolled_back) == ("reject", False, False)
    assert memory["topics"] == ["cur"]
    assert memory["category"] == "food"
    assert memory["weight"] == 1.0


# ---------------------------------------------------------------------------
# _write_fusion_metadata
# ---------------------------------------------------------------------------

def test_write_fusion_metadata_writes_all_blocks():
    """融合元数据同时落到 analysis_meta、metadata 顶层与 ai_shadow。"""
    memory = {"metadata": {}, "topics": ["a"], "category": "food"}
    ai_shadow = {"topics": ["a"], "category": "food"}
    result = FusionResult(
        action="override",
        final_confidence=0.8,
        s_rule=0.4,
        s_ai=0.9,
        s_consistency=0.7,
        s_stability=0.5,
        trigger_final_confidence=0.6,
        trigger_decision="manual_review",
        rule_discourse_label="GENERIC_CHAT",
        rule_state_event="NONE",
        ai_discourse_label="GENERIC_CHAT",
        ai_state_event="MEAL_NOW",
        override_threshold=0.75,
        supplement_threshold=0.5,
        effective_override_threshold=0.9,
        effective_supplement_threshold=0.7,
        risk_level="high",
        allow_override=True,
        original_category="food",
        original_topics=["a"],
        ai_category="drink",
        ai_topics=["b"],
        memory_type="dialogue",
        now_ts=55.0,
    )
    _write_fusion_metadata(memory=memory, ai_shadow=ai_shadow, result=result)

    metadata = memory["metadata"]
    analysis_meta = metadata["analysis_meta"]
    fusion = analysis_meta["fusion"]
    assert fusion["action"] == "override"
    assert fusion["final_confidence"] == 0.8
    assert fusion["effective_override_min_confidence"] == 0.9
    assert fusion["version"] == "s_fuse_v1"
    assert fusion["updated_at"] == 55.0
    assert analysis_meta["state"] == "fusion_done"
    assert analysis_meta["last_action"] == "override"
    assert metadata["fuse_source"] == "s_fuse_v1"
    assert metadata["fuse_last_action"] == "override"
    assert metadata["fuse_updated_at"] == 55.0
    trace = metadata["decision_trace"]
    assert trace["rule_topics"] == ["a"]
    assert trace["bert_topics"] == ["b"]
    assert trace["version"] == "s_decision_trace_v1"
    assert metadata["ai_shadow"] is ai_shadow
    assert ai_shadow["fuse_version"] == "s_fuse_v1"
    assert ai_shadow["fuse_action"] == "override"
    assert ai_shadow["fuse_updated_at"] == 55.0


def test_write_fusion_metadata_non_dict_metadata():
    """metadata 非 dict 时重建并挂回 memory。"""
    memory = {"metadata": "bad"}
    ai_shadow = {}
    result = FusionResult(action="reject", now_ts=1.0)
    _write_fusion_metadata(memory=memory, ai_shadow=ai_shadow, result=result)
    assert isinstance(memory["metadata"], dict)
    assert memory["metadata"]["fuse_last_action"] == "reject"
    assert memory["metadata"]["analysis_meta"]["fusion"]["action"] == "reject"


# ---------------------------------------------------------------------------
# apply_ai_shadow_adjudication
# ---------------------------------------------------------------------------

def test_apply_ai_shadow_adjudication_no_candidates():
    """无候选时返回零统计，且不触发保存。"""
    weighted = {
        "fused": {
            "metadata": {"ai_shadow": {"fuse_version": "s_fuse_v1"}},
        },
        "no_shadow": {"metadata": {}},
        "bad_meta": {"metadata": "not-a-dict"},
    }
    manager = _FakeManager(weighted)
    report = apply_ai_shadow_adjudication(manager)
    assert report == {
        "processed": 0,
        "pending_before": 0,
        "pending_after": 0,
        "applied": 0,
        "rejected": 0,
        "updated_ids": [],
    }
    assert manager.save_count == 0


def test_apply_ai_shadow_adjudication_override_and_index_move():
    """低阈值 + 允许覆盖：分类变更并同步 category_index（含历史稳定性读取）。"""
    memory = _make_memory(
        "m1",
        topics=["a"],
        category="food",
        weight=1.0,
        ai_shadow={
            "topics": ["a"],
            "category": "drink",
            "confidence": 0.9,
            "weight_delta": 0.5,
        },
        analysis_meta={"ai_shadow": {"history": [{"topics": ["a"], "category": "food"}]}},
    )
    manager = _FakeManager({"m1": memory})
    manager.category_index["food"].append("m1")
    report = apply_ai_shadow_adjudication(
        manager,
        limit=16,
        override_min_confidence=0.0,
        supplement_min_confidence=0.0,
        allow_override=True,
    )
    assert report["processed"] == 1
    assert report["pending_before"] == 1
    assert report["pending_after"] == 0
    assert report["applied"] == 1
    assert report["rejected"] == 0
    assert report["updated_ids"] == ["m1"]
    assert memory["category"] == "drink"
    assert memory["weight"] == 1.5
    assert "m1" not in manager.category_index["food"]
    assert "m1" in manager.category_index["drink"]
    assert memory["metadata"]["analysis_meta"]["fusion"]["action"] == "override"
    assert manager.keyword_dirty == ["m1"]
    assert manager.save_count == 1


def test_apply_ai_shadow_adjudication_reject_rollback_and_rule_blocked():
    """高阈值下分别走到 reject / rollback，并验证规则屏蔽进入 fusion 元数据。"""
    reject_mem = _make_memory(
        "m_reject",
        topics=[],
        category="uncategorized",
        ai_shadow={"topics": [], "category": "uncategorized", "confidence": 0.0},
    )
    rollback_mem = _make_memory(
        "m_rollback",
        topics=["cur"],
        category="drink",
        weight=5.0,
        ai_shadow={"topics": [], "category": "uncategorized", "confidence": 0.0},
        analysis_meta={
            "override_snapshot": {"topics": ["s"], "category": "food", "weight": 2.0}
        },
    )
    blocked_mem = _make_memory(
        "m_blocked",
        topics=["a"],
        category="food",
        ai_shadow={"topics": ["a"], "category": "food", "confidence": 0.9},
        analysis_meta={"rule": {"discourse_label": "QUESTION", "state_event": "NONE"}},
    )
    plain_mem = _make_memory(
        "m_plain",
        topics=["a"],
        category="food",
        ai_shadow={"topics": ["a"], "category": "food", "confidence": 0.9},
        analysis_meta={"rule": "not-a-dict"},
    )
    manager = _FakeManager(
        {
            "m_reject": reject_mem,
            "m_rollback": rollback_mem,
            "m_blocked": blocked_mem,
            "m_plain": plain_mem,
        }
    )
    report = apply_ai_shadow_adjudication(
        manager,
        override_min_confidence=0.9,
        supplement_min_confidence=0.9,
        allow_override=True,
    )
    assert report["processed"] == 4
    assert report["pending_before"] == 4
    assert report["pending_after"] == 0
    assert report["rolled_back"] == 1
    assert report["applied"] == 1
    assert report["rejected"] == 3

    assert reject_mem["topics"] == []
    assert rollback_mem["topics"] == ["s"]
    assert rollback_mem["category"] == "food"
    assert rollback_mem["weight"] == 2.0
    assert rollback_mem["metadata"]["analysis_meta"]["fusion"]["action"] == "rollback"
    assert "override_snapshot" not in rollback_mem["metadata"]["analysis_meta"]

    blocked_fusion = blocked_mem["metadata"]["analysis_meta"]["fusion"]
    assert blocked_fusion["trigger_decision"] == "deny"
    assert blocked_fusion["rule_discourse_label"] == "QUESTION"
    assert blocked_fusion["action"] == "reject"

    plain_fusion = plain_mem["metadata"]["analysis_meta"]["fusion"]
    assert plain_fusion["rule_discourse_label"] == "GENERIC_CHAT"
    assert plain_fusion["rule_state_event"] == "NONE"


def test_apply_ai_shadow_adjudication_skips_non_dict_memory(monkeypatch):
    """第二轮取到非 dict / metadata 非 dict 的记录被跳过。"""
    good_a = _make_memory(
        "m_bad",
        topics=["a"],
        category="food",
        ai_shadow={"topics": ["a"], "category": "food", "confidence": 0.9},
    )
    good_b = _make_memory(
        "m_meta_bad",
        topics=["a"],
        category="food",
        ai_shadow={"topics": ["a"], "category": "food", "confidence": 0.9},
    )
    weighted = _ScriptedDict(
        {"m_bad": good_a, "m_meta_bad": good_b},
        {"m_bad": ["not-a-dict"], "m_meta_bad": [{"metadata": "not-a-dict"}]},
    )
    manager = _FakeManager(weighted)
    report = apply_ai_shadow_adjudication(manager, override_min_confidence=0.0)
    assert report["processed"] == 0
    assert report["pending_before"] == 2
    assert report["pending_after"] == 2
    assert report["updated_ids"] == []
    assert manager.save_count == 0


def test_apply_ai_shadow_adjudication_supplement_and_threshold_clamp():
    """supplement 分支 + supplement 阈值被夹到 override 阈值。"""
    memory = _make_memory(
        "m1",
        topics=["a"],
        category="uncategorized",
        ai_shadow={
            "topics": ["a"],
            "category": "food",
            "confidence": 0.9,
            "discourse_label": "GENERIC_CHAT",
            "state_event": "MEAL_NOW",
            "trigger_allowed": True,
        },
        analysis_meta={"rule": {"discourse_label": "GENERIC_CHAT", "state_event": "MEAL_NOW"}},
    )
    manager = _FakeManager({"m1": memory})
    report = apply_ai_shadow_adjudication(
        manager,
        override_min_confidence=0.2,
        supplement_min_confidence=0.99,
        allow_override=False,
    )
    assert report["applied"] == 1
    assert report["updated_ids"] == ["m1"]
    assert memory["topics"] == ["a"]
    assert memory["category"] == "food"
    fusion = memory["metadata"]["analysis_meta"]["fusion"]
    assert fusion["action"] == "supplement"
    # 传入的 0.99 > override 0.2，被夹回 0.2
    assert fusion["supplement_min_confidence"] == 0.2
    assert fusion["override_min_confidence"] == 0.2
    # uncategorized 提升分支把有效补充阈值抬到 0.45
    assert fusion["effective_supplement_min_confidence"] == 0.45
    assert fusion["trigger_decision"] == "allow"
    assert fusion["allow_override"] is False


# ---------------------------------------------------------------------------
# _prepare_pending_analysis
# ---------------------------------------------------------------------------

def test_prepare_pending_analysis_empty_content():
    """内容为空时返回 skip 标记。"""
    manager = _FakeManager()
    prep = _prepare_pending_analysis(manager, "m1", {"content": "   "}, 1.0)
    assert prep == {"skip": True, "memory_id": "m1", "empty_content": True}


def test_prepare_pending_analysis_full_with_penalty():
    """完整路径：主题合并分类、指令语气罚分、关键词与展示标签去重。"""
    manager = _FakeManager(
        topics=["a"],
        category="food",
        emotion="happy",
        keywords=["k2", "k1"],
        weight=2.0,
    )
    prep = _prepare_pending_analysis(
        manager, "m1", {"content": "记得喝水", "category": "old", "is_important": True}, 9.0
    )
    assert prep["skip"] is False
    assert prep["content"] == "记得喝水"
    assert prep["old_category"] == "old"
    assert prep["topics"] == ["a", "food"]
    assert prep["category"] == "food"
    assert prep["discourse_label"] == "INSTRUCTION"
    assert prep["emotions"] == ["happy"]
    assert prep["weight"] == 1.6
    assert prep["search_keywords"] == ["k1", "k2"]
    assert prep["display_tags"] == ["a", "food", "k1", "k2"]
    assert prep["now_ts"] == 9.0
    assert "原文：记得喝水" in prep["bert_input_text"]
    assert manager.weight_calculator.calls[0]["is_important"] is True
    assert manager.weight_calculator.calls[0]["emotions"] == ["happy"]


def test_prepare_pending_analysis_uncategorized_and_no_emotion():
    """uncategorized 不并入主题，空情绪被过滤掉，普通语气不加罚分。"""
    manager = _FakeManager(
        topics=["a"],
        category="uncategorized",
        emotion="",
        keywords=[],
        weight=2.0,
    )
    prep = _prepare_pending_analysis(
        manager, "m1", {"content": "随便聊聊", "category": "uncategorized"}, 3.0
    )
    assert prep["topics"] == ["a"]
    assert prep["category"] == "uncategorized"
    assert prep["emotions"] == []
    assert prep["weight"] == 2.0
    assert prep["display_tags"] == ["a"]
    assert manager.weight_calculator.calls[0]["emotions"] == []


# ---------------------------------------------------------------------------
# _apply_pending_analysis_result
# ---------------------------------------------------------------------------

def test_apply_pending_analysis_result_empty_content():
    """空内容：清 pending、减计数、写错误态。"""
    memory = {"metadata": {"analysis_pending": True}}
    manager = _FakeManager({"m1": memory}, pending_count=3)
    ok = _apply_pending_analysis_result(
        manager, "m1", memory, {"empty_content": True}, {}, 42.0
    )
    assert ok is False
    assert manager._pending_analysis_count == 2
    metadata = memory["metadata"]
    assert metadata["analysis_pending"] is False
    assert metadata["analysis_error"] == "empty_content"
    assert metadata["analysis_completed_at"] == 42.0
    assert metadata["analysis_meta"]["state"] == "rule_failed"
    assert metadata["analysis_meta"]["error"] == "empty_content"


def test_apply_pending_analysis_result_empty_content_non_dict_metadata():
    """空内容但 metadata 非 dict 时安全返回 False。"""
    memory = {"metadata": [1, 2]}
    manager = _FakeManager({"m1": memory})
    assert _apply_pending_analysis_result(
        manager, "m1", memory, {"empty_content": True}, {}, 1.0
    ) is False
    assert memory["metadata"] == [1, 2]


def test_apply_pending_analysis_result_ok_path():
    """正常路径：写规则块与 BERT 影子，递增计数器并更新索引。"""
    memory = {
        "metadata": {"analysis_pending": True},
        "category": "uncategorized",
        "weight": 0.5,
    }
    manager = _FakeManager({"m1": memory}, pending_count=1, ai_shadow_count=0)
    manager.category_index["uncategorized"].append("m1")
    prep = _make_prep()
    bert = {
        "topics": ["bt"],
        "category": "food",
        "confidence": 0.7,
        "weight_delta": 0.2,
        "discourse_label": "GENERIC_CHAT",
        "state_event": "MEAL_NOW",
        "trigger_allowed": True,
        "reason": "done",
        "source": "bert_local",
        "status": "ok",
        "latency_ms": 3.0,
    }
    ok = _apply_pending_analysis_result(manager, "m1", memory, prep, bert, 77.0)
    assert ok is True
    assert memory["topics"] == ["a"]
    assert memory["category"] == "food"
    assert memory["emotions"] == ["happy"]
    assert memory["emotion"] == "happy"
    assert memory["weight"] == 1.5
    assert memory["search_keywords"] == ["k1"]
    assert memory["keywords"] == ["k1"]
    assert memory["display_tags"] == ["d1"]
    assert memory["last_access_time"] == 77.0
    metadata = memory["metadata"]
    assert metadata["analysis_pending"] is False
    assert metadata["analysis_source"] == "rule_worker"
    assert metadata["analysis_version"] == "s_rule_v1"
    analysis_meta = metadata["analysis_meta"]
    assert analysis_meta["rule"]["category"] == "food"
    assert analysis_meta["rule"]["discourse_label"] == "GENERIC_CHAT"
    assert analysis_meta["rule"]["state_event"] == "MEAL_NOW"
    assert analysis_meta["bert_shadow"]["input_text"] == "原文：今天吃了饭"
    assert analysis_meta["bert_shadow"]["version"] == "s_bert_shadow_v1"
    assert analysis_meta["state"] == "ai_shadow_done"
    assert metadata["ai_shadow"]["topics"] == ["bt"]
    assert metadata["ai_shadow"]["trigger_allowed"] is True
    assert manager._pending_analysis_count == 0
    assert manager._ai_shadow_count == 1
    assert "m1" not in manager.category_index["uncategorized"]
    assert "m1" in manager.category_index["food"]
    assert manager.topic_weights["a"] == pytest.approx(0.15)
    assert manager.emotion_memory_map["happy"] == [
        {"memory_id": "m1", "relevance_score": 0.8}
    ]
    assert manager.keyword_dirty == ["m1"]


def test_apply_pending_analysis_result_non_ok_status():
    """BERT 状态非 ok 时只落到 rule_done，不写 ai_shadow。"""
    memory = {"metadata": {}, "category": "food", "weight": 1.0}
    manager = _FakeManager({"m1": memory}, ai_shadow_count=0)
    prep = _make_prep(category="food", old_category="food", emotions=[], search_keywords=[])
    ok = _apply_pending_analysis_result(
        manager, "m1", memory, prep, {"status": "skipped"}, 5.0
    )
    assert ok is True
    metadata = memory["metadata"]
    assert metadata["analysis_meta"]["state"] == "rule_done"
    assert "ai_shadow" not in metadata
    assert manager._ai_shadow_count == 0
    assert memory["emotion"] == "neutral"


# ---------------------------------------------------------------------------
# process_pending_analysis
# ---------------------------------------------------------------------------

def test_apply_pending_analysis_result_non_dict_metadata():
    """正常路径但 metadata 非 dict 时被替换为新的 dict。"""
    memory = {"metadata": None, "category": "food", "weight": 1.0}
    manager = _FakeManager({"m1": memory})
    prep = _make_prep(category="food", old_category="food", emotions=[])
    ok = _apply_pending_analysis_result(manager, "m1", memory, prep, {}, 8.0)
    assert ok is True
    assert isinstance(memory["metadata"], dict)
    assert memory["metadata"]["analysis_pending"] is False
    # 空 bert_shadow 的 status 默认 "ok"，因此落到 ai_shadow_done
    assert memory["metadata"]["analysis_meta"]["state"] == "ai_shadow_done"
    assert memory["metadata"]["ai_shadow"]["category"] == "uncategorized"


def test_process_pending_analysis_no_pending():
    """无待分析记忆时直接返回零统计，不保存（含 metadata 非 dict 的跳过分支）。"""
    manager = _FakeManager(
        {
            "m1": {"metadata": {"analysis_pending": False}},
            "m2": {"metadata": "not-a-dict"},
        }
    )
    report = process_pending_analysis(manager)
    assert report == {
        "processed": 0,
        "pending_before": 0,
        "pending_after": 0,
        "updated_ids": [],
    }
    assert manager.save_count == 0


def test_process_pending_analysis_full(monkeypatch):
    """端到端：收集快照 -> 锁外分析 -> 锁内落库，并触发一次保存。"""
    analyzer = _install_fake_bert(
        monkeypatch,
        {
            "topics": ["bt"],
            "category": "food",
            "confidence": 0.8,
            "weight_delta": 0.1,
            "reason": "done",
        },
    )
    weighted = {
        "m1": {
            "content": "今天吃了饭",
            "category": "uncategorized",
            "is_important": False,
            "metadata": {"analysis_pending": True},
            "timestamp": 1.0,
        },
        "m2": {
            "content": "记得喝水",
            "category": "food",
            "is_important": True,
            "metadata": {"analysis_pending": True},
            "timestamp": 2.0,
        },
    }
    manager = _FakeManager(
        weighted,
        topics=["a"],
        category="food",
        emotion="happy",
        keywords=["k1"],
        weight=2.0,
        ai_shadow_count=0,
    )
    report = process_pending_analysis(manager, limit=10)
    assert report["processed"] == 2
    assert report["pending_before"] == 2
    assert report["pending_after"] == 0
    assert report["updated_ids"] == ["m1", "m2"]
    assert len(analyzer.calls) == 2

    assert manager.weighted_memories["m1"]["category"] == "food"
    assert manager.weighted_memories["m1"]["topics"] == ["a", "food"]
    assert manager.weighted_memories["m1"]["metadata"]["analysis_pending"] is False
    assert (
        manager.weighted_memories["m1"]["metadata"]["analysis_meta"]["rule"]["state_event"]
        == "MEAL_NOW"
    )
    assert manager.weighted_memories["m2"]["weight"] == 1.6
    assert manager._ai_shadow_count == 2
    assert len(manager.emotion_memory_map["happy"]) == 2
    assert manager.topic_weights["a"] == pytest.approx(0.36)
    assert manager.save_count == 1


def test_process_pending_analysis_skips_non_dict_memory(monkeypatch):
    """快照阶段取到非 dict 记录时跳过；第三阶段取到 dict 但无 prep 时也跳过。"""
    _install_fake_bert(monkeypatch, {"topics": ["bt"], "category": "food"})
    real1 = {
        "content": "今天吃了饭",
        "category": "uncategorized",
        "is_important": False,
        "metadata": {"analysis_pending": True},
        "timestamp": 1.0,
    }
    real2 = {
        "content": "记得喝水",
        "category": "food",
        "is_important": False,
        "metadata": {"analysis_pending": True},
        "timestamp": 2.0,
    }
    # m1 两阶段都取到非 dict；m2 第一阶段非 dict（无快照），第三阶段是 dict（无 prep）
    weighted = _ScriptedDict(
        {"m1": real1, "m2": real2},
        {"m1": ["not-a-dict", "not-a-dict"], "m2": ["not-a-dict", real2]},
    )
    manager = _FakeManager(weighted, topics=["a"], category="food")
    report = process_pending_analysis(manager)
    assert report["processed"] == 0
    assert report["pending_before"] == 2
    assert report["pending_after"] == 2
    assert report["updated_ids"] == []
    assert real1["metadata"]["analysis_pending"] is True
    assert real2["metadata"]["analysis_pending"] is True
    assert manager.save_count == 0


# ---------------------------------------------------------------------------
# 常量/配置健全性（防止顺手改坏被别处依赖的默认值）
# ---------------------------------------------------------------------------

def test_fusion_config_defaults_are_consistent():
    """默认配置权重之和为 1，且补充阈值不高于覆盖阈值。"""
    config = FusionConfig()
    assert config == DEFAULT_FUSION_CONFIG
    assert round(
        config.s_rule + config.s_ai + config.s_consistency + config.s_stability, 6
    ) == 1.0
    assert round(
        config.consistency_topic + config.consistency_category + config.consistency_discourse,
        6,
    ) == 1.0
    assert analysis_ops.DISCOURSE_WEIGHT_PENALTIES["QUESTION"] == -0.4
    assert "QUESTION" in analysis_ops.BLOCKED_DISCOURSE_LABELS
    assert "profile" in analysis_ops.RISK_MEMORY_TYPES


def test_module_exports_expected_surface():
    """关键函数可被外部按名导入（回归保护）。"""
    for name in (
        "count_pending_analysis",
        "get_pending_analysis_items",
        "attach_ai_shadow_result",
        "count_ai_shadow_results",
        "apply_ai_shadow_adjudication",
        "process_pending_analysis",
    ):
        assert callable(getattr(analysis_ops, name))
