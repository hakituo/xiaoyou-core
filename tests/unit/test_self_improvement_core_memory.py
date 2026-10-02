"""MEMORY.md 核心记忆管理器（CoreMemory）单元测试。

覆盖目标：``core/services/self_improvement/core_memory.py`` 的分支与边界。

设计原则：
- 所有日期都注入固定的「今天」（2026/08/10 12:00 +08:00），不依赖真实系统时间；
- 文件 IO 全部落在 ``tmp_path``，绝不触碰仓库真实数据目录；
- embedding / 向量库一律用 ``sys.modules`` 注入的假模块替身，绝不加载真实模型；
- 外部 LLM 合并器用假的协程函数替换，绝不联网；
- 不做任何耗时 / 随机 / sleep 断言，避免 flaky。
"""
from __future__ import annotations

import asyncio
import datetime
import math
import sys
import types

import pytest

from core.services.self_improvement import core_memory as coremem
from core.services.self_improvement.core_memory import CoreMemory
from core.services.self_improvement.models import (
    MEMORY_MAX_SIZE_BYTES,
    MemorySection,
)

TZ = datetime.timezone(datetime.timedelta(hours=8))
# 固定「今天」：2026/08/10 12:00 +08:00
NOW = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=TZ)
TODAY = "2026-08-10"

PREFERENCES = MemorySection.PREFERENCES
ROLE = MemorySection.ROLE
EXPERIENCE = MemorySection.EXPERIENCE
ACTIVE_TASKS = MemorySection.ACTIVE_TASKS
CORRECTIONS = MemorySection.CORRECTIONS
SUMMARIES = MemorySection.SUMMARIES

ALL_SECTIONS = [PREFERENCES, ROLE, EXPERIENCE, ACTIVE_TASKS, CORRECTIONS, SUMMARIES]


# ----------------------------------------------------------------------
# 替身：embedding 生成器
# ----------------------------------------------------------------------


def _vec_with_sim(sim: float) -> list:
    """返回与 ``[1.0, 0.0]`` 余弦相似度恰为 ``sim`` 的二维单位向量。"""
    return [sim, math.sqrt(max(0.0, 1.0 - sim * sim))]


class _FakeEmbeddingGenerator:
    """可控的 embedding 生成器替身（不加载任何真实模型）。"""

    def __init__(self, vectors=None, fail_texts=None, hash_fallback=False):
        self.vectors = dict(vectors or {})
        self.fail_texts = set(fail_texts or ())
        self._use_hash_fallback = hash_fallback
        self.calls = []

    def generate_embedding(self, text):
        self.calls.append(text)
        if text in self.fail_texts:
            raise RuntimeError("embedding 计算失败")
        return list(self.vectors.get(text, [1.0, 0.0]))


class _FakeEmbeddingGeneratorClass:
    """假 ``EmbeddingGenerator``：只提供被用到的 cosine_similarity。"""

    @staticmethod
    def cosine_similarity(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def _install_fake_embedding(monkeypatch, gen=None, get_raises=False):
    """把假的 ``memory.embedding_generator`` 注入 sys.modules，绕开真实模型加载。"""
    mod = types.ModuleType("memory.embedding_generator")
    mod.EmbeddingGenerator = _FakeEmbeddingGeneratorClass
    if get_raises:
        def _boom():
            raise RuntimeError("模型不可用")
        mod.get_embedding_generator = _boom
    else:
        mod.get_embedding_generator = lambda: gen
    monkeypatch.setitem(sys.modules, "memory.embedding_generator", mod)
    return mod


# ----------------------------------------------------------------------
# 替身：JournalService
# ----------------------------------------------------------------------


class _FakeDaily:
    """带 summary 属性的假日记摘要对象。"""

    def __init__(self, summary):
        self.summary = summary


def _install_fake_journal(
    monkeypatch,
    data,
    scope="aveline",
    fail=False,
    raises_on=None,
    calls=None,
):
    """注入假的 JournalService 与活跃角色解析函数。"""
    import core.services.journal.service as journal_mod
    import core.utils.data_paths as data_paths_mod

    class _Storage:
        async def get_daily_summary(self, date_str, scope=None):
            if calls is not None:
                calls.append((date_str, scope))
            if raises_on and date_str in raises_on:
                raise RuntimeError("读取日记失败")
            return data.get(date_str)

    class _JournalService:
        def __init__(self, *args, **kwargs):
            if fail:
                raise RuntimeError("JournalService 不可用")
            self.storage = _Storage()

    monkeypatch.setattr(journal_mod, "JournalService", _JournalService)
    monkeypatch.setattr(
        data_paths_mod, "_resolve_scope_from_active_persona", lambda: scope
    )


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    """返回一个数据目录隔离在 tmp_path、时钟固定为 2026/08/10 的管理器。"""
    monkeypatch.setattr(coremem, "get_current_time", lambda: NOW)
    monkeypatch.setattr(coremem, "today_str", lambda: TODAY)
    return CoreMemory(tmp_path / "scope_data", scope="user")


def _preset(cm, sections):
    """直接注入内存分区，跳过文件加载。"""
    cm._loaded = True
    cm._sections = {s: [] for s in ALL_SECTIONS}
    cm._sections.update(sections)
    return cm


# ----------------------------------------------------------------------
# 1. 关键词桶
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,bucket",
    [
        ("回复消息要简短", "reply_style"),
        ("不吃海鲜，忌口", "diet"),
        ("住在重庆某城区", "location"),
        ("少用表情 emoji", "emoji_style"),
        ("今天天气不错", "other"),
    ],
)
def test_get_keyword_bucket(text, bucket):
    """每个关键词桶都能命中，未命中时返回 other。"""
    assert coremem._get_keyword_bucket(text) == bucket


