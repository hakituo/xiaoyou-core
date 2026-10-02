"""同步执行：复制文件、并集合并、冲突留档、写回同步基线。

执行层只做四件事：

1. 按 ``Action`` 的方向复制文件（先写 ``.sync-tmp`` 再原子替换，避免半截文件）；
2. ``MERGE`` 动作改走并集合并：把两侧内容按策略合并后**同时写回双方**，
   因此「两边都追加了聊天记录」既不丢消息，也不会留下分歧；
3. 冲突时把被覆盖的一方另存 ``<name>.sync-conflict-<时间戳>``，绝不静默丢弃；
4. 同步成功后把双方共同的内容指纹写回 state，作为下次三向比对的基线。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from core.utils.logger import get_logger

from scripts.sync.learning_data.chat_merge import union_bytes
from scripts.sync.learning_data.manifest import file_stat
from scripts.sync.learning_data.planner import (
    CONFLICT,
    DELETE_LOCAL,
    DELETE_PEER,
    MERGE,
    PULL,
    PUSH,
    SKIP,
    DROPPED,
    Action,
)

logger = get_logger("LearningDataSync")

STATE_VERSION = 1


@dataclass
class ApplyResult:
    """一次同步执行的汇总。"""

    pushed: int = 0
    pulled: int = 0
    merged: int = 0
    conflicts: int = 0
    deleted: int = 0
    skipped: int = 0
    backups: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)


def load_state(path: Path) -> Dict[str, dict]:
    """读取同步基线；文件缺失或损坏时返回空基线（退化为首次同步）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("files")
    return dict(entries) if isinstance(entries, dict) else {}


def save_state(path: Path, state: Dict[str, dict]) -> None:
    """原子写回同步基线。"""
    payload = {"version": STATE_VERSION, "files": state}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def apply_actions(
    actions: Sequence[Action],
    *,
    local_of: Callable[[str, str], Optional[Path]],
    peer_of: Callable[[str, str], Optional[Path]],
    state: Dict[str, dict],
    dry_run: bool = False,
) -> ApplyResult:
    """执行同步计划并就地更新 ``state``。

    Args:
        actions: :func:`planner.plan` 生成的动作列表。
        local_of: 本机路径解析 ``(base, rel) -> Path``。
        peer_of: 对端路径解析 ``(base, rel) -> Path``。
        state: 同步基线，会被就地修改（新增 / 更新 / 删除条目）。
        dry_run: 为 True 时只统计不落盘。
    """
    result = ApplyResult()
    for action in actions:
        if action.kind in (SKIP, DROPPED):
            result.skipped += 1
            continue
        if action.kind in (DELETE_LOCAL, DELETE_PEER):
            _delete(action, local_of, peer_of, state, result, dry_run)
            continue
        if action.kind == MERGE:
            _merge(action, local_of, peer_of, state, result, dry_run)
            continue
        if action.kind == PUSH or (action.kind == CONFLICT and action.winner == "local"):
            _transfer(action, local_of, peer_of, state, result, dry_run, to_peer=True)
        elif action.kind == PULL or (action.kind == CONFLICT and action.winner == "peer"):
            _transfer(action, local_of, peer_of, state, result, dry_run, to_peer=False)
        else:  # pragma: no cover - planner 不产生其他 kind
            result.skipped += 1
    return result


