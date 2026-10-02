"""结构感知的中文学习资料切分。

**不要机械按字数一刀切。** 教材里「公式 F = -kx」和「负号表示回复力方向」
必须在同一个或相邻片段里；机械切分很容易把公式搜出来、却把解释它的下一段丢掉。

优先级：**结构边界 > 字数**
    章（H1） → 小节（H2/H3） → 自然段/推导块 → 仍然过长时才按字数再切

中文教材起步 300–700 字/chunk，但结构边界优先。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import List, NamedTuple, Optional

from .models import Chunk

#: 目标字数区间。结构完整时允许略微超出，避免把一段推导劈开。
TARGET_MIN_CHARS = 120
TARGET_MAX_CHARS = 700
HARD_MAX_CHARS = 1200

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FRONTMATTER_RE = re.compile(r"^---\s*$")


class _Section(NamedTuple):
    """切分时的中间结构：一个小节及其正文。"""

    chapter: str
    section: str
    body: str


def _strip_frontmatter(lines: List[str]) -> List[str]:
    """去掉 Obsidian 的 YAML frontmatter，否则切出来的第一块全是元数据。"""
    if not lines or not _FRONTMATTER_RE.match(lines[0].strip()):
        return lines
    for index in range(1, len(lines)):
        if _FRONTMATTER_RE.match(lines[index].strip()):
            return lines[index + 1 :]
    return lines


def _split_sections(text: str) -> List[_Section]:
    """按标题层级切成「章 / 小节 / 正文」。

    H1 视为章，H2/H3 视为小节，更深层级并入最近的小节标题。
    """
    lines = _strip_frontmatter(text.splitlines())

    sections: List[_Section] = []
    chapter = ""
    section = ""
    buffer: List[str] = []

    def _flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(_Section(chapter, section, body))
        buffer.clear()

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            _flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            if level <= 1:
                chapter, section = title, ""
            elif level <= 3:
                section = title
            else:
                # H4+ 太碎，并入当前小节而不是单开一个
                buffer.append(line)
            continue
        buffer.append(line)
    _flush()
    return sections


def _split_long_body(body: str, limit: int = HARD_MAX_CHARS) -> List[str]:
    """结构内仍过长时再切。

    优先在段落边界切，其次在句号切，绝不从单词中间断。
    """
    if len(body) <= limit:
        return [body]

    pieces: List[str] = []
    current = ""
    for paragraph in body.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(paragraph) <= limit:
            current = paragraph
            continue
        # 单段仍超长：按句号退让
        sentence_buffer = ""
        for sentence in re.split(r"(?<=[。！？；])", paragraph):
            if len(sentence_buffer) + len(sentence) <= limit:
                sentence_buffer += sentence
            else:
                if sentence_buffer:
                    pieces.append(sentence_buffer)
                sentence_buffer = sentence
        current = sentence_buffer
    if current:
        pieces.append(current)
    return [p.strip() for p in pieces if p.strip()]


def _merge_short(pieces: List[str], target_min: int = TARGET_MIN_CHARS) -> List[str]:
    """把过短的碎片并回上一块，避免「一个标题一句话」这种噪声 chunk。"""
    merged: List[str] = []
    for piece in pieces:
        if merged and (len(merged[-1]) < target_min or len(piece) < target_min):
            merged[-1] = f"{merged[-1]}\n\n{piece}"
        else:
            merged.append(piece)
    return merged


def chunk_markdown(
    text: str,
    *,
    resource_id: str,
    subject: str = "",
    source_path: str = "",
    trust_level: str = "",
    page: Optional[int] = None,
) -> List[Chunk]:
    """把一篇 Markdown 学习资料切成结构感知的片段。"""
    chunks: List[Chunk] = []
    order = 0

    for section in _split_sections(text):
        pieces = _merge_short(_split_long_body(section.body))
        for piece in pieces:
            # 标题作为上下文前缀一起入 chunk：只搜正文会丢失「属于哪个小节」
            prefix = " > ".join(p for p in (section.chapter, section.section) if p)
            body = f"{prefix}\n{piece}" if prefix else piece
            chunk_id = hashlib.md5(
                f"{resource_id}|{order}|{piece[:80]}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    resource_id=resource_id,
                    text=body.strip(),
                    subject=subject,
                    chapter=section.chapter,
                    section=section.section,
                    order=order,
                    page=page,
                    source_path=source_path,
                    trust_level=trust_level,
                )
            )
            order += 1
    return chunks


def chunk_plain_text(
    text: str,
    *,
    resource_id: str,
    subject: str = "",
    source_path: str = "",
    trust_level: str = "",
    page: Optional[int] = None,
) -> List[Chunk]:
    """纯文本没有标题结构，退化为「段落 → 合并短段 → 切长段」。"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces = _merge_short(paragraphs)
    expanded: List[str] = []
    for piece in pieces:
        expanded.extend(_split_long_body(piece))

    chunks: List[Chunk] = []
    for order, piece in enumerate(expanded):
        chunk_id = hashlib.md5(
            f"{resource_id}|{order}|{piece[:80]}".encode("utf-8")
        ).hexdigest()
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                resource_id=resource_id,
                text=piece,
                subject=subject,
                order=order,
                page=page,
                source_path=source_path,
                trust_level=trust_level,
            )
        )
    return chunks


def chunk_document(
    text: str,
    *,
    resource_id: str,
    suffix: str = ".md",
    **kwargs,
) -> List[Chunk]:
    """按文件类型选择切分方式；未知类型按纯文本处理。"""
    if suffix.lower() in (".md", ".markdown"):
        return chunk_markdown(text, resource_id=resource_id, **kwargs)
    return chunk_plain_text(text, resource_id=resource_id, **kwargs)


def with_concepts(chunk: Chunk, concept_ids: List[str]) -> Chunk:
    """给片段打上知识点标签（frozen，只能替换）。"""
    return replace(chunk, concept_ids=list(concept_ids))