# ----------------------------------------------------------------------
# 2. 初始化 / 加载 / 保存
# ----------------------------------------------------------------------


def test_ensure_initialized_creates_template_and_is_idempotent(cm):
    """首次初始化创建 MEMORY.md 与归档目录，重复调用不覆盖已有内容。"""
    cm.ensure_initialized()
    assert cm._memory_file.is_file()
    assert cm._archive_dir.is_dir()
    text = cm._memory_file.read_text(encoding="utf-8")
    assert "用户偏好" in text

    cm.ensure_initialized()
    assert cm._memory_file.read_text(encoding="utf-8") == text


def test_load_sync_creates_file_when_missing(cm):
    """MEMORY.md 不存在时先初始化，再解析出全空分区。"""
    sections = cm._load_sync()
    assert cm._memory_file.exists()
    assert cm._loaded is True
    assert set(sections) == set(ALL_SECTIONS)
    assert all(v == [] for v in sections.values())


def test_load_sync_parses_headers_items_and_skips_noise(cm):
    """解析分区标题、条目行，跳过注释行与空行。"""
    cm._base_dir.mkdir(parents=True, exist_ok=True)
    cm._memory_file.write_text(
        "# MEMORY.md - 核心记忆（自动加载）\n"
        "\n"
        "## 🔒 用户偏好（永久保留）\n"
        "喜欢简短回复\n"
        "# 这是注释，应被跳过\n"
        "\n"
        "## 📝 业务经验（长期保留，≤15条）\n"
        "经验一\n",
        encoding="utf-8",
    )
    sections = cm._load_sync()
    assert sections[PREFERENCES] == ["喜欢简短回复"]
    assert sections[EXPERIENCE] == ["经验一"]
    assert sections[ROLE] == []


def test_load_sync_returns_empty_when_read_fails(tmp_path):
    """MEMORY.md 路径存在但不可读（是目录）时，返回全空分区而不抛异常。"""
    base = tmp_path / "broken"
    (base / "MEMORY.md").mkdir(parents=True)
    m = CoreMemory(base)
    sections = m._load_sync()
    assert all(v == [] for v in sections.values())
    # 读取失败走提前 return，不会标记为已加载（下次调用仍会重试）
    assert m._loaded is False


def test_load_and_save_async_roundtrip(cm):
    """异步 save/load 能往返保留条目，并清空 embedding 缓存。"""
    _preset(cm, {PREFERENCES: ["偏好甲"], EXPERIENCE: ["经验乙"]})
    cm._embeddings_cache[PREFERENCES] = [[1.0, 0.0]]
    asyncio.run(cm.save())
    assert cm._memory_file.exists()

    fresh = CoreMemory(cm._base_dir)
    sections = asyncio.run(fresh.load())
    assert sections[PREFERENCES] == ["偏好甲"]
    assert sections[EXPERIENCE] == ["经验乙"]
    assert fresh._embeddings_cache == {}


def test_save_sync_swallows_write_error(cm, monkeypatch):
    """落盘失败只记日志，不向上抛异常。"""
    def _boom(*args, **kwargs):
        raise OSError("磁盘写满")

    monkeypatch.setattr(coremem, "safe_write_text", _boom)
    _preset(cm, {PREFERENCES: ["条目"]})
    asyncio.run(cm.save())
    assert not cm._memory_file.exists()


