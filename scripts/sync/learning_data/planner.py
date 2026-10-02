"""三向比对：本机 / 对端 / 上次同步基线 → 同步动作计划。

只用「谁改过」判断方向，不猜时间戳谁更可信：

- 基线 = 上次同步后双方共同的内容指纹（记在 state 里）；
- 只有一端相对基线变了 → 从变化的一端同步到另一端（单向，安全）；
- 没有基线（首次同步或新增文件）→ 按「谁有」决定方向；
- 两端都有且都变了 → 按清单项的合并策略处理：
  - ``MERGE_COPY``（默认）：冲突，取 mtime 更新的一方，另一方另存冲突副本；
  - ``MERGE_JSONL`` / ``MERGE_INDEX``：不做覆盖，改为两端并集合并（``MERGE``），
    因此「两边都追加了聊天记录」不会丢消息。

删除默认不传播：一端文件消失时只报告不删除另一端，避免误删学习数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from scripts.sync.learning_data.items import MERGE_COPY
from scripts.sync.learning_data.manifest import FileStat, key_of

PUSH = "push"
PULL = "pull"
SKIP = "skip"
CONFLICT = "conflict"
MERGE = "merge"
DROPPED = "dropped"
DELETE_LOCAL = "delete-local"
DELETE_PEER = "delete-peer"

_DIRECTION_OF = {
    PUSH: "本地 → 对端",
    PULL: "对端 → 本地",
    MERGE: "双向并集",
    DELETE_LOCAL: "删除本机",
    DELETE_PEER: "删除对端",
}


@dataclass(frozen=True)
class Action:
    """一条同步动作。

    Attributes:
        kind: ``push`` / ``pull`` / ``merge`` / ``skip`` / ``conflict`` / ``dropped``。
        base: 基准根。
        rel: 相对基准根的路径。
        reason: 判定依据，用于 dry-run 打印。
        winner: 冲突时取胜的一方（``local`` / ``peer``），非冲突为空。
        merge: 合并策略；``kind == MERGE`` 时由执行层据此选择并集函数。
    """

    kind: str
    base: str
    rel: str
    reason: str
    winner: str = ""
    merge: str = MERGE_COPY

    @property
    def key(self) -> str:
        return key_of(self.base, self.rel)

    @property
    def direction(self) -> str:
        """返回人类可读的传输方向；skip / dropped 返回空串。"""
        if self.kind == CONFLICT:
            return _DIRECTION_OF[PUSH if self.winner == "local" else PULL]
        return _DIRECTION_OF.get(self.kind, "")


def plan(
    local: Dict[str, FileStat],
    peer: Dict[str, FileStat],
    state: Dict[str, dict],
    *,
    propagate_delete: bool = False,
    merge_mode_of: Optional[Callable[[str], str]] = None,
) -> List[Action]:
    """比对两端生成同步计划。

    Args:
        local: 本机扫描结果。
        peer: 对端扫描结果。
        state: 上次同步基线，{key: {"sha1": ...}}。
        propagate_delete: 为 True 时一端删除会真的删掉另一端（默认关闭）。
        merge_mode_of: 按键返回合并策略；缺省一律按整文件复制（``MERGE_COPY``）处理。
    """
    actions: List[Action] = []
    resolve_merge = merge_mode_of or (lambda _key: MERGE_COPY)
    for key in sorted(set(local) | set(peer)):
        base, _, rel = key.partition(":")
        actions.append(
            _decide(
                base,
                rel,
                local.get(key),
                peer.get(key),
                str((state.get(key) or {}).get("sha1") or ""),
                propagate_delete,
                resolve_merge(key),
            )
        )
    return actions


def _decide(
    base: str,
    rel: str,
    mine: Optional[FileStat],
    theirs: Optional[FileStat],
    base_sha: str,
    propagate_delete: bool,
    merge_mode: str,
) -> Action:
    if mine is None and theirs is None:  # pragma: no cover - 键来自两端并集
        return Action(SKIP, base, rel, "两端都不存在")
    if theirs is None:
        if not base_sha:
            return Action(PUSH, base, rel, "本机新增，对端没有")
        if base_sha != mine.sha1:
            return Action(PUSH, base, rel, "本机改过且对端缺失")
        if propagate_delete:
            return Action(DELETE_LOCAL, base, rel, "对端已删除，按 --propagate-delete 删除本机")
        return Action(DROPPED, base, rel, "对端已删除（默认不传播删除）")
    if mine is None:
        if not base_sha:
            return Action(PULL, base, rel, "对端新增，本机没有")
        if base_sha != theirs.sha1:
            return Action(PULL, base, rel, "对端改过且本机缺失")
        if propagate_delete:
            return Action(DELETE_PEER, base, rel, "本机已删除，按 --propagate-delete 删除对端")
        return Action(DROPPED, base, rel, "本机已删除（默认不传播删除）")
    if mine.sha1 == theirs.sha1:
        return Action(SKIP, base, rel, "两端内容一致")
    if base_sha == mine.sha1:
        return Action(PULL, base, rel, "仅对端相对上次同步有改动")
    if base_sha == theirs.sha1:
        return Action(PUSH, base, rel, "仅本机相对上次同步有改动")
    reason = "两端都改过" if base_sha else "两端都有但无同步基线（首次同步）"
    if merge_mode != MERGE_COPY:
        return Action(MERGE, base, rel, f"{reason}，按 {merge_mode} 做并集合并", merge=merge_mode)
    winner = "local" if mine.mtime_ns >= theirs.mtime_ns else "peer"
    return Action(CONFLICT, base, rel, f"{reason}，取 mtime 更新的一方", winner)
