import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


@dataclass
class ChunkMeta:
    path: str
    start_line: int
    end_line: int
    sha1: str


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_index_dir() -> Path:
    root = _project_root()
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        cache_dir = str(getattr(settings.model, "cache_dir", "cache") or "cache")
    except Exception:
        cache_dir = "cache"
    return (root / cache_dir / "semantic_index").resolve()


def _iter_source_files(root: Path, include_globs: List[str]) -> Iterable[Path]:
    ignore_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".trae",
        ".vs",
        "__pycache__",
        "build",
        "clients",
        "cpp_scheduler\\build",
        "dist",
        "external",
        "legacy",
        "models",
        "output",
        "paper",
        "venv_core",
    }

    normalized_ignore = {d.replace("/", "\\").lower() for d in ignore_dirs}

    for pattern in include_globs:
        for p in root.rglob(pattern):
            try:
                rel = p.relative_to(root)
            except Exception:
                continue

            rel_str = str(rel).replace("/", "\\")
            parts = rel_str.lower().split("\\")
            if any(part in normalized_ignore for part in parts):
                continue
            if not p.is_file():
                continue
            yield p


def _read_text_file(path: Path, max_bytes: int) -> Optional[str]:
    try:
        size = path.stat().st_size
        if size <= 0:
            return ""
        if size > max_bytes:
            return None
        data = path.read_bytes()
        try:
            return data.decode("utf-8")
        except Exception:
            try:
                return data.decode("utf-8", errors="ignore")
            except Exception:
                return None
    except Exception:
        return None


def _sha1_bytes(data: bytes) -> str:
    import hashlib

    h = hashlib.sha1()
    h.update(data)
    return h.hexdigest()


def _chunk_text(
    text: str, chunk_lines: int, overlap: int
) -> List[Tuple[str, int, int]]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: List[Tuple[str, int, int]] = []
    step = max(1, chunk_lines - overlap)
    i = 0
    while i < len(lines):
        start = i
        end = min(len(lines), i + chunk_lines)
        block = "\n".join(lines[start:end]).strip("\n")
        if block.strip():
            chunks.append((block, start + 1, end))
        if end >= len(lines):
            break
        i += step
    return chunks


def _normalize_query(q: str) -> str:
    q = str(q or "").strip()
    q = re.sub(r"\s+", " ", q)
    return q