# ----------------------------------------------------------------------
# 3. embedding 相关私有方法
# ----------------------------------------------------------------------


def test_get_embedding_generator_lazy_loads_and_caches(cm, monkeypatch):
    """首次调用加载生成器，之后不再重复加载。"""
    sentinel = _FakeEmbeddingGenerator()
    _install_fake_embedding(monkeypatch, gen=sentinel)
    assert cm._get_embedding_generator() is sentinel
    assert cm._embedding_checked is True

    # 第二次调用走「已检查」分支，仍返回同一实例
    assert cm._get_embedding_generator() is sentinel


def test_get_embedding_generator_swallows_failure(cm, monkeypatch):
    """生成器加载失败时降级为 None，不抛异常。"""
    _install_fake_embedding(monkeypatch, get_raises=True)
    assert cm._get_embedding_generator() is None
    assert cm._embedding_gen is None
    assert cm._embedding_checked is True


def test_is_hash_fallback_variants(cm):
    """无生成器 / 有生成器时分别返回正确的降级标记。"""
    cm._embedding_gen = None
    assert cm._is_hash_fallback() is True

    cm._embedding_gen = _FakeEmbeddingGenerator(hash_fallback=True)
    assert cm._is_hash_fallback() is True

    cm._embedding_gen = _FakeEmbeddingGenerator(hash_fallback=False)
    assert cm._is_hash_fallback() is False


def test_compute_embedding_paths(cm):
    """无生成器 / 生成器报错 / 正常计算 三条路径。"""
    cm._embedding_checked = True
    cm._embedding_gen = None
    assert cm._compute_embedding("任意") is None

    cm._embedding_gen = _FakeEmbeddingGenerator(fail_texts={"任意"})
    assert cm._compute_embedding("任意") is None

    cm._embedding_gen = _FakeEmbeddingGenerator(vectors={"任意": [0.1, 0.2]})
    assert cm._compute_embedding("任意") == [0.1, 0.2]


def test_invalidate_section_cache(cm):
    """清缓存对存在的分区生效，对不存在的分区也不报错。"""
    cm._embeddings_cache[PREFERENCES] = [[1.0, 0.0]]
    cm._invalidate_section_cache(PREFERENCES)
    assert PREFERENCES not in cm._embeddings_cache
    cm._invalidate_section_cache(ROLE)
    assert ROLE not in cm._embeddings_cache


# ----------------------------------------------------------------------
# 4. 语义去重
# ----------------------------------------------------------------------


def test_find_semantic_duplicate_empty_section(cm):
    """分区为空时直接判定不重复。"""
    cm._sections = {}
    assert cm._find_semantic_duplicate(PREFERENCES, "任意", [1.0, 0.0]) == (False, -1)


def test_find_semantic_duplicate_exact_match_short_circuits(cm, monkeypatch):
    """全等命中时不需要 embedding 模块（提前返回）。"""
    _preset(cm, {PREFERENCES: ["条目甲", "条目乙"]})
    assert cm._find_semantic_duplicate(PREFERENCES, "条目乙", None) == (True, 1)


def test_find_semantic_duplicate_new_embedding_none(cm):
    """新条目 embedding 不可用且无全等匹配时，判定不重复。"""
    _preset(cm, {PREFERENCES: ["条目甲"]})
    assert cm._find_semantic_duplicate(PREFERENCES, "条目乙", None) == (False, -1)


def test_find_semantic_duplicate_import_failure(cm, monkeypatch):
    """embedding 模块不可导入时降级为不重复。"""
    monkeypatch.setitem(sys.modules, "memory.embedding_generator", None)
    _preset(cm, {PREFERENCES: ["条目甲"]})
    assert cm._find_semantic_duplicate(PREFERENCES, "条目乙", [1.0, 0.0]) == (False, -1)


def test_find_semantic_duplicate_hits_with_normal_threshold(cm, monkeypatch):
    """不同关键词桶用严格阈值（0.85），相似度达标即命中。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(vectors={"条目甲": [1.0, 0.0]})
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert cm._find_semantic_duplicate(
        PREFERENCES, "条目乙", _vec_with_sim(0.9)
    ) == (True, 0)


def test_find_semantic_duplicate_misses_below_threshold(cm, monkeypatch):
    """相似度低于阈值时判定不重复。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(vectors={"条目甲": [1.0, 0.0]})
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert cm._find_semantic_duplicate(
        PREFERENCES, "条目乙", _vec_with_sim(0.5)
    ) == (False, -1)


