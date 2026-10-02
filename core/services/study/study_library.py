"""学习资料库索引 —— 在用户的 Study 笔记库里按知识点找相关笔记。

定位
----
``ResourceRegistry`` 负责**用户显式登记**的少量可信资源（教材、官方文档）；
本模块负责**已存在的笔记库**：用户的 ``study_root`` 通常就是一个 Obsidian 库
（如 ``Physics/02_一轮复习/05_动量.md``），里面有成百上千份结构化笔记。

为什么不做成「把全部笔记登记进 resources.json」：
1000+ 条记录会让状态文件膨胀到几百 KB，每次读写都变慢，而且用户新增笔记后
还要重新同步。改为**惰性按需检索 + 缓存**，永远与笔记库保持同步。

检索策略（两段，先便宜后贵）：
1. 文件名匹配（零 IO）：知识点名出现在文件名里，如「动量」↔ ``05_动量.md``；
2. 正文标题匹配（有界 IO）：知识点名出现在文件开头的标题里，
   处理「相位」藏在 ``04_简谐运动.md`` 这种章节内的情况。

结果只返回**标题 + 相对路径**，由上层决定是否用 ``study_data_management``
工具去读全文——第一版不做完整 RAG。
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.services.study import paths
from core.utils.logger import get_logger

logger = get_logger("StudyLibrary")

# 科目 slug -> 笔记库里的目录名
SUBJECT_DIRS: Dict[str, Tuple[str, ...]] = {
    "physics": ("Physics",),
    "math": ("Mathematics",),
    "chemistry": ("Chemistry",),
    "biology": ("Biology",),
    "chinese": ("Chinese",),
    "english": ("English",),
    "geography": ("Geography",),
    "history": ("History",),
    "computer_science": ("Computer_Science",),
    "general": ("Gaokao_Prep",),
}

# 不参与检索的目录：运行状态、版本库、编辑器配置、媒体与工具
SKIP_DIR_NAMES = {
    ".state", ".git", ".obsidian", "media", "obsidian-viewer",
    "Study_tools", "copilot", "attachments", ".trash",
}

# 单科目扫描上限与正文扫描上限（防御性，避免超大库拖慢对话）
MAX_SCAN_FILES = 600
MAX_CONTENT_SCAN_FILES = 80
CONTENT_HEAD_LINES = 60

# 缓存有效期（秒）；笔记库变化不频繁，过期后自然重建
CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class LibraryHit:
    """一条命中的笔记。"""

    title: str
    rel_path: str
    subject: str
    matched_by: str  # filename / heading
    excerpt: str = ""  # 相关片段，让模型一次就能用上，不必再调工具读全文

    def to_dict(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "location": self.rel_path,
            "subject": self.subject,
            "matched_by": self.matched_by,
            "excerpt": self.excerpt,
        }


class StudyLibraryIndex:
    """按知识点在笔记库里检索相关笔记（线程安全 + TTL 缓存）。"""

    _instance: Optional["StudyLibraryIndex"] = None
    _instance_lock = threading.Lock()

    def __init__(self, root: Optional[Path] = None):
        self._lock = threading.Lock()
        # 注意：必须走 paths.get_study_root() 而不是 `from paths import get_study_root`，
        # 否则函数引用在导入时被固定，测试里替换 paths.get_study_root 不会生效。
        self._root = Path(root) if root else paths.get_study_root()
        self._cache: Dict[Tuple[str, str], Tuple[float, List[LibraryHit]]] = {}

    @classmethod
    def get_instance(cls) -> "StudyLibraryIndex":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    #: 给前几条命中补摘要（读文件有 IO，条数要封顶）
    EXCERPT_HIT_LIMIT = 3
    EXCERPT_CHARS = 160

    def search(self, subject: str, concept: str, limit: int = 3) -> List[LibraryHit]:
        """按科目 + 知识点名检索相关笔记。"""
        key = (self._normalize_subject(subject), str(concept or "").strip())
        if not key[1]:
            return []

        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return list(cached[1])[:limit]

        hits = self._search_uncached(key[0], key[1])
        # 只给前几条补摘要：读文件有 IO，且 prompt 里也放不下太多
        for hit in hits[: self.EXCERPT_HIT_LIMIT]:
            if not hit.excerpt:
                object.__setattr__(
                    hit, "excerpt", self._read_excerpt(self._root / hit.rel_path, key[1])
                )
        with self._lock:
            self._cache[key] = (now, hits)
        return hits[:limit]

    def search_many(
        self, subject: str, concepts: List[str], limit: int = 3
    ) -> List[LibraryHit]:
        """多知识点检索，按知识点顺序去重合并。"""
        merged: List[LibraryHit] = []
        seen = set()
        for concept in concepts or []:
            for hit in self.search(subject, concept, limit=limit):
                if hit.rel_path in seen:
                    continue
                seen.add(hit.rel_path)
                merged.append(hit)
                if len(merged) >= limit:
                    return merged
        return merged

    def invalidate(self) -> None:
        """清空缓存（笔记库变动或测试时调用）。"""
        with self._lock:
            self._cache.clear()

    def is_available(self) -> bool:
        """笔记库是否存在。"""
        return self._root.is_dir()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_subject(subject: str) -> str:
        return str(subject or "").strip().lower() or "general"

    def _subject_dirs(self, subject: str) -> List[Path]:
        names = SUBJECT_DIRS.get(subject) or SUBJECT_DIRS["general"]
        return [self._root / name for name in names]

    def _iter_markdown(self, subject: str):
        """遍历该科目下的 markdown 文件（跳过运行状态与版本库目录）。"""
        count = 0
        for base in self._subject_dirs(subject):
            if not base.is_dir():
                continue
            for path in base.rglob("*.md"):
                if any(part in SKIP_DIR_NAMES for part in path.parts):
                    continue
                yield path
                count += 1
                if count >= MAX_SCAN_FILES:
                    return

    def _search_uncached(self, subject: str, concept: str) -> List[LibraryHit]:
        if not self.is_available():
            return []

        # 第一段：文件名匹配（零 IO）
        by_name: List[LibraryHit] = []
        candidates: List[Path] = []
        try:
            for path in self._iter_markdown(subject):
                candidates.append(path)
                if concept in path.stem:
                    by_name.append(
                        LibraryHit(
                            title=path.stem,
                            rel_path=self._rel(path),
                            subject=subject,
                            matched_by="filename",
                        )
                    )
        except Exception as e:  # noqa: BLE001
            logger.debug("扫描笔记库失败 %s/%s：%s", subject, concept, e)
            return []

        if by_name:
            # 路径更浅的通常更贴近主题（章节页优于子目录里的碎片）
            by_name.sort(key=lambda h: (len(h.rel_path), h.rel_path))
            return by_name

        # 第二段：正文标题匹配（有界 IO），处理知识点藏在章节内的情况
        return self._search_by_heading(candidates, subject, concept)

    def _search_by_heading(
        self, candidates: List[Path], subject: str, concept: str
    ) -> List[LibraryHit]:
        hits: List[LibraryHit] = []
        # 浅路径优先，提高命中章节页的概率
        ordered = sorted(candidates, key=lambda p: (len(p.parts), str(p)))[
            :MAX_CONTENT_SCAN_FILES
        ]
        for path in ordered:
            if self._head_mentions(path, concept):
                hits.append(
                    LibraryHit(
                        title=path.stem,
                        rel_path=self._rel(path),
                        subject=subject,
                        matched_by="heading",
                    )
                )
                if len(hits) >= 5:
                    break
        return hits

    #: 元数据行（Obsidian frontmatter / 标签），摘要必须跳过
    _META_RE = re.compile(
        r"^\s*(aliases|tags|category|created|updated|source|date|type|cssclass)\s*[:：]",
        re.IGNORECASE,
    )

    def _read_excerpt(self, path: Path, concept: str) -> str:
        """取一小段与知识点最相关的**正文**。

        优先取「包含知识点名、且像正文（够长、非元数据）的那一行及其后几行」。
        直接取首个含关键词的行会抓到 frontmatter（如「- 动量 aliases: - 动量」），
        那种摘要对模型毫无价值。取不到贴题正文就退回首段正文。
        """
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.rstrip() for line in f.readlines()[:200]]
        except OSError:
            return ""

        # 去掉 YAML frontmatter
        start = 0
        if lines and lines[0].strip() == "---":
            for index in range(1, len(lines)):
                if lines[index].strip() == "---":
                    start = index + 1
                    break
        body = lines[start:]

        def _is_meta(line: str) -> bool:
            text = line.strip()
            return not text or text == "---" or bool(self._META_RE.match(text))

        def _is_prose(line: str) -> bool:
            return len(line.strip()) >= 12 and not _is_meta(line)

        def _join(index: int) -> str:
            picked = [x for x in body[index : index + 3] if x.strip() and not _is_meta(x)]
            return " ".join(picked)

        chunk = ""
        for index, line in enumerate(body):
            if concept in line and _is_prose(line):
                chunk = _join(index)
                break
        if not chunk:
            for index, line in enumerate(body):
                if _is_prose(line):
                    chunk = _join(index)
                    break

        chunk = re.sub(r"[#*`>|\[\]]+", " ", chunk)
        chunk = re.sub(r"\s+", " ", chunk).strip()
        if len(chunk) > self.EXCERPT_CHARS:
            chunk = chunk[: self.EXCERPT_CHARS].rstrip() + "…"
        return chunk

    @staticmethod
    def _head_mentions(path: Path, concept: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for index, line in enumerate(f):
                    if index >= CONTENT_HEAD_LINES:
                        break
                    # 只看标题行，避免正文里偶然提到就算命中
                    if line.lstrip().startswith("#") and concept in line:
                        return True
        except OSError:
            return False
        return False

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self._root).as_posix()
        except ValueError:
            return path.as_posix()


def get_study_library() -> StudyLibraryIndex:
    """工厂函数，获取全局单例。"""
    return StudyLibraryIndex.get_instance()