def build_index(
    index_dir: Path,
    include_globs: List[str],
    chunk_lines: int,
    overlap: int,
    max_file_bytes: int,
) -> int:
    root = _project_root()
    index_dir.mkdir(parents=True, exist_ok=True)

    docs: List[str] = []
    metas: List[ChunkMeta] = []

    file_count = 0
    chunk_count = 0
    skipped_large = 0
    skipped_unreadable = 0

    for path in _iter_source_files(root, include_globs):
        file_count += 1
        raw = _read_text_file(path, max_file_bytes)
        if raw is None:
            try:
                if path.stat().st_size > max_file_bytes:
                    skipped_large += 1
                else:
                    skipped_unreadable += 1
            except Exception:
                skipped_unreadable += 1
            continue
        raw_bytes = raw.encode("utf-8", errors="ignore")
        file_sha1 = _sha1_bytes(raw_bytes)
        rel = str(path.relative_to(root)).replace("/", "\\")

        for block, start_line, end_line in _chunk_text(raw, chunk_lines, overlap):
            docs.append(block)
            metas.append(
                ChunkMeta(
                    path=rel,
                    start_line=int(start_line),
                    end_line=int(end_line),
                    sha1=file_sha1,
                )
            )
            chunk_count += 1

    if not docs:
        print("未收集到任何可索引文件")
        return 1

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    from joblib import dump
    import scipy.sparse

    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        max_features=200000,
        token_pattern=r"(?u)\b[\w\-\./]{2,}\b",
        lowercase=False,
    )
    matrix = vectorizer.fit_transform(docs)

    nn = NearestNeighbors(metric="cosine", algorithm="brute")
    nn.fit(matrix)

    dump(vectorizer, index_dir / "vectorizer.joblib")
    dump(nn, index_dir / "nn.joblib")
    scipy.sparse.save_npz(index_dir / "matrix.npz", matrix)
    (index_dir / "metas.jsonl").write_text(
        "\n".join(json.dumps(m.__dict__, ensure_ascii=False) for m in metas),
        encoding="utf-8",
    )
    (index_dir / "stats.json").write_text(
        json.dumps(
            {
                "project_root": str(root),
                "file_count": file_count,
                "chunk_count": chunk_count,
                "skipped_large": skipped_large,
                "skipped_unreadable": skipped_unreadable,
                "chunk_lines": chunk_lines,
                "overlap": overlap,
                "max_file_bytes": max_file_bytes,
                "include_globs": include_globs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"索引完成: chunks={chunk_count}, files_seen={file_count}")
    print(f"索引目录: {index_dir}")
    return 0


def _load_metas(index_dir: Path) -> List[ChunkMeta]:
    metas_path = index_dir / "metas.jsonl"
    if not metas_path.exists():
        raise FileNotFoundError(f"找不到索引元数据: {metas_path}")
    metas: List[ChunkMeta] = []
    for line in metas_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        metas.append(
            ChunkMeta(
                path=str(obj.get("path") or ""),
                start_line=int(obj.get("start_line") or 1),
                end_line=int(obj.get("end_line") or 1),
                sha1=str(obj.get("sha1") or ""),
            )
        )
    return metas


def search_index(index_dir: Path, query: str, k: int, show_lines: int) -> int:
    from joblib import load

    q = _normalize_query(query)
    if not q:
        print("query 为空")
        return 1

    vectorizer_path = index_dir / "vectorizer.joblib"
    nn_path = index_dir / "nn.joblib"
    matrix_path = index_dir / "matrix.npz"
    if not vectorizer_path.exists() or not nn_path.exists() or not matrix_path.exists():
        print("索引不存在或不完整，请先运行 build")
        return 1

    import scipy.sparse

    vectorizer = load(vectorizer_path)
    nn = load(nn_path)
    matrix = scipy.sparse.load_npz(matrix_path)
    metas = _load_metas(index_dir)
    if matrix.shape[0] != len(metas):
        print("索引损坏：矩阵行数与元数据不一致")
        return 1

    q_vec = vectorizer.transform([q])
    n = min(max(1, int(k)), matrix.shape[0])
    distances, indices = nn.kneighbors(q_vec, n_neighbors=n, return_distance=True)

    root = _project_root()
    shown = 0
    for dist, idx in zip(distances[0].tolist(), indices[0].tolist()):
        try:
            meta = metas[int(idx)]
        except Exception:
            continue

        file_path = (root / meta.path).resolve()
        if not file_path.exists():
            continue
        text = _read_text_file(file_path, max_bytes=20_000_000)
        if text is None:
            continue
        lines = text.splitlines()
        s = max(1, meta.start_line)
        e = min(len(lines), meta.end_line)
        ctx = max(0, int(show_lines))
        s2 = max(1, s - ctx)
        e2 = min(len(lines), e + ctx)

        snippet_lines = lines[s2 - 1 : e2]
        score = 1.0 - float(dist)
        print(f"[{shown + 1}] score={score:.4f} {meta.path}#L{s}-L{e}")
        for i, line in enumerate(snippet_lines, start=s2):
            print(f"{i:>5} | {line}")
        print("-")
        shown += 1
        if shown >= k:
            break

    if shown == 0:
        print("未找到匹配结果")
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build")
    p_build.add_argument("--index-dir", type=str, default=None)
    p_build.add_argument(
        "--include",
        type=str,
        default="*.py,*.md,*.txt,*.toml,*.yaml,*.yml,*.json,*.ts,*.tsx,*.js,*.jsx,*.cpp,*.h,*.hpp,*.c,*.cu,*.cmake",
    )
    p_build.add_argument("--chunk-lines", type=int, default=200)
    p_build.add_argument("--overlap", type=int, default=40)
    p_build.add_argument("--max-file-bytes", type=int, default=2_000_000)

    p_search = sub.add_parser("search")
    p_search.add_argument("query", type=str)
    p_search.add_argument("--index-dir", type=str, default=None)
    p_search.add_argument("--topk", type=int, default=8)
    p_search.add_argument("--show-lines", type=int, default=3)

    args = parser.parse_args(argv)
    cmd = str(getattr(args, "cmd", "") or "").strip().lower()
    index_dir = (
        Path(args.index_dir).resolve()
        if getattr(args, "index_dir", None)
        else _default_index_dir()
    )

    if cmd == "build":
        include = str(args.include or "").strip()
        include_globs = [p.strip() for p in include.split(",") if p.strip()]
        return build_index(
            index_dir=index_dir,
            include_globs=include_globs,
            chunk_lines=int(args.chunk_lines),
            overlap=int(args.overlap),
            max_file_bytes=int(args.max_file_bytes),
        )
    if cmd == "search":
        return search_index(
            index_dir=index_dir,
            query=str(args.query or ""),
            k=int(args.topk),
            show_lines=int(args.show_lines),
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
