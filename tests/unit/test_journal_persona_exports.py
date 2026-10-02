"""``core.services.journal.persona_exports`` 单元测试。

覆盖三类内容：
1. 模块级纯函数（日期归一、片段清洗、画像/事件渲染等）；
2. 下游协作者全部 stub 掉的 BERT / LLM 分支（不触碰真实模型）；
3. ``PersonaJournalExportService`` 的落盘行为。

所有文件 IO 都走 pytest 的 ``tmp_path``，并通过替换
``_role_persona_data_dir`` 与 ``JournalStorage`` 把导出根目录隔离到临时目录，
绝不写进仓库里的真实数据目录。
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import core.services.journal.persona_exports as pe
from core.services.dual_role.constants import (
    DEFAULT_PERSONAS,
    LING_PERSONAS,
    get_persona_scope,
)
from core.services.journal.diary_personas import (
    get_diary_persona_ids,
    get_diary_persona_name,
)
from core.services.journal.models import DailySummary, JournalEntry

# 运行期真实的注册角色（写日记的角色集合由配置决定，这里动态取，避免硬编码）
_DIARY_IDS = get_diary_persona_ids()
_DATE = datetime(2026, 8, 23)
_PERSONA = "Aveline"  # 注册角色 aveline 的权威中文名


# ---------------------------------------------------------------- 测试替身


def _entry(
    content: str = "Aveline：今天去公园散步了，天气很好",
    *,
    entry_type: str = "daily",
    source: str = "user",
    thought: str | None = None,
    tags: list[str] | None = None,
    timestamp: float = 1.0,
) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp,
        time_str="00:00:01",
        type=entry_type,
        content=content,
        thought=thought,
        tags=list(tags or []),
        source=source,
    )


class _FakeStorage:
    """内存版 JournalStorage，只实现导出链路用到的两个读接口。"""

    def __init__(self, entries=None, summaries=None):
        self.entries_data = list(entries or [])
        self.summaries = dict(summaries or {})
        self.entry_calls = 0
        self.summary_calls: list[str] = []

    async def get_entries(self, dt):
        self.entry_calls += 1
        return list(self.entries_data)

    async def get_daily_summary(self, dt, scope="user"):
        self.summary_calls.append(scope)
        return self.summaries.get(scope)


class _FakeAnalyzer:
    """假 BERT 分析器：返回固定结构，避免加载真实模型。"""

    def __init__(self, payload=None, exc=None):
        if payload is None:
            payload = {
                "category": "chat",
                "topics": ["日常"],
                "weight_delta": 0.5,
                "state_event": "NONE",
                "discourse": {"discourse_label": "CHAT"},
            }
        self.payload = payload
        self.exc = exc
        self.seen: list[str] = []

    def analyze(self, text):
        self.seen.append(text)
        if self.exc:
            raise self.exc
        return dict(self.payload)


class _FakeLLM:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple] = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.exc:
            raise self.exc
        return self.response


def _install_llm_modules(monkeypatch, llm, *, journal_model="model-x", model_raises=False):
    """把 _generate_diary_with_llm 里的全部惰性 import 换成假模块。"""
    llm_mod = types.ModuleType("core.llm")
    llm_mod.get_llm_module = lambda: llm
    monkeypatch.setitem(sys.modules, "core.llm", llm_mod)

    prompt_mod = types.ModuleType(
        "core.agents.chat_agent_components.persona_system.prompt.components"
    )
    prompt_mod.JOURNAL_LLM_DIARY_PROMPT_TEMPLATE = (
        "{persona_name}|{date}|{portrait_text}|{events_text}|"
        "{fragments_text}|{highlights_text}|{study_text}"
    )
    monkeypatch.setitem(
        sys.modules,
        "core.agents.chat_agent_components.persona_system.prompt.components",
        prompt_mod,
    )

    settings = SimpleNamespace(model=SimpleNamespace(journal_model_hint="fallback-hint"))
    cfg_mod = types.ModuleType("config.integrated_config")
    cfg_mod.get_settings = lambda: settings
    monkeypatch.setitem(sys.modules, "config.integrated_config", cfg_mod)

    mc_mod = types.ModuleType("config.model_config")
    if model_raises:
        def _raise():
            raise RuntimeError("模型提示不可用")
        mc_mod.get_journal_model = _raise
    else:
        mc_mod.get_journal_model = lambda: journal_model
    monkeypatch.setitem(sys.modules, "config.model_config", mc_mod)
    return settings


@pytest.fixture()
def export_env(tmp_path, monkeypatch):
    """隔离导出根目录 / JournalStorage / BERT 分析器。"""
    storage = _FakeStorage()

    def _fake_root(scope):
        return tmp_path / f"{scope}_data" / "persona_data"

    monkeypatch.setattr(pe, "_role_persona_data_dir", _fake_root)
    monkeypatch.setattr(pe, "JournalStorage", lambda: storage)
    monkeypatch.setattr(pe, "_get_bert_analyzer", lambda: _FakeAnalyzer())
    return SimpleNamespace(tmp_path=tmp_path, storage=storage)


def _make_service(export_env):
    return pe.PersonaJournalExportService()


# ---------------------------------------------------------------- _safe_segment


def test_safe_segment_empty_and_none_fall_back_to_default():
    assert pe._safe_segment("") == "default"
    assert pe._safe_segment("   ") == "default"
    assert pe._safe_segment(None) == "default"
    assert pe._safe_segment("._ ") == "default"


def test_safe_segment_replaces_illegal_filename_chars():
    raw = 'a<b>c:d"e/f\\g|h?i*j'
    cleaned = pe._safe_segment(raw)
    assert cleaned == "a_b_c_d_e_f_g_h_i_j"
    for ch in '<>:"/\\|?*':
        assert ch not in cleaned


# ---------------------------------------------------------------- _normalize_date


def test_normalize_date_passthrough_and_parsing(monkeypatch):
    monkeypatch.setattr(pe, "get_current_time", lambda: datetime(1999, 1, 1))
    assert pe._normalize_date(_DATE) is _DATE
    assert pe._normalize_date("2026-08-23") == datetime(2026, 8, 23)
    assert pe._normalize_date("2026-08-23 10:30:00") == datetime(2026, 8, 23)
    # 非法 / 空值统一兜底到 get_current_time
    assert pe._normalize_date("不是日期") == datetime(1999, 1, 1)
    assert pe._normalize_date(None) == datetime(1999, 1, 1)
    assert pe._normalize_date("") == datetime(1999, 1, 1)


# ---------------------------------------------------------------- _entry_to_dict


def test_entry_to_dict_copies_all_fields():
    entry = _entry("内容", tags=["a", "b"], source="ling", thought="想", entry_type="daily")
    payload = pe._entry_to_dict(entry)
    assert payload["id"] == entry.id
    assert payload["content"] == "内容"
    assert payload["tags"] == ["a", "b"]
    assert payload["source"] == "ling"
    assert payload["thought"] == "想"
    assert payload["type"] == "daily"
    assert payload["mood"] == entry.mood


def test_entry_to_dict_tolerates_none_tags():
    entry = _entry("内容")
    entry.tags = None  # 模拟历史脏数据
    assert pe._entry_to_dict(entry)["tags"] == []


# ---------------------------------------------------------------- scope / persona 解析


def test_resolve_active_persona_scope_returns_real_scope():
    assert pe._resolve_active_persona_scope() == "aveline"


def test_resolve_active_persona_scope_falls_back_on_error(monkeypatch):
    import core.utils.data.data_paths as dp_mod

    def _boom():
        raise RuntimeError("no active persona")

    monkeypatch.setattr(dp_mod, "_resolve_scope_from_active_persona", _boom)
    assert pe._resolve_active_persona_scope() == "aveline"


def test_role_persona_data_dir_points_at_role_dir():
    path = pe._role_persona_data_dir("aveline")
    assert path.name == "persona_data"
    assert "aveline_data" in str(path)


def test_scope_default_persona_map_uses_en_name():
    mapping = pe._scope_default_persona_map()
    assert set(mapping) == set(_DIARY_IDS)
    assert mapping["aveline"] == "Aveline"


def test_scope_default_persona_map_falls_back_when_profile_missing(monkeypatch):
    import core.services.dual_role.personas as personas_mod

    monkeypatch.setattr(personas_mod, "get_persona", lambda role_id: None)
    mapping = pe._scope_default_persona_map()
    assert mapping == {role_id: role_id for role_id in _DIARY_IDS}


def test_infer_active_persona_name_maps_scope():
    assert pe._infer_active_persona_name() == "Aveline"


def test_infer_persona_name_from_content_and_source():
    assert pe._infer_persona_name(_entry("Ling：我在写作业")) == "Ling"
    assert pe._infer_persona_name(_entry("随便聊聊", source="ling")) == "Ling"
    assert pe._infer_persona_name(_entry("随便聊聊", source="unknown-src")) is None


def test_infer_persona_name_ignores_blank_tags():
    entry = _entry("随便聊聊", tags=["  ", "Ling"], source="user")
    assert pe._infer_persona_name(entry) == "Ling"


# ---------------------------------------------------------------- 条目过滤


def test_is_legacy_background_circle_entry_detects_thought_and_tag():
    assert pe._is_legacy_background_circle_entry(_entry(thought="dual_role_background_circle"))
    assert pe._is_legacy_background_circle_entry(_entry(tags=["后台圈子"]))
    assert pe._is_legacy_background_circle_entry(_entry(tags=[" ", "后台圈子"]))
    assert not pe._is_legacy_background_circle_entry(_entry())


def test_is_diary_like_entry_filters_system_entries():
    assert not pe._is_diary_like_entry(_entry(entry_type="daily_summary"))
    assert not pe._is_diary_like_entry(
        _entry(source="system", thought="auto_generated_daily_summary")
    )
    assert not pe._is_diary_like_entry(_entry(thought="dual_role_background_circle"))
    assert pe._is_diary_like_entry(_entry())


def test_entry_mentions_persona_matches_prefix():
    assert pe._entry_mentions_persona(_entry("Aveline：在的"), "Aveline")
    assert not pe._entry_mentions_persona(_entry("Aveline在的"), "Aveline")


def test_get_persona_dir_name_returns_scope():
    assert pe._get_persona_dir_name(_PERSONA) == get_persona_scope(_PERSONA) == "aveline"
    assert pe._get_persona_dir_name("Ye") == "ye"


# ---------------------------------------------------------------- 片段清洗


def test_split_fragment_lines_filters_speakers_and_noise():
    text = "\n".join(
        [
            "",
            "Ling：我今天很开心",  # 已知说话人但非当前 persona → 丢弃
            "Aveline：我今天去公园散步了",  # 当前 persona → 去掉前缀
            "陌生人：这是一句很长的话",  # 未知说话人 → 整行保留
            "有",  # 太短 → 丢弃
            "我很好因为",  # 半截话 → 丢弃
            "今天天气不错",  # 正常保留
        ]
    )
    result = pe._split_fragment_lines(_PERSONA, text)
    assert result == ["我今天去公园散步了", "陌生人：这是一句很长的话", "今天天气不错"]


def test_split_fragment_lines_handles_empty_text():
    assert pe._split_fragment_lines(_PERSONA, "") == []
    assert pe._split_fragment_lines(_PERSONA, None) == []


def test_collect_fragments_dedups_case_insensitively():
    entries = [
        {"content": "今天天气不错"},
        {"content": "今天天气不错"},  # 完全重复 → 去重
        {"content": "TODAY 很忙"},
        {"content": "today 很忙"},  # 仅大小写不同 → 去重
    ]
    result = pe._collect_fragments(_PERSONA, entries)
    assert result == ["今天天气不错", "TODAY 很忙"]


def test_collect_fragments_falls_back_to_low_signal():
    entries = [{"content": "早点休息"}]
    assert pe._collect_fragments(_PERSONA, entries) == ["早点休息"]


def test_collect_fragments_returns_empty_when_nothing_usable():
    assert pe._collect_fragments(_PERSONA, [{"content": ""}]) == []


# ---------------------------------------------------------------- 学习句子


def test_build_study_sentence_empty_inputs():
    assert pe._build_study_sentence({}) == ""
    assert pe._build_study_sentence(None) == ""
    assert pe._build_study_sentence("not-a-dict") == ""


def test_build_study_sentence_renders_session_and_vocab():
    summary = {
        "session": {"study_duration_minutes": 45, "study_session_count": 2},
        "vocab": {"new_words": 12, "reviewed_words": 30},
    }
    text = pe._build_study_sentence(summary)
    assert "学习时长约45分钟" in text
    assert "完成2次学习记录" in text
    assert "新增词汇12个" in text
    assert "复习词汇30个" in text


def test_build_study_sentence_single_side_fields():
    assert pe._build_study_sentence({"session": {"study_session_count": 1}}) == "完成1次学习记录"
    assert pe._build_study_sentence({"vocab": {"new_words": 3}}) == "新增词汇3个"
    # session / vocab 存在但不是 dict → 当空处理
    assert pe._build_study_sentence({"session": "x", "vocab": []}) == ""


def test_build_study_sentence_includes_concepts():
    summary = {"concepts": {"taught": ["分数"]}}
    assert pe._build_study_sentence(summary) == "今天讲到分数"


# ---------------------------------------------------------------- 知识点句子


def test_build_concept_sentences_empty_inputs():
    assert pe._build_concept_sentences(None) == []
    assert pe._build_concept_sentences({}) == []
    assert pe._build_concept_sentences([1, 2]) == []


def test_build_concept_sentences_excludes_hint_assisted_from_correct():
    concepts = {
        "taught": ["分数", "小数"],
        "correct": ["分数", "小数", "  ", "比例"],
        "hint_assisted": ["小数"],
        "incorrect": ["比例"],
        "confused": ["通分"],
    }
    out = pe._build_concept_sentences(concepts)
    assert "今天讲到分数、小数" in out
    # 靠提示答出的「小数」不能算独立答对
    assert "他自己答出了分数、比例" in out
    assert "小数是靠提示才答出的" in out
    assert "在比例上答错了" in out
    assert "他说通分没听懂" in out


def test_build_concept_sentences_snapshot_wording():
    concepts = {
        "mastered_total": 8,
        "weak": [{"name": "分数"}, {"other": 1}, {"name": "小数"}, {"name": "比例"}],
        "unverified_count": 3,
    }
    out = pe._build_concept_sentences(concepts)
    assert "目前累计掌握8个知识点" in out
    assert "目前还薄弱的有分数、小数" in out
    assert "另有3个知识点只讲过、还没检验过他是否真的会" in out


def test_build_concept_sentences_bad_numeric_fields_default_to_zero():
    concepts = {"mastered_total": "abc", "unverified_count": object(), "weak": []}
    assert pe._build_concept_sentences(concepts) == []


def test_build_concept_sentences_limits_names_to_three():
    concepts = {"taught": ["a", "b", "c", "d"]}
    assert pe._build_concept_sentences(concepts) == ["今天讲到a、b、c"]


# ---------------------------------------------------------------- BERT 分析


def test_get_bert_analyzer_returns_cached_instance(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(pe, "_BERT_ANALYZER_INSTANCE", sentinel)
    assert pe._get_bert_analyzer() is sentinel


def test_get_bert_analyzer_builds_instance_on_success(monkeypatch):
    monkeypatch.setattr(pe, "_BERT_ANALYZER_INSTANCE", None)
    fake_mod = types.ModuleType("core.services.data_ops.bert_analyzer")

    class _Bert:
        pass

    fake_mod.BertAnalyzer = _Bert
    monkeypatch.setitem(sys.modules, "core.services.data_ops.bert_analyzer", fake_mod)
    analyzer = pe._get_bert_analyzer()
    assert isinstance(analyzer, _Bert)
    assert pe._BERT_ANALYZER_INSTANCE is analyzer


def test_get_bert_analyzer_returns_none_on_import_failure(monkeypatch):
    monkeypatch.setattr(pe, "_BERT_ANALYZER_INSTANCE", None)
    fake_mod = types.ModuleType("core.services.data_ops.bert_analyzer")  # 缺 BertAnalyzer
    monkeypatch.setitem(sys.modules, "core.services.data_ops.bert_analyzer", fake_mod)
    assert pe._get_bert_analyzer() is None
    assert pe._BERT_ANALYZER_INSTANCE is None


def test_analyze_fragment_sync_without_analyzer(monkeypatch):
    monkeypatch.setattr(pe, "_get_bert_analyzer", lambda: None)
    result = pe._analyze_fragment_sync("任意文本")
    assert result == {
        "category": "uncategorized",
        "topics": [],
        "importance": 0.0,
        "state_event": "NONE",
        "discourse": "GENERIC_CHAT",
    }


def test_analyze_fragment_sync_maps_analyzer_output(monkeypatch):
    monkeypatch.setattr(pe, "_get_bert_analyzer", lambda: _FakeAnalyzer())
    result = pe._analyze_fragment_sync("任意文本")
    assert result["category"] == "chat"
    assert result["topics"] == ["日常"]
    assert result["importance"] == 0.5
    assert result["state_event"] == "NONE"
    assert result["discourse"] == "CHAT"


def test_analyze_fragment_sync_defaults_on_missing_keys(monkeypatch):
    analyzer = _FakeAnalyzer(payload={})
    monkeypatch.setattr(pe, "_get_bert_analyzer", lambda: analyzer)
    result = pe._analyze_fragment_sync("任意文本")
    assert result["category"] == "uncategorized"
    assert result["discourse"] == "GENERIC_CHAT"


def test_analyze_fragment_sync_swallows_analyzer_errors(monkeypatch):
    analyzer = _FakeAnalyzer(exc=RuntimeError("炸了"))
    monkeypatch.setattr(pe, "_get_bert_analyzer", lambda: analyzer)
    assert pe._analyze_fragment_sync("任意文本")["category"] == "uncategorized"


def test_analyze_fragments_batch_empty_short_circuits():
    assert asyncio.run(pe._analyze_fragments_batch([])) == []


def test_analyze_fragments_batch_sorts_by_importance(monkeypatch):
    weights = {"低": 0.1, "高": 0.9, "中": 0.5}

    def _fake_sync(text):
        return {
            "category": "chat",
            "topics": [],
            "importance": weights[text],
            "state_event": "NONE",
            "discourse": "GENERIC_CHAT",
        }

    monkeypatch.setattr(pe, "_analyze_fragment_sync", _fake_sync)
    result = asyncio.run(pe._analyze_fragments_batch(["低", "高", "中"], max_count=3))
    assert [item["text"] for item in result] == ["高", "中", "低"]
    # max_count 生效：只分析前 N 条
    assert [item["text"] for item in asyncio.run(pe._analyze_fragments_batch(["低", "高"], max_count=1))] == ["低"]


# ---------------------------------------------------------------- 生活画像 / 结构化事件


def test_build_daily_portrait_text_empty_inputs():
    assert pe._build_daily_portrait_text({}) == ""
    assert pe._build_daily_portrait_text(None) == ""


def test_build_daily_portrait_text_full_record():
    record = {
        "sleep_cycle": {"wakeup": "07:00", "sleep": "23:30"},
        "meals": [
            {"type": "breakfast", "content": "牛奶面包"},
            {"type": "lunch", "content": ""},
            {"type": "custom", "content": "火锅"},
        ],
        "study": {"sessions": [{"topic": "英语"}, {"topic": ""}]},
        "activities": [{"content": "散步"}, {"content": ""}],
        "health": [{"symptom": "头痛"}, {"symptom": ""}],
        "mood": {"mood": "开心"},
    }
    text = pe._build_daily_portrait_text(record)
    assert "起床于07:00" in text
    assert "入睡于23:30" in text
    assert "早餐吃了牛奶面包" in text
    assert "custom吃了火锅" in text
    assert "学习了英语" in text
    assert "活动：散步" in text
    assert "健康状态：头痛" in text
    assert "心情：开心" in text


def test_build_daily_portrait_text_schedule_and_plain_mood():
    record = {"schedule": {"wakeup": "06:00"}, "mood": "平静"}
    text = pe._build_daily_portrait_text(record)
    assert "起床于06:00" in text
    assert "心情：平静" in text


def test_build_structured_events_from_record():
    record = {
        "sleep_cycle": {"wakeup": "07:00", "sleep": "23:30"},
        "meals": [
            {"type": "breakfast", "content": "牛奶", "time": "07:20"},
            {"type": "lunch", "content": "", "time": "12:00"},
        ],
        "study": {
            "sessions": [
                {"topic": "英语", "time": "09:00"},
                {"content": "做习题", "time": "10:00"},
                {"topic": "", "content": "", "time": "11:00"},
            ]
        },
    }
    events = pe._build_structured_events(record, [])
    types_seen = [e["type"] for e in events]
    assert types_seen.count("meal") == 2
    assert types_seen.count("study") == 2  # 空 session 被跳过
    assert "起床" in [e["content"] for e in events]
    lunch = next(e for e in events if e["content"] == "吃了午餐")
    assert lunch["importance"] == 0.2


def test_build_structured_events_from_analyzed_fragments():
    frags = [
        {"text": "他起床了", "state_event": "WAKE_UP", "importance": 0.1, "category": "life"},
        {"text": "聊得很开心", "state_event": "NONE", "importance": 0.8, "topics": ["日常"]},
        {"text": "无关紧要", "state_event": "NONE", "importance": 0.1},
    ]
    events = pe._build_structured_events({}, frags)
    assert len(events) == 2  # 低重要度的普通片段被丢弃
    state_event = next(e for e in events if e["type"] == "wake_up")
    assert state_event["importance"] == 0.4  # max(0.3, 0.1 + 0.3)
    chat_event = next(e for e in events if e["type"] == "chat")
    assert chat_event["topics"] == ["日常"]


# ---------------------------------------------------------------- LLM 日记


def test_generate_diary_with_llm_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", False)
    result = asyncio.run(
        pe._generate_diary_with_llm(
            dt=_DATE,
            persona_name=_PERSONA,
            portrait_text="",
            events=[],
            fragments=[],
            highlights=[],
            study_text="",
        )
    )
    assert result is None


def _llm_kwargs():
    return dict(
        dt=_DATE,
        persona_name=_PERSONA,
        portrait_text="画像",
        events=[{"content": "起床"}],
        fragments=["片段"],
        highlights=["亮点"],
        study_text="学习",
    )


def test_generate_diary_with_llm_missing_module(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    _install_llm_modules(monkeypatch, llm=None)
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) is None


def test_generate_diary_with_llm_success_dict_response(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    llm = _FakeLLM(response={"status": "success", "response": "  今天很充实  "})
    _install_llm_modules(monkeypatch, llm=llm, journal_model="model-x")
    result = asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs()))
    assert result == "今天很充实"
    assert llm.calls[0][1]["model_path"] == "model-x"
    assert llm.calls[0][0][0]["role"] == "user"


def test_generate_diary_with_llm_failed_dict_response(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    _install_llm_modules(monkeypatch, llm=_FakeLLM(response={"status": "error"}))
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) is None


def test_generate_diary_with_llm_plain_string_response(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    _install_llm_modules(monkeypatch, llm=_FakeLLM(response=" 纯文本日记 "))
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) == "纯文本日记"


def test_generate_diary_with_llm_empty_response(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    _install_llm_modules(monkeypatch, llm=_FakeLLM(response=None))
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) is None


def test_generate_diary_with_llm_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)
    _install_llm_modules(monkeypatch, llm=_FakeLLM(exc=RuntimeError("网络断了")))
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) is None


def test_generate_diary_with_llm_model_hint_fallbacks(monkeypatch):
    monkeypatch.setattr(pe, "_LLM_DIARY_ENABLED", True)

    # get_journal_model 抛错 → 落回空串
    llm = _FakeLLM(response="ok")
    _install_llm_modules(monkeypatch, llm=llm, model_raises=True)
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) == "ok"
    assert llm.calls[-1][1]["model_path"] == ""

    # get_journal_model 返回空 → 用 settings.model.journal_model_hint
    llm2 = _FakeLLM(response="ok")
    _install_llm_modules(monkeypatch, llm=llm2, journal_model="")
    assert asyncio.run(pe._generate_diary_with_llm(**_llm_kwargs())) == "ok"
    assert llm2.calls[-1][1]["model_path"] == "fallback-hint"


# ---------------------------------------------------------------- _build_final_diary


def test_build_final_diary_returns_none_without_fragments():
    entry, used = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[],
            daily_summary=None,
            study_summary={},
        )
    )
    assert entry is None
    assert used == []


def test_build_final_diary_returns_none_when_no_material(monkeypatch):
    monkeypatch.setattr(pe, "_analyze_fragments_batch", _noop_batch)
    entry, used = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[{"content": "今天天气不错"}],
            daily_summary=None,
            study_summary={},
            daily_record=None,
            use_bert_analysis=False,
        )
    )
    assert entry is None
    assert used == []


async def _noop_batch(fragments, max_count=12):
    return []


def test_build_final_diary_legacy_path_uses_fragments(monkeypatch):
    monkeypatch.setattr(pe, "_analyze_fragments_batch", _noop_batch)
    entry, used = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[{"content": "今天天气不错"}],
            daily_summary=None,
            study_summary={},
            daily_record={"mood": "开心"},
            use_bert_analysis=False,
        )
    )
    assert used == ["今天天气不错"]
    assert entry["generation_method"] == "merged_daily_summary_template"
    assert entry["analysis_source"] == "legacy"
    assert "关键片段" in entry["content"]
    assert entry["id"] == "final_20260823_Aveline"


def test_build_final_diary_bert_path_renders_all_sections(monkeypatch):
    async def _fake_batch(fragments, max_count=12):
        return [
            {"text": f, "category": "chat", "topics": ["日常"],
             "importance": 0.5, "state_event": "NONE"}
            for f in fragments[:max_count]
        ]

    monkeypatch.setattr(pe, "_analyze_fragments_batch", _fake_batch)
    record = {
        "sleep_cycle": {"wakeup": "07:00"},
        "meals": [{"type": "breakfast", "content": "牛奶", "time": "07:20"}],
        "mood": "开心",
    }
    summary = DailySummary(date="2026-08-23", summary="今天过得很充实。")
    entry, used = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[{"content": "今天天气不错"}],
            daily_summary=summary,
            study_summary={"session": {"study_session_count": 1}},
            daily_record=record,
            use_bert_analysis=True,
        )
    )
    assert entry["analysis_source"] == "bert_enhanced"
    content = entry["content"]
    assert "今天整体回顾：今天过得很充实。" in content
    assert "今日生活画像：" in content
    assert "今日事件：" in content
    assert "重要片段：" in content
    assert "学习方面：完成1次学习记录。" in content
    assert entry["structured_events"]


def test_build_final_diary_skips_low_importance_fragments(monkeypatch):
    async def _fake_batch(fragments, max_count=12):
        return [
            {"text": f, "category": "chat", "topics": [],
             "importance": 0.1, "state_event": "NONE"}
            for f in fragments
        ]

    monkeypatch.setattr(pe, "_analyze_fragments_batch", _fake_batch)
    entry, _ = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[{"content": "今天天气不错"}],
            daily_summary=DailySummary(date="2026-08-23", summary="还不错"),
            study_summary={},
            daily_record=None,
            use_bert_analysis=True,
        )
    )
    # 有 analyzed_fragments 但都不重要 → 既不出「重要片段」也不回退到「关键片段」
    assert "重要片段" not in entry["content"]
    assert "关键片段" not in entry["content"]


def test_build_final_diary_dedups_and_filters_event_types(monkeypatch):
    # 直接 stub 结构化事件，专门验证「去重 + 非生活类事件按重要度过滤」两段逻辑
    monkeypatch.setattr(
        pe,
        "_build_structured_events",
        lambda record, frags: [
            {"type": "custom", "content": "应被跳过", "importance": 0.1},
            {"type": "custom", "content": "应被保留", "importance": 0.9},
            {"type": "custom", "content": "应被保留", "importance": 0.9},
            {"type": "meal", "content": "早餐吃了牛奶", "importance": 0.2},
        ],
    )
    entry, _ = asyncio.run(
        pe._build_final_diary(
            dt=_DATE,
            persona_name=_PERSONA,
            diary_entries=[{"content": "今天天气不错"}],
            daily_summary=None,
            study_summary={},
            daily_record=None,
            use_bert_analysis=False,
        )
    )
    content = entry["content"]
    assert "应被跳过" not in content
    assert content.count("应被保留") == 1
    assert "早餐吃了牛奶" in content


# ---------------------------------------------------------------- _ExportContext


def test_export_context_caches_reads():
    summary = DailySummary(date="2026-08-23", summary="总结")
    storage = _FakeStorage(entries=[_entry()], summaries={"aveline": summary})
    ctx = pe._ExportContext(_DATE, storage)
    assert ctx.date_key == "2026-08-23"

    first = asyncio.run(ctx.entries())
    second = asyncio.run(ctx.entries())
    assert first == second
    assert storage.entry_calls == 1

    assert asyncio.run(ctx.daily_summary()) is summary
    assert asyncio.run(ctx.daily_summary()) is summary
    assert storage.summary_calls == ["aveline"]


def test_export_context_daily_summary_for_scope():
    summary = DailySummary(date="2026-08-23", summary="Ling的总结")
    storage = _FakeStorage(summaries={"ling": summary})
    ctx = pe._ExportContext(_DATE, storage)
    assert asyncio.run(ctx.daily_summary_for_scope("ling")) is summary
    assert storage.summary_calls == ["ling"]


def test_export_context_study_and_daily_record(monkeypatch):
    storage = _FakeStorage()
    ctx = pe._ExportContext(_DATE, storage)
    monkeypatch.setattr(pe, "_load_study_summary", lambda dt: {"vocab": {"new_words": 1}})
    monkeypatch.setattr(pe, "_load_daily_record", lambda key: {"mood": "开心"})

    assert asyncio.run(ctx.study_summary()) == {"vocab": {"new_words": 1}}
    assert asyncio.run(ctx.study_summary()) == {"vocab": {"new_words": 1}}
    assert asyncio.run(ctx.daily_record()) == {"mood": "开心"}
    assert asyncio.run(ctx.daily_record()) == {"mood": "开心"}


def test_export_context_empty_summaries_return_empty_dict(monkeypatch):
    ctx = pe._ExportContext(_DATE, _FakeStorage())
    monkeypatch.setattr(pe, "_load_study_summary", lambda dt: None)
    monkeypatch.setattr(pe, "_load_daily_record", lambda key: None)
    assert asyncio.run(ctx.study_summary()) == {}
    assert asyncio.run(ctx.daily_record()) == {}


# ---------------------------------------------------------------- 学习/生活数据加载


def test_load_study_summary_success(monkeypatch):
    digest = {"session": {"study_session_count": 2}}
    svc = SimpleNamespace(get_study_daily_digest=lambda key: digest)
    mod = types.ModuleType("core.services.study.service")
    mod.get_study_service = lambda: svc
    monkeypatch.setitem(sys.modules, "core.services.study.service", mod)
    assert pe._load_study_summary(_DATE) == digest


def test_load_study_summary_failure_returns_empty(monkeypatch):
    mod = types.ModuleType("core.services.study.service")

    def _raise():
        raise RuntimeError("学习服务不可用")

    mod.get_study_service = _raise
    monkeypatch.setitem(sys.modules, "core.services.study.service", mod)
    assert pe._load_study_summary(_DATE) == {}


def test_load_study_summary_none_digest(monkeypatch):
    svc = SimpleNamespace(get_study_daily_digest=lambda key: None)
    mod = types.ModuleType("core.services.study.service")
    mod.get_study_service = lambda: svc
    monkeypatch.setitem(sys.modules, "core.services.study.service", mod)
    assert pe._load_study_summary(_DATE) == {}


def test_load_daily_record_success_and_failure(monkeypatch):
    record = {"mood": "开心"}
    mgr = SimpleNamespace(get_record=lambda key: record)
    mod = types.ModuleType("core.services.daily.manager")
    mod.get_daily_manager = lambda: mgr
    monkeypatch.setitem(sys.modules, "core.services.daily.manager", mod)
    assert pe._load_daily_record("2026-08-23") == record

    def _raise():
        raise RuntimeError("daily 服务不可用")

    mod2 = types.ModuleType("core.services.daily.manager")
    mod2.get_daily_manager = _raise
    monkeypatch.setitem(sys.modules, "core.services.daily.manager", mod2)
    assert pe._load_daily_record("2026-08-23") == {}


# ---------------------------------------------------------------- 服务构造与迁移


def test_service_init_creates_scope_roots(export_env):
    svc = _make_service(export_env)
    assert set(svc._scope_roots) == set(_DIARY_IDS)
    for path in svc._scope_roots.values():
        assert path.is_dir()
    assert svc._migrated is False


def test_ensure_migration_is_idempotent(export_env):
    svc = _make_service(export_env)
    svc._ensure_migration()
    assert svc._migrated is True
    # 第二次调用直接返回，不再重建目录
    svc._ensure_migration()
    assert svc._migrated is True


def test_ensure_migration_skips_absent_and_file_sources(export_env):
    svc = _make_service(export_env)
    aveline_root = svc._scope_roots["aveline"]
    # canonical 名字 'aveline' 与自身相等 → 跳过；
    # 别名位置放的是文件而不是目录 → 跳过（不能被当成迁移源）
    alias_file = aveline_root / get_diary_persona_name("aveline")
    alias_file.write_text("我是文件不是目录", encoding="utf-8")

    svc._ensure_migration()

    assert (aveline_root / "aveline").is_dir()
    assert alias_file.is_file()


def test_ensure_migration_moves_children_and_tolerates_conflicts(export_env):
    svc = _make_service(export_env)
    aveline_root = svc._scope_roots["aveline"]

    # 别名目录（中文名·Aveline）：目标已存在的 child 跳过，剩余 child 迁移后源目录无法删除
    alias_dir = aveline_root / get_diary_persona_name("aveline")
    canonical_dir = aveline_root / "aveline"
    alias_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir.mkdir(parents=True, exist_ok=True)
    (alias_dir / "a.json").write_text("{}", encoding="utf-8")
    (canonical_dir / "a.json").write_text("{}", encoding="utf-8")
    (alias_dir / "b.json").write_text("{}", encoding="utf-8")

    svc._ensure_migration()

    assert (canonical_dir / "b.json").is_file()
    assert (canonical_dir / "a.json").read_text(encoding="utf-8") == "{}"
    assert alias_dir.is_dir()  # 还有 a.json，删不掉


def test_ensure_migration_continues_when_one_child_fails(export_env, monkeypatch):
    """单个文件迁移失败不能中断整个迁移流程。"""
    svc = _make_service(export_env)
    aveline_root = svc._scope_roots["aveline"]
    alias_dir = aveline_root / get_diary_persona_name("aveline")
    alias_dir.mkdir(parents=True, exist_ok=True)
    (alias_dir / "bad.json").write_text("{}", encoding="utf-8")
    (alias_dir / "good.json").write_text("{}", encoding="utf-8")

    original_replace = Path.replace

    def _flaky_replace(self, target):
        if self.name == "bad.json":
            raise OSError("模拟迁移失败")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _flaky_replace)
    svc._ensure_migration()

    canonical_dir = aveline_root / "aveline"
    assert (canonical_dir / "good.json").is_file()
    assert (alias_dir / "bad.json").is_file()


# ---------------------------------------------------------------- _write_exports / 导出入口


def _seed(export_env, entries=None, summaries=None):
    export_env.storage.entries_data = list(entries or [])
    export_env.storage.summaries = dict(summaries or {})
    return export_env.storage


def test_write_exports_groups_personas_by_scope(export_env):
    summary = DailySummary(date="2026-08-23", summary="今天不错")
    _seed(
        export_env,
        entries=[_entry("Aveline：今天去公园散步了"), _entry("Ye：我在看书", source="ye")],
        summaries={"aveline": summary},
    )
    svc = _make_service(export_env)
    result = asyncio.run(
        svc._write_exports(
            dt=_DATE,
            entries=export_env.storage.entries_data,
            daily_summary=summary,
            study_summary={},
            daily_record={"mood": "开心"},
            persona_hint=None,
        )
    )
    assert result["date"] == "2026-08-23"
    # 未注册角色（Ling/ling）即使在 DEFAULT_PERSONAS 里也被过滤掉
    assert "Ling" in DEFAULT_PERSONAS
    assert get_persona_scope("Ling") not in svc._scope_roots
    assert "Ling" not in result["personas"]
    assert "Aveline" in result["personas"]
    assert result["personas"]["Aveline"]["scope"] == "aveline"
    assert (svc._scope_roots["aveline"] / "index.json").is_file()
    index = json.loads((svc._scope_roots["aveline"] / "index.json").read_text(encoding="utf-8"))
    assert index["date"] == "2026-08-23"
    assert "Aveline" in index["personas"]


def test_write_exports_adds_persona_hint(export_env):
    _seed(export_env, entries=[])
    svc = _make_service(export_env)
    result = asyncio.run(
        svc._write_exports(
            dt=_DATE,
            entries=[],
            daily_summary=None,
            study_summary={},
            persona_hint="Aveline",
        )
    )
    assert "Aveline" in result["personas"]
    assert result["personas"]["Aveline"]["diary_entries"] == 0


def test_write_exports_records_persona_failures(export_env):
    _seed(export_env, entries=[])
    svc = _make_service(export_env)

    async def _boom(self, **kwargs):
        raise RuntimeError("导出炸了")

    with mock.patch.object(pe.PersonaJournalExportService, "_export_persona", _boom):
        result = asyncio.run(
            svc._write_exports(
                dt=_DATE,
                entries=[],
                daily_summary=None,
                study_summary={},
            )
        )
    assert result["personas"] == {}
    index = json.loads((svc._scope_roots["aveline"] / "index.json").read_text(encoding="utf-8"))
    assert index["personas"] == {}


def test_export_date_uses_active_persona_hint(export_env):
    summary = DailySummary(date="2026-08-23", summary="今天不错")
    _seed(export_env, entries=[_entry()], summaries={"aveline": summary})
    svc = _make_service(export_env)
    result = asyncio.run(svc.export_date("2026-08-23"))
    assert result["date"] == "2026-08-23"
    assert "Aveline" in result["personas"]
    # 每个 scope 都读一次专属 daily_summary
    assert set(export_env.storage.summary_calls) >= set(_DIARY_IDS)


def test_export_after_entry_infers_persona_from_entry(export_env):
    _seed(export_env, entries=[_entry("Ling：今天写了很多作业")])
    svc = _make_service(export_env)
    entry = _entry("Ling：今天写了很多作业")
    result = asyncio.run(svc.export_after_entry(entry, _DATE))
    assert "Ling" not in result["personas"]  # ling 未注册，被过滤
    assert "Aveline" in result["personas"]


def test_export_learning_summary_passes_summary_data(export_env):
    _seed(export_env, entries=[])
    svc = _make_service(export_env)
    result = asyncio.run(
        svc.export_learning_summary(
            _DATE, {"session": {"study_session_count": 3}, "vocab": {"new_words": 5}}
        )
    )
    assert result["date"] == "2026-08-23"
    assert "Aveline" in result["personas"]


# ---------------------------------------------------------------- _export_persona


def test_export_persona_writes_diary_for_registered_role(export_env):
    svc = _make_service(export_env)
    summary = DailySummary(date="2026-08-23", summary="今天不错")
    entries = [_entry("Aveline：今天去公园散步了")]
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name=_PERSONA,
            entries=entries,
            daily_summary=summary,
            aveline_daily_summary=None,
            study_summary={"session": {"study_session_count": 1}},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    persona_dir = Path(result["path"])
    assert result["scope"] == "aveline"
    assert result["diary_entries"] == 1
    diary = json.loads((persona_dir / "diary.json").read_text(encoding="utf-8"))
    assert diary["is_finalized"] is True
    assert diary["entry_count"] == 1
    assert diary["note"] == ""
    # aveline 不是 ling persona → 不写 learning_summary.json
    assert not (persona_dir / "learning_summary.json").exists()
    index = json.loads((persona_dir / "index.json").read_text(encoding="utf-8"))
    assert index["files"] == {"diary": "diary.json"}


def test_export_persona_ling_branch_and_aveline_summary_fallback(export_env):
    svc = _make_service(export_env)
    fallback = DailySummary(date="2026-08-23", summary="Aveline 的总结")
    entries = [_entry("Ling：今天写了很多作业")]
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name="Ling",
            entries=entries,
            daily_summary=None,
            aveline_daily_summary=fallback,
            study_summary={},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    persona_dir = Path(result["path"])
    assert result["scope"] == "ling"
    assert "Ling" in LING_PERSONAS
    assert (persona_dir / "learning_summary.json").is_file()
    index = json.loads((persona_dir / "index.json").read_text(encoding="utf-8"))
    assert index["files"]["learning_summary"] == "learning_summary.json"
    learning = json.loads((persona_dir / "learning_summary.json").read_text(encoding="utf-8"))
    assert learning["daily_summary"]["summary"] == "Aveline 的总结"


def test_export_persona_without_material_marks_not_finalized(export_env):
    """没有可用素材时不生成成品日记；ling 角色仍会写 learning_summary。"""
    svc = _make_service(export_env)
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name="Ling",
            entries=[],
            daily_summary=None,
            aveline_daily_summary=None,
            study_summary={},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    persona_dir = Path(result["path"])
    diary = json.loads((persona_dir / "diary.json").read_text(encoding="utf-8"))
    assert result["diary_entries"] == 0
    assert diary["is_finalized"] is False
    assert diary["note"] == "今天暂无可用素材，尚未生成成品日记。"
    assert diary["entries"] == []
    assert diary["source_counts"] == {"diary_fragments": 0, "used_fragments": 0}
    learning = json.loads((persona_dir / "learning_summary.json").read_text(encoding="utf-8"))
    assert learning["daily_summary"] is None


def test_export_persona_ling_entries_without_inferred_persona(export_env):
    """ling 角色要兜住「推断不出角色」的条目（历史数据兜底）。"""
    svc = _make_service(export_env)
    entries = [_entry("今天写了很多作业，好累", source="unknown-src")]
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name="Ling",
            entries=entries,
            daily_summary=None,
            aveline_daily_summary=None,
            study_summary={},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    assert result["diary_entries"] == 1


def test_export_persona_mentions_persona_without_source_match(export_env):
    """条目未推断出角色、但正文里出现了角色名 → 仍归属该角色。"""
    svc = _make_service(export_env)
    entries = [_entry("今天和Aveline：一起吃了饭", source="unknown-src")]
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name=_PERSONA,
            entries=entries,
            daily_summary=None,
            aveline_daily_summary=None,
            study_summary={},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    assert result["diary_entries"] == 1


def test_export_persona_ignores_non_diary_entries(export_env):
    svc = _make_service(export_env)
    entries = [
        _entry("Aveline：今天去公园散步了"),
        _entry("Aveline：自动总结", entry_type="daily_summary"),
        _entry("Aveline：系统条目", source="system", thought="auto_generated_daily_summary"),
        _entry("Aveline：圈子条目", thought="dual_role_background_circle"),
    ]
    result = asyncio.run(
        svc._export_persona(
            dt=_DATE,
            persona_name=_PERSONA,
            entries=entries,
            daily_summary=None,
            aveline_daily_summary=None,
            study_summary={},
            daily_record=None,
            date_key="2026-08-23",
        )
    )
    diary = json.loads((Path(result["path"]) / "diary.json").read_text(encoding="utf-8"))
    assert diary["source_counts"]["diary_fragments"] == 1


# ---------------------------------------------------------------- 单例入口


def test_get_persona_journal_export_service_returns_singleton(monkeypatch):
    created = []

    class _Svc:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(pe, "_service_instance", None)
    monkeypatch.setattr(pe, "PersonaJournalExportService", _Svc)

    first = pe.get_persona_journal_export_service()
    second = pe.get_persona_journal_export_service()
    assert first is second
    assert len(created) == 1


def test_get_persona_journal_export_service_double_check(monkeypatch):
    sentinel = object()

    class _Lock:
        def __enter__(self):
            # 模拟「等锁期间别的线程已经建好实例」
            pe._service_instance = sentinel
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pe, "_service_instance", None)
    monkeypatch.setattr(pe, "_service_lock", _Lock())
    assert pe.get_persona_journal_export_service() is sentinel
