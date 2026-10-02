"""学习数据清单扫描：把一侧的文件扫成 {key: FileStat}。

扫描结果同时充当「内容指纹」：``sha1`` 判定内容是否一致，``mtime_ns`` 决定冲突时
谁取胜，``size`` 只用于跳过超大文件与打印。key 统一为 ``<base>:<rel>``，
与平台无关，本机与对端可以直接对账。

清单项的 ``rel`` 允许带 ``*`` / ``**`` 通配符（如聊天历史的 ``*/chat_history/**/*.jsonl``）；
通配符命中的文件一律换算成「相对基准根」的具体路径，因此两端展开出的键仍然一致。
扫描时顺带把每个键的合并策略记进 ``modes``，供 planner 决定「覆盖」还是「并集」。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from scripts.sync.learning_data.items import (
    EXCLUDED_DIR_NAMES,
    EXCLUDED_FILE_NAMES,
    EXCLUDED_SUFFIXES,
    SyncItem,
)

_READ_CHUNK = 1 << 20


@dataclass(frozen=True)
class FileStat:
    """单个文件的同步指纹。"""

    size: int
    mtime_ns: int
    sha1: str

    def as_state(self) -> Dict[str, int | str]:
        return {"size": self.size, "mtime_ns": self.mtime_ns, "sha1": self.sha1}


def key_of(base: str, rel: str) -> str:
    """返回清单项的对账键 ``<base>:<rel>``。"""
    return f"{base}:{rel}"


def is_pattern(rel: str) -> bool:
    """判断清单项的 ``rel`` 是否是通配符模式。"""
    return any(char in rel for char in "*?[")


def file_stat(path: Path) -> Optional[FileStat]:
    """读取单个文件的指纹；读不到（已删除 / 无权限）返回 None。"""
    try:
        info = path.stat()
    except OSError:
        return None
    digest = hashlib.sha1()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_READ_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return FileStat(size=info.st_size, mtime_ns=info.st_mtime_ns, sha1=digest.hexdigest())


def scan(
    items: Sequence[SyncItem],
    root_of: Callable[[str], Optional[Path]],
    *,
    max_bytes: int = 16 * 1024 * 1024,
    skipped: Optional[list] = None,
    modes: Optional[Dict[str, str]] = None,
) -> Dict[str, FileStat]:
    """扫描一侧的全部清单项。

    Args:
        items: 待扫描的清单项。
        root_of: 基准根解析函数，返回 None 表示该基准根不可用（整项跳过）。
        max_bytes: 单文件体积上限，超过则跳过（避免把大附件塞进中转目录）。
        skipped: 可选的收集器，用于记录被跳过的原因。
        modes: 可选的收集器，记录 ``{key: 合并策略}``；两端用同一份清单，
            因此本机与对端扫出来的策略一致。

    Returns:
        {key: FileStat}；不存在的路径不出现在结果里。
    """
    result: Dict[str, FileStat] = {}
    for item in items:
        root = root_of(item.base)
        if root is None:
            _note(skipped, key_of(item.base, item.rel), "对端/本机基准根不可用")
            continue
        if is_pattern(item.rel):
            _scan_pattern(result, skipped, modes, item, root, max_bytes)
            continue
        target = root / Path(item.rel)
        if not target.exists():
            continue
        if target.is_file():
            _collect(result, skipped, modes, item, item.rel, target, max_bytes)
            continue
        if not item.recursive:
            continue
        for path in sorted(target.rglob("*")):
            if not path.is_file() or _is_excluded(path, target):
                continue
            rel = path.relative_to(target).as_posix()
            _collect(result, skipped, modes, item, f"{item.rel}/{rel}", path, max_bytes)
    return result


def _scan_pattern(
    result: Dict[str, FileStat],
    skipped: Optional[list],
    modes: Optional[Dict[str, str]],
    item: SyncItem,
    root: Path,
    max_bytes: int,
) -> None:
    """展开通配符清单项，命中文件换算成「相对基准根」的具体路径。"""
    for path in sorted(root.glob(item.rel)):
        if not path.is_file() or _is_excluded(path, root):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - glob 结果必然在 root 之下
            continue
        _collect(result, skipped, modes, item, rel, path, max_bytes)


def _collect(
    result: Dict[str, FileStat],
    skipped: Optional[list],
    modes: Optional[Dict[str, str]],
    item: SyncItem,
    rel: str,
    path: Path,
    max_bytes: int,
) -> None:
    key = key_of(item.base, rel)
    if _is_excluded_file(path):
        _note(skipped, key, "命中排除名单")
        return
    try:
        if path.stat().st_size > max_bytes:
            _note(skipped, key, "超过单文件体积上限")
            return
    except OSError:
        return
    stat = file_stat(path)
    if stat is None:
        return
    result[key] = stat
    if modes is not None:
        modes[key] = item.merge


def _is_excluded(path: Path, base_dir: Path) -> bool:
    """目录递归时的排除判定：缓存目录 / 备份目录 / 版本库目录。"""
    try:
        parts = path.relative_to(base_dir).parts
    except ValueError:
        return False
    return any(part in EXCLUDED_DIR_NAMES for part in parts[:-1])


def _is_excluded_file(path: Path) -> bool:
    name = path.name
    return name in EXCLUDED_FILE_NAMES or name.endswith(EXCLUDED_SUFFIXES)


def _note(skipped: Optional[list], key: str, reason: str) -> None:
    if skipped is not None:
        skipped.append({"key": key, "reason": reason})
