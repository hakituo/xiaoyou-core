"""学习资料库索引测试。

用临时目录伪造一个迷你 Obsidian 库，验证：
文件名命中、正文标题回退命中、跳过运行状态目录、缓存与失效、空库安全。
"""
from __future__ import annotations

from core.services.study.study_library import StudyLibraryIndex, get_study_library


def _write(root, rel: str, content: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(root) -> StudyLibraryIndex:
    return StudyLibraryIndex(root=root)


def test_filename_match(study_sandbox):
    _write(study_sandbox, "Physics/02_一轮复习/05_动量.md", "# 动量\n")
    _write(study_sandbox, "Physics/02_一轮复习/04_功和能.md", "# 功和能\n")

    hits = _index(study_sandbox).search("physics", "动量")

    assert len(hits) == 1
    assert hits[0].title == "05_动量"
    assert hits[0].rel_path == "Physics/02_一轮复习/05_动量.md"
    assert hits[0].matched_by == "filename"


def test_heading_fallback_when_filename_misses(study_sandbox):
    """知识点藏在章节文件里时，要能靠正文标题找到。"""
    _write(
        study_sandbox,
        "Biology/02_二轮复习专题/01_细胞代谢综合专题.md",
        "# 细胞代谢综合专题\n\n## 细胞呼吸\n\n内容\n",
    )

    hits = _index(study_sandbox).search("biology", "细胞呼吸")

    assert len(hits) == 1
    assert hits[0].matched_by == "heading"
    assert hits[0].rel_path.startswith("Biology/")


def test_body_text_is_not_treated_as_match(study_sandbox):
    """正文里偶然提到不算命中，只有标题行才算，避免误报。"""
    _write(
        study_sandbox,
        "Physics/01_质点运动学.md",
        "# 质点运动学\n\n这里顺便提一句相位的问题，但不是本章主题。\n",
    )

    assert _index(study_sandbox).search("physics", "相位") == []


def test_no_match_returns_empty(study_sandbox):
    _write(study_sandbox, "Physics/01_质点运动学.md", "# 质点运动学\n")

    assert _index(study_sandbox).search("physics", "热力学第二定律") == []


def test_empty_concept_returns_empty(study_sandbox):
    _write(study_sandbox, "Physics/01_质点运动学.md", "# 质点运动学\n")
    index = _index(study_sandbox)

    assert index.search("physics", "") == []
    assert index.search("physics", "   ") == []


def test_runtime_state_dirs_are_skipped(study_sandbox):
    """运行状态与版本库目录不能被当成学习资料。"""
    _write(study_sandbox, ".state/notes/动量.md", "# 动量\n")
    _write(study_sandbox, ".obsidian/动量.md", "# 动量\n")
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")

    hits = _index(study_sandbox).search("physics", "动量")

    assert [h.rel_path for h in hits] == ["Physics/05_动量.md"]


def test_other_subject_dirs_are_not_searched(study_sandbox):
    """查物理不应该命中数学目录里的同名文件。"""
    _write(study_sandbox, "Mathematics/动量.md", "# 动量\n")
    _write(study_sandbox, "Physics/动量.md", "# 动量\n")

    hits = _index(study_sandbox).search("physics", "动量")

    assert [h.rel_path for h in hits] == ["Physics/动量.md"]


def test_missing_library_is_safe(tmp_path):
    index = StudyLibraryIndex(root=tmp_path / "not-exist")

    assert index.is_available() is False
    assert index.search("physics", "动量") == []


def test_results_are_cached_and_invalidatable(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")
    index = _index(study_sandbox)

    first = index.search("physics", "动量")
    # 新增文件后，缓存期内仍返回旧结果
    _write(study_sandbox, "Physics/06_动量守恒.md", "# 动量守恒\n")
    assert len(index.search("physics", "动量")) == len(first)

    index.invalidate()
    assert len(index.search("physics", "动量")) == 2


def test_search_many_dedupes_and_limits(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")
    _write(study_sandbox, "Physics/04_功和能.md", "# 功和能\n")
    index = _index(study_sandbox)

    hits = index.search_many("physics", ["动量", "功和能"], limit=5)

    assert {h.rel_path for h in hits} == {
        "Physics/05_动量.md",
        "Physics/04_功和能.md",
    }
    assert len(hits) == 2


def test_hit_serializes_for_prompt(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")

    payload = _index(study_sandbox).search("physics", "动量")[0].to_dict()

    assert payload["title"] == "05_动量"
    assert payload["location"] == "Physics/05_动量.md"
    assert payload["subject"] == "physics"
    assert payload["matched_by"] == "filename"


def test_singleton_follows_patched_study_root(study_sandbox):
    """单例必须走 paths.get_study_root()，否则测试会误指向真实笔记库。"""
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")

    hits = get_study_library().search("physics", "动量")

    assert [h.rel_path for h in hits] == ["Physics/05_动量.md"]


def test_concept_context_exposes_library_hits(study_sandbox):
    """知识点上下文要把笔记作为可用资料暴露出来，而不是只躺在索引里。"""
    from core.services.study.teaching_orchestrator import get_teaching_orchestrator

    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n")
    get_teaching_orchestrator().record_teaching("physics", "动量")

    ctx = get_teaching_orchestrator().get_context("讲讲动量")
    block = get_teaching_orchestrator().get_context_block("讲讲动量")

    assert any(r.get("source") == "library" for r in ctx["resources"])
    assert "Physics/05_动量.md" in block


def _frontmatter_note() -> str:
    """带 Obsidian frontmatter 的笔记，用于验证摘要会跳过元数据。"""
    parts = [
        "---",
        "aliases:",
        "  - 动量",
        "tags: [物理]",
        "---",
        "",
        "# 动量",
        "",
        "动量观点与能量观点并列，是解决力学综合题（碰撞、打击、反冲）的两把利器。",
        "",
    ]
    return "\n".join(parts) + "\n"


def test_hit_carries_excerpt(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", _frontmatter_note())
    index = _index(study_sandbox)

    hits = index.search("physics", "动量")

    assert hits[0].excerpt
    assert "动量观点与能量观点并列" in hits[0].excerpt
    assert hits[0].to_dict()["excerpt"] == hits[0].excerpt


def test_excerpt_skips_frontmatter(study_sandbox):
    """首个含关键词的行常在 frontmatter 里，那种摘要对模型毫无价值。"""
    _write(study_sandbox, "Physics/05_动量.md", _frontmatter_note())
    index = _index(study_sandbox)

    excerpt = index.search("physics", "动量")[0].excerpt

    assert "aliases" not in excerpt
    assert "动量观点" in excerpt


def test_excerpt_is_length_capped(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n\n" + "内容" * 500 + "\n")
    index = _index(study_sandbox)

    excerpt = index.search("physics", "动量")[0].excerpt

    assert len(excerpt) <= index.EXCERPT_CHARS + 1


def test_excerpt_tolerates_missing_file(study_sandbox):
    _write(study_sandbox, "Physics/05_动量.md", "# 动量\n\n动量定理的内容。\n")
    index = _index(study_sandbox)
    hit = index.search("physics", "动量")[0]
    (study_sandbox / hit.rel_path).unlink()

    assert index._read_excerpt(study_sandbox / hit.rel_path, "动量") == ""