def test_find_semantic_duplicate_same_bucket_uses_loose_threshold(cm, monkeypatch):
    """同关键词桶用宽松阈值（0.65），0.7 相似度即可命中。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(vectors={"回复要简短": [1.0, 0.0]})
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["回复要简短"]})

    assert cm._find_semantic_duplicate(
        PREFERENCES, "回复要精炼", _vec_with_sim(0.7)
    ) == (True, 0)


def test_find_semantic_duplicate_hash_fallback_uses_strict_threshold(cm, monkeypatch):
    """hash fallback 模式阈值提高到 0.95，0.9 相似度不再命中。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(
        vectors={"条目甲": [1.0, 0.0]}, hash_fallback=True
    )
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert cm._find_semantic_duplicate(
        PREFERENCES, "条目乙", _vec_with_sim(0.9)
    ) == (False, -1)


def test_find_semantic_duplicate_skips_when_cache_rebuild_incomplete(cm, monkeypatch):
    """重建缓存时任一旧条目算不出 embedding，就放弃语义判定且不写缓存。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(fail_texts={"条目甲"})
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert cm._find_semantic_duplicate(
        PREFERENCES, "条目乙", _vec_with_sim(0.99)
    ) == (False, -1)
    assert PREFERENCES not in cm._embeddings_cache


# ----------------------------------------------------------------------
# 5. add_item
# ----------------------------------------------------------------------


def test_add_item_skips_not_to_save_items(cm):
    """NOT-to-save 条目直接丢弃，且不触发加载 / 落盘。"""
    assert asyncio.run(cm.add_item(PREFERENCES, "import os 的用法")) is False
    assert cm._loaded is False
    assert not cm._memory_file.exists()


def test_add_item_logs_not_to_save_when_debug_enabled(cm, monkeypatch):
    """core_memory 调试开关打开时，NOT-to-save 跳过会额外记日志。"""
    monkeypatch.setattr(coremem, "is_debug_enabled", lambda module: True)
    assert asyncio.run(cm.add_item(PREFERENCES, "def foo(): 的写法")) is False
    assert cm._loaded is False


def test_add_item_exact_duplicate_returns_false(cm):
    """全等重复条目第二次写入返回 False。"""
    cm._embedding_checked = True
    cm._embedding_gen = None
    assert asyncio.run(cm.add_item(PREFERENCES, "喜欢简短回复")) is True
    assert asyncio.run(cm.add_item(PREFERENCES, "喜欢简短回复")) is False
    assert cm._sections[PREFERENCES] == ["喜欢简短回复"]


def test_add_item_replaces_semantically_duplicate(cm, monkeypatch):
    """语义重复但不全等时，用新表述原地替换并返回 True。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(
        vectors={"条目甲": [1.0, 0.0], "条目乙": _vec_with_sim(0.9)}
    )
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert asyncio.run(cm.add_item(PREFERENCES, "条目乙")) is True
    assert cm._sections[PREFERENCES] == ["条目乙"]
    assert "条目乙" in cm._memory_file.read_text(encoding="utf-8")