def _merge(
    action: Action,
    local_of: Callable[[str, str], Optional[Path]],
    peer_of: Callable[[str, str], Optional[Path]],
    state: Dict[str, dict],
    result: ApplyResult,
    dry_run: bool,
) -> None:
    """并集合并：两侧内容合并后同时写回双方，并把合并结果写进基线。"""
    local = local_of(action.base, action.rel)
    peer = peer_of(action.base, action.rel)
    if local is None or peer is None:
        result.failed.append(f"{action.key} 路径不可用")
        return
    merged = union_bytes(action.merge, _read_bytes(local), _read_bytes(peer))
    if merged is None:  # pragma: no cover - planner 只对已知策略产生 MERGE
        result.failed.append(f"{action.key} 未知合并策略: {action.merge}")
        return
    result.merged += 1
    if dry_run:
        return
    try:
        _write_atomic(merged, local)
        _write_atomic(merged, peer)
    except OSError as exc:
        result.failed.append(f"{action.key} 合并写入失败: {exc}")
        logger.warning("合并失败 %s：%s", action.key, exc)
        return
    stat = file_stat(local)
    if stat is not None:
        state[action.key] = stat.as_state()


def _transfer(
    action: Action,
    local_of: Callable[[str, str], Optional[Path]],
    peer_of: Callable[[str, str], Optional[Path]],
    state: Dict[str, dict],
    result: ApplyResult,
    dry_run: bool,
    *,
    to_peer: bool,
) -> None:
    src_of, dst_of = (local_of, peer_of) if to_peer else (peer_of, local_of)
    src = src_of(action.base, action.rel)
    dst = dst_of(action.base, action.rel)
    if src is None or dst is None:
        result.failed.append(f"{action.key} 路径不可用")
        return
    if not src.exists():
        result.failed.append(f"{action.key} 源文件不存在: {src}")
        logger.warning("同步跳过：源文件不存在 %s", src)
        return
    if action.kind == CONFLICT:
        result.conflicts += 1
    if to_peer:
        result.pushed += 1
    else:
        result.pulled += 1
    if dry_run:
        return
    try:
        if action.kind == CONFLICT and dst.exists():
            backup = _backup(dst)
            if backup:
                result.backups.append(str(backup))
        _copy_atomic(src, dst)
    except OSError as exc:
        result.failed.append(f"{action.key} 传输失败: {exc}")
        logger.warning("同步失败 %s：%s", action.key, exc)
        return
    stat = file_stat(dst) or file_stat(src)
    if stat is not None:
        state[action.key] = stat.as_state()


def _delete(
    action: Action,
    local_of: Callable[[str, str], Optional[Path]],
    peer_of: Callable[[str, str], Optional[Path]],
    state: Dict[str, dict],
    result: ApplyResult,
    dry_run: bool,
) -> None:
    target_of = local_of if action.kind == DELETE_LOCAL else peer_of
    target = target_of(action.base, action.rel)
    if target is None or not target.exists():
        state.pop(action.key, None)
        return
    result.deleted += 1
    if dry_run:
        return
    try:
        target.unlink()
        state.pop(action.key, None)
    except OSError as exc:
        result.failed.append(f"{action.key} 删除失败: {exc}")
        logger.warning("删除失败 %s：%s", action.key, exc)


def _read_bytes(path: Path) -> bytes:
    """读取文件内容用于合并；不存在或不可读时按空内容处理。"""
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _write_atomic(payload: bytes, dst: Path) -> None:
    """先写 ``.sync-tmp`` 再原子替换目标文件。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".sync-tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, dst)


def _copy_atomic(src: Path, dst: Path) -> None:
    """复制文件到 ``.sync-tmp`` 后原子替换，保留 mtime。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".sync-tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _backup(path: Path) -> Optional[Path]:
    """把将被覆盖的文件另存为冲突副本。"""
    stamp = _stamp()
    target = path.with_name(f"{path.name}.sync-conflict-{stamp}")
    try:
        shutil.copy2(path, target)
        logger.warning("同步冲突，已保留旧版本：%s", target)
        return target
    except OSError as exc:
        logger.warning("冲突副本写入失败 %s：%s", path, exc)
        return None


def _stamp() -> str:
    try:
        from core.utils.time_utils import now_str

        return now_str("%Y%m%d-%H%M%S")
    except Exception:  # noqa: BLE001 - 脚本独立运行时的兜底
        import time

        return time.strftime("%Y%m%d-%H%M%S")