def test_add_item_appends_and_extends_embedding_cache(cm, monkeypatch):
    """追加新条目时，若缓存与条目一一对应则直接追加，不整体重建。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(
        vectors={"条目甲": [1.0, 0.0], "条目乙": [0.0, 1.0]}
    )
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})
    cm._embeddings_cache[PREFERENCES] = [[1.0, 0.0]]

    assert asyncio.run(cm.add_item(PREFERENCES, "条目乙")) is True
    assert cm._sections[PREFERENCES] == ["条目甲", "条目乙"]
    assert len(cm._embeddings_cache[PREFERENCES]) == 2


def test_add_item_invalidates_stale_cache_when_embedding_partial(cm, monkeypatch):
    """旧条目 embedding 算不出来时缓存不可用，追加后清掉缓存。"""
    _install_fake_embedding(monkeypatch, gen=None)
    gen = _FakeEmbeddingGenerator(
        vectors={"条目乙": [1.0, 0.0]}, fail_texts={"条目甲"}
    )
    cm._embedding_gen = gen
    cm._embedding_checked = True
    _preset(cm, {PREFERENCES: ["条目甲"]})

    assert asyncio.run(cm.add_item(PREFERENCES, "条目乙")) is True
    assert cm._sections[PREFERENCES] == ["条目甲", "条目乙"]
    assert PREFERENCES not in cm._embeddings_cache


def test_add_item_trims_over_limit_and_archives(cm):
    """超出分区上限时移除最旧条目并写入归档文件。"""
    cm._embedding_checked = True
    cm._embedding_gen = None
    old_items = [f"任务{i}" for i in range(10)]
    _preset(cm, {ACTIVE_TASKS: list(old_items)})

    assert asyncio.run(cm.add_item(ACTIVE_TASKS, "任务10")) is True

    items = cm._sections[ACTIVE_TASKS]
    assert len(items) == 10
    assert items[-1] == "任务10"
    assert "任务0" not in items

    archive = cm._archive_dir / f"active_tasks_{TODAY}.md"
    assert archive.exists()
    assert "任务0" in archive.read_text(encoding="utf-8")


def test_add_item_does_not_trim_unlimited_section(cm):
    """上限为 0（永久保留）的分区不做淘汰。"""
    cm._embedding_checked = True
    cm._embedding_gen = None
    _preset(cm, {PREFERENCES: [f"偏好{i}" for i in range(12)]})

    assert asyncio.run(cm.add_item(PREFERENCES, "偏好12")) is True
    assert len(cm._sections[PREFERENCES]) == 13
    assert not cm._archive_dir.exists()


# ----------------------------------------------------------------------
# 6. remove / update / get / search
# ----------------------------------------------------------------------


def test_remove_item_hit_miss_and_missing_section(cm):
    """移除命中、移除未命中、分区不存在三种情况。"""
    _preset(cm, {PREFERENCES: ["甲", "乙"]})
    cm._embeddings_cache[PREFERENCES] = [[1.0, 0.0]]

    assert asyncio.run(cm.remove_item(PREFERENCES, "甲")) is True
    assert cm._sections[PREFERENCES] == ["乙"]
    assert PREFERENCES not in cm._embeddings_cache

    assert asyncio.run(cm.remove_item(PREFERENCES, "不存在")) is False
    assert asyncio.run(cm.remove_item(ROLE, "任意")) is False


def test_update_item_hit_and_miss(cm):
    """更新命中时原地替换并清缓存，未命中返回 False。"""
    _preset(cm, {EXPERIENCE: ["旧经验"]})
    cm._embeddings_cache[EXPERIENCE] = [[1.0, 0.0]]

    assert asyncio.run(cm.update_item(EXPERIENCE, "旧经验", "新经验")) is True
    assert cm._sections[EXPERIENCE] == ["新经验"]
    assert EXPERIENCE not in cm._embeddings_cache

    assert asyncio.run(cm.update_item(EXPERIENCE, "没有的", "x")) is False


def test_get_section_and_get_all_return_copies(cm):
    """get_section / get_all 返回副本，外部改动不影响内部状态，且首次调用触发加载。"""
    assert asyncio.run(cm.get_section(PREFERENCES)) == []
    assert cm._loaded is True

    cm._sections[PREFERENCES] = ["条目"]
    got = asyncio.run(cm.get_section(PREFERENCES))
    assert got == ["条目"]
    got.append("外部改动")
    assert cm._sections[PREFERENCES] == ["条目"]

    all_map = asyncio.run(cm.get_all())
    assert all_map[PREFERENCES] == ["条目"]
    all_map[PREFERENCES].append("外部改动2")
    assert cm._sections[PREFERENCES] == ["条目"]


def test_search_matches_case_insensitively(cm):
    """搜索大小写不敏感，可跨分区命中，无结果返回空列表。"""
    _preset(
        cm,
        {
            PREFERENCES: ["喜欢 Python"],
            EXPERIENCE: ["python 性能调优"],
            ROLE: ["温柔"],
        },
    )
    results = asyncio.run(cm.search("python"))
    assert len(results) == 2
    assert {r["section"] for r in results} == {"preferences", "experience"}
    assert asyncio.run(cm.search("不存在的关键词")) == []


def test_lazy_load_branch_of_read_apis(cm):
    """未加载时 get_all / search 会先触发一次加载。"""
    assert cm._loaded is False
    all_map = asyncio.run(cm.get_all())
    assert set(all_map) == set(ALL_SECTIONS)
    assert all(v == [] for v in all_map.values())
    assert cm._loaded is True

    cm._loaded = False
    assert asyncio.run(cm.search("任意")) == []
    assert cm._loaded is True


def test_lazy_load_branch_of_mutating_apis(cm):
    """未加载时 remove_item / update_item 会先触发一次加载。"""
    assert cm._loaded is False
    assert asyncio.run(cm.remove_item(PREFERENCES, "不存在")) is False
    assert cm._loaded is True

    cm._loaded = False
    assert asyncio.run(cm.update_item(PREFERENCES, "不存在", "新值")) is False
    assert cm._loaded is True


def test_lazy_load_branch_of_auto_slim_and_llm_merge(cm, monkeypatch):
    """未加载时 auto_slim / llm_merge_preferences 会先触发一次加载。"""
    import core.services.self_improvement.core_memory_llm_merge as merger

    async def _fake(items, model_hint=None):  # pragma: no cover - 不应被调用
        raise AssertionError("偏好为空时不应调用 LLM 合并")

    monkeypatch.setattr(merger, "llm_merge_preferences", _fake)

    assert cm._loaded is False
    assert asyncio.run(cm.auto_slim()) == {}
    assert cm._loaded is True

    cm._loaded = False
    assert asyncio.run(cm.llm_merge_preferences()) == {
        "skipped": "too_few_items",
        "before": 0,
        "after": 0,
    }
    assert cm._loaded is True


# ----------------------------------------------------------------------
# 7. auto_slim
# ----------------------------------------------------------------------


def test_auto_slim_returns_empty_when_under_limit(cm):
    """文件未超 5KB 时不瘦身。"""
    _preset(cm, {PREFERENCES: ["条目"]})
    cm._base_dir.mkdir(parents=True, exist_ok=True)
    cm._memory_file.write_text("小文件", encoding="utf-8")
    assert cm._memory_file.stat().st_size <= MEMORY_MAX_SIZE_BYTES
    assert asyncio.run(cm.auto_slim()) == {}


def test_auto_slim_returns_empty_when_stat_fails(cm):
    """文件不存在（stat 抛异常）时安全返回空结果。"""
    _preset(cm, {})
    assert asyncio.run(cm.auto_slim()) == {}


def test_auto_slim_removes_stale_and_merges_experience(cm):
    """超限时删除已完成任务 / 已晋升纠正 / 过期摘要，并合并相似经验。"""
    experience = ["甲乙类经验"] * 2 + [
        f"{word}类经验" for word in "一二三四五六七八九十甲乙丙丁戊"
    ]
    assert len(experience) == 17
    _preset(
        cm,
        {
            PREFERENCES: ["喜欢简短回复"],
            ROLE: ["温柔角色"],
            EXPERIENCE: list(experience),
            ACTIVE_TASKS: ["✅ 已完成任务", "[完成] 另一个任务", "进行中任务"],
            CORRECTIONS: ["[已晋升] 旧纠正", "✅ 已修正", "普通纠正"],
            SUMMARIES: ["2020-01-01 旧摘要", "2999-01-01 未来摘要"],
        },
    )
    cm._base_dir.mkdir(parents=True, exist_ok=True)
    cm._memory_file.write_text(
        "# MEMORY.md\n" + ("x" * (MEMORY_MAX_SIZE_BYTES + 512)), encoding="utf-8"
    )

    removed = asyncio.run(cm.auto_slim())

    assert removed["active_tasks"] == 2
    assert removed["corrections"] == 2
    assert removed["summaries"] == 1
    assert removed["experience"] == 2

    assert cm._sections[ACTIVE_TASKS] == ["进行中任务"]
    assert cm._sections[CORRECTIONS] == ["普通纠正"]
    assert cm._sections[SUMMARIES] == ["2999-01-01 未来摘要"]
    assert len(cm._sections[EXPERIENCE]) == 15
    assert "（含2条相似经验）" in cm._sections[EXPERIENCE][0]

    for name in ("active_tasks", "corrections", "summaries", "experience"):
        assert (cm._archive_dir / f"{name}_{TODAY}.md").exists()


# ----------------------------------------------------------------------
# 8. _merge_similar_items / _is_older_than / _should_not_save
# ----------------------------------------------------------------------


def test_merge_similar_items_noop_when_within_limit():
    """不超过 15 条时原样返回。"""
    items = ["条目一", "条目二"]
    merged, removed = CoreMemory._merge_similar_items(items)
    assert merged == items
    assert removed == []


def test_merge_similar_items_groups_and_truncates():
    """超 15 条时同关键词分组合并，仍超限则截断到 15 条。"""
    items = ["！！"] + [f"{word}类经验" for word in "一二三四五六七八九十甲乙丙丁戊"]
    assert len(items) == 16
    merged, removed = CoreMemory._merge_similar_items(items)
    assert len(merged) == 15
    assert len(removed) == 1
    assert removed[0] not in merged


def test_merge_similar_items_marks_group_size():
    """同一分组的多个条目合并为一条，并标注相似条数。"""
    items = ["经验甲乙丙丁"] * 3 + [f"独立条目{i}号" for i in range(13)]
    assert len(items) == 16
    merged, removed = CoreMemory._merge_similar_items(items)
    assert any("（含3条相似经验）" in item for item in merged)
    assert any("（含13条相似经验）" in item for item in merged)
    assert len(removed) == 14
    assert len(merged) + len(removed) == len(items)


@pytest.mark.parametrize(
    "item,cutoff,expected",
    [
        ("2020-01-01 的旧摘要", "2026-08-03", True),
        ("2026-08-09 的新摘要", "2026-08-03", False),
        ("没有日期的摘要", "2026-08-03", False),
    ],
)
def test_is_older_than(item, cutoff, expected):
    """能从条目里提取日期则比较，提取不到一律视为不过期。"""
    assert CoreMemory._is_older_than(item, cutoff) is expected


@pytest.mark.parametrize(
    "item,expected",
    [
        ("import os 后要用", True),
        ("from x import y", True),
        ("class Foo:", True),
        ("def bar():", True),
        ("配置写在 config.py 里", True),
        ("看看 git log 历史", True),
        ("这条 commit 信息", True),
        ("参考 pr #123", True),
        ("debug 一下这个问题", True),
        ("在这里设置断点", True),
        ("按 step 逐步排查", True),
        ("stack trace 很长", True),
        ("用户喜欢简短回复", False),
    ],
)
def test_should_not_save(item, expected):
    """NOT-to-save 规则：代码模式 / git 历史 / 调试步骤。"""
    assert CoreMemory._should_not_save(item) is expected


# ----------------------------------------------------------------------
# 9. LLM 合并偏好（夜间兜底）
# ----------------------------------------------------------------------


def test_llm_merge_preferences_skips_when_too_few(cm):
    """偏好条数 <= 1 时跳过 LLM 合并。"""
    _preset(cm, {PREFERENCES: ["只有一条"]})
    assert asyncio.run(cm.llm_merge_preferences()) == {
        "skipped": "too_few_items",
        "before": 1,
        "after": 1,
    }

    _preset(cm, {PREFERENCES: []})
    assert asyncio.run(cm.llm_merge_preferences()) == {
        "skipped": "too_few_items",
        "before": 0,
        "after": 0,
    }


def test_llm_merge_preferences_no_change_keeps_sections(cm, monkeypatch):
    """LLM 未移除任何条目时，不落盘、不改动分区。"""
    import core.services.self_improvement.core_memory_llm_merge as merger

    async def _fake(items, model_hint=None):
        return items, 0, {"skipped": "llm_no_response"}

    monkeypatch.setattr(merger, "llm_merge_preferences", _fake)
    _preset(cm, {PREFERENCES: ["偏好甲", "偏好乙"]})

    result = asyncio.run(cm.llm_merge_preferences(model_hint="hint"))
    assert result["skipped"] == "llm_no_response"
    assert result["before"] == 2
    assert result["after"] == 2
    assert cm._sections[PREFERENCES] == ["偏好甲", "偏好乙"]
    assert not cm._memory_file.exists()


def test_llm_merge_preferences_applies_and_persists(cm, monkeypatch):
    """LLM 成功合并时替换分区、清缓存并落盘。"""
    import core.services.self_improvement.core_memory_llm_merge as merger

    async def _fake(items, model_hint=None):
        return ["合并后的偏好"], 2, {"removed": 2}

    monkeypatch.setattr(merger, "llm_merge_preferences", _fake)
    _preset(cm, {PREFERENCES: ["偏好甲", "偏好乙", "偏好丙"]})
    cm._embeddings_cache[PREFERENCES] = [[1.0, 0.0]]

    result = asyncio.run(cm.llm_merge_preferences())
    assert result == {
        "before": 3,
        "after": 1,
        "removed": 2,
        "diag": {"removed": 2},
    }
    assert cm._sections[PREFERENCES] == ["合并后的偏好"]
    assert PREFERENCES not in cm._embeddings_cache
    assert "合并后的偏好" in cm._memory_file.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 10. _get_journal_summary
# ----------------------------------------------------------------------


def test_get_journal_summary_collects_recent_days(cm, monkeypatch):
    """按活跃角色 scope 读取最近 3 天摘要，无 summary 属性的条目被跳过。"""
    calls = []
    _install_fake_journal(
        monkeypatch,
        {
            "2026-08-10": _FakeDaily("今天摘要"),
            "2026-08-09": object(),
            "2026-08-08": _FakeDaily("前天摘要"),
        },
        scope="ling",
        calls=calls,
    )
    _preset(cm, {})

    text = asyncio.run(cm._get_journal_summary())
    assert "- [2026-08-10] 今天摘要" in text
    assert "- [2026-08-08] 前天摘要" in text
    assert len(calls) == 3
    assert all(scope == "ling" for _, scope in calls)


def test_get_journal_summary_continues_on_single_day_error(cm, monkeypatch):
    """单天读取失败只跳过该天，不影响其余天。"""
    _install_fake_journal(
        monkeypatch,
        {"2026-08-10": _FakeDaily("好的")},
        raises_on={"2026-08-09", "2026-08-08"},
    )
    _preset(cm, {})

    text = asyncio.run(cm._get_journal_summary())
    assert text == "- [2026-08-10] 好的"


def test_get_journal_summary_falls_back_to_sections(cm, monkeypatch):
    """JournalService 整体不可用时回退到 MEMORY.md 摘要区。"""
    _install_fake_journal(monkeypatch, {}, fail=True)
    _preset(cm, {SUMMARIES: ["旧摘要A", "旧摘要B"]})

    text = asyncio.run(cm._get_journal_summary())
    assert text == "- 旧摘要A\n- 旧摘要B"


def test_get_journal_summary_fallback_empty(cm, monkeypatch):
    """回退路径下摘要区也为空时返回空字符串。"""
    _install_fake_journal(monkeypatch, {}, fail=True)
    _preset(cm, {SUMMARIES: []})
    assert asyncio.run(cm._get_journal_summary()) == ""


# ----------------------------------------------------------------------
# 11. build_injection_text / build_injection_text_sync
# ----------------------------------------------------------------------


def test_build_injection_text_returns_empty_when_no_content(cm, monkeypatch):
    """全空时不注入（返回空字符串）。"""
    _install_fake_journal(monkeypatch, {})
    _preset(cm, {})
    assert asyncio.run(cm.build_injection_text()) == ""


def test_build_injection_text_lazy_loads(cm, monkeypatch):
    """未加载时 build_injection_text 会先触发一次加载。"""
    _install_fake_journal(monkeypatch, {})
    assert cm._loaded is False
    assert asyncio.run(cm.build_injection_text()) == ""
    assert cm._loaded is True


def test_build_injection_text_includes_sections_and_journal(cm, monkeypatch):
    """有内容时按分区顺序拼装，摘要区只取 JournalService 的内容。"""
    _install_fake_journal(monkeypatch, {"2026-08-10": _FakeDaily("今天聊了天气")})
    _preset(cm, {PREFERENCES: ["喜欢简短回复"], SUMMARIES: ["不应出现"]})

    text = asyncio.run(cm.build_injection_text())
    assert text.startswith("【核心记忆（MEMORY.md）】")
    assert "- 喜欢简短回复" in text
    assert "🔒 用户偏好（永久保留）" in text
    assert "今天聊了天气" in text
    assert "不应出现" not in text


def test_build_injection_text_sync_skips_summaries(cm):
    """同步版本首次调用触发同步加载，且跳过摘要区。"""
    assert cm.build_injection_text_sync() == ""
    assert cm._loaded is True

    _preset(cm, {PREFERENCES: ["偏好甲"], SUMMARIES: ["摘要不该出现"]})
    text = cm.build_injection_text_sync()
    assert "- 偏好甲" in text
    assert "摘要不该出现" not in text
    assert "对话摘要" not in text


# ----------------------------------------------------------------------
# 12. _archive_items
# ----------------------------------------------------------------------


def test_archive_items_noop_on_empty(cm):
    """空列表不创建归档目录。"""
    asyncio.run(cm._archive_items(PREFERENCES, []))
    assert not cm._archive_dir.exists()


def test_archive_items_appends_to_same_file(cm):
    """同一天多次归档追加到同一文件。"""
    asyncio.run(cm._archive_items(PREFERENCES, ["条目一"]))
    archive = cm._archive_dir / f"preferences_{TODAY}.md"
    asyncio.run(cm._archive_items(PREFERENCES, ["条目二"]))

    content = archive.read_text(encoding="utf-8")
    assert "条目一" in content
    assert "条目二" in content


def test_archive_items_swallows_errors(cm, monkeypatch):
    """归档过程出错只记日志，不向上抛异常。"""
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(coremem, "today_str", _boom)
    asyncio.run(cm._archive_items(PREFERENCES, ["条目一"]))
    assert list(cm._archive_dir.glob("*.md")) == []
