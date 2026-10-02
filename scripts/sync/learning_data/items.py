"""学习数据同步清单与路径解析。

双系统（Windows / Linux 双启动）场景下同一时刻只有一个系统在线，两端各持有一份
仓库与运行时数据。本模块只回答两个问题，不做任何读写：

1. 学习数据包含哪些文件或目录（``ITEMS`` 清单，按 group 分组）；
2. 清单项在本机与对端的绝对路径是什么（``local_root`` / ``PeerLayout``）。

清单项统一用「基准根 + 相对路径」描述，与平台无关。基准根有四类：

- ``project``：仓库根目录（``get_project_root()``）；
- ``user_data``：运行时用户数据目录（``companion_data/user_data``）；
- ``study``：学习库根目录（Windows 为 ``D:\\AI\\Study``，Linux 经跨平台镜像到 ``~/Study``）；
- ``companion``：运行时数据根（``companion_data``），用于覆盖各角色 scope 目录。

部分文件两端都会写（典型是聊天历史：一个会话一天一个 JSONL，两边都可能追加），
整文件「谁新用谁」会丢掉另一边的消息，因此这类清单项带 ``merge`` 策略，由
``chat_merge`` 做行级/条目级并集合并。

对端路径由 ``PeerLayout`` 的两种实现解析（中转目录 ``HubLayout`` / 对端仓库 ``RepoLayout``），
细节见各自的类注释。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

BASE_PROJECT = "project"
BASE_USER_DATA = "user_data"
BASE_STUDY = "study"
BASE_COMPANION = "companion"
ALL_BASES: Tuple[str, ...] = (BASE_PROJECT, BASE_USER_DATA, BASE_STUDY, BASE_COMPANION)

# 同步时一律跳过的目录名：缓存 / 版本库 / 备份目录
EXCLUDED_DIR_NAMES = frozenset({"__pycache__", ".git", "backups"})
# 同步时一律跳过的文件后缀：备份、损坏留档、传输临时文件、SQLite 派生库
EXCLUDED_SUFFIXES = (".bak", ".tmp", ".sync-tmp", ".db", ".db-wal", ".db-shm")
# 平台相关且体积巨大的设备使用流水，不属于学习数据
EXCLUDED_FILE_NAMES = frozenset({"app_usage.jsonl"})

#: 合并策略：整文件复制（默认），两端都改过时取 mtime 更新的一方。
MERGE_COPY = "copy"
#: 合并策略：JSONL 按 ``event_id`` 做行级并集（聊天记录，两边都可能追加）。
MERGE_JSONL = "jsonl_union"
#: 合并策略：JSON ``files`` 数组按 ``relative_path`` 做条目级并集（当天 index.json）。
MERGE_INDEX = "json_index_union"
#: 合并策略：记忆文件按条目身份（``id`` / 指纹键）取并集，同一条目取更新的一份。
MERGE_MEMORY = "memory_union"


@dataclass(frozen=True)
class SyncItem:
    """一条学习数据同步项。

    Attributes:
        group: 分组名，用于 ``--groups`` 过滤。
        base: 基准根，取 ``BASE_PROJECT`` / ``BASE_USER_DATA`` / ``BASE_STUDY`` /
            ``BASE_COMPANION``。
        rel: 相对基准根的路径（POSIX 分隔符）；支持 ``*`` / ``**`` 通配符，
            命中项统一换算成「相对基准根」的具体路径。
        recursive: 该项是目录且需要递归同步。
        merge: 两端都改过时的合并策略，取 ``MERGE_COPY`` / ``MERGE_JSONL`` /
            ``MERGE_INDEX``；非 ``MERGE_COPY`` 时不做「谁新用谁」的覆盖，
            而是把两边的行/条目并集写回双方。
    """

    group: str
    base: str
    rel: str
    recursive: bool = False
    merge: str = MERGE_COPY


#: 学习数据清单。新增学习数据只需往这里补一项，调用方不用改。
ITEMS: Tuple[SyncItem, ...] = (
    # 背单词：FSRS 调度进度与手动背诵统计
    SyncItem("vocab", BASE_PROJECT, "output/user_data/vocab_progress.json"),
    SyncItem("vocab", BASE_PROJECT, "output/user_data/vocab_meta.json"),
    # 背单词：每日生词日志、复习队列状态、长期生词本
    SyncItem("vocab", BASE_PROJECT, "data/study_data/English/Words/daily", recursive=True),
    SyncItem("vocab", BASE_PROJECT, "data/study_data/English/Words/unfamiliar_word.txt"),
    # 每日学习：计划 / 日记 / 学习摘要 / 每日画像
    SyncItem("daily", BASE_USER_DATA, "daily", recursive=True),
    SyncItem("daily", BASE_USER_DATA, "daily_records", recursive=True),
    SyncItem("daily", BASE_USER_DATA, "daily_vocab_status.json"),
    SyncItem("daily", BASE_USER_DATA, "daily_word_quiz_status.json"),
    # 专注会话记录
    SyncItem("focus", BASE_USER_DATA, "focus_sessions", recursive=True),
    # 学习系统状态：学习时长 / 正确率 / 知识点掌握度 / 薄弱点
    SyncItem("study_state", BASE_STUDY, ".state", recursive=True),
    # 聊天历史真源：两个系统都可能往同一个会话文件追加，按 event_id 并集合并
    SyncItem("chat", BASE_COMPANION, "*/chat_history/**/*.jsonl", merge=MERGE_JSONL),
    # 聊天历史当天的 index.json 只是该目录的列表投影，按条目并集合并
    SyncItem("chat", BASE_COMPANION, "*/chat_history/**/index.json", merge=MERGE_INDEX),
    # 记忆：短期 / 加权 / 会话列表 / 指纹索引的持久状态，按条目身份取并集
    SyncItem("memories", BASE_COMPANION, "*/memories/**/*.json", merge=MERGE_MEMORY),
)

GROUPS: Tuple[str, ...] = ("vocab", "daily", "focus", "study_state", "chat", "memories")


def items_for(groups: Optional[Sequence[str]] = None) -> Tuple[SyncItem, ...]:
    """按分组过滤清单；``groups`` 为空表示全选。"""
    if not groups:
        return ITEMS
    wanted = {g.strip() for g in groups if g and g.strip()}
    return tuple(item for item in ITEMS if item.group in wanted)


def bases_of(items: Sequence[SyncItem]) -> Tuple[str, ...]:
    """返回清单用到的基准根（去重、按固定顺序）。"""
    used = {item.base for item in items}
    return tuple(base for base in ALL_BASES if base in used)


def local_root(base: str) -> Path:
    """返回本机上某个基准根的绝对路径。

    Args:
        base: ``BASE_PROJECT`` / ``BASE_USER_DATA`` / ``BASE_STUDY`` / ``BASE_COMPANION``。

    Raises:
        ValueError: base 取值非法。
    """
    if base == BASE_PROJECT:
        from core.utils.common import get_project_root

        return get_project_root()
    if base == BASE_USER_DATA:
        from core.utils.data.data_paths import get_user_data_dir

        return get_user_data_dir()
    if base == BASE_STUDY:
        from core.services.study import paths as study_paths

        return study_paths.get_study_root()
    if base == BASE_COMPANION:
        from core.utils.data.data_paths import get_companion_data_dir

        return get_companion_data_dir()
    raise ValueError(f"未知的基准根: {base}")


def local_roots(items: Sequence[SyncItem]) -> Dict[str, Path]:
    """返回清单用到的全部本机基准根（惰性解析，取不到的根不报错）。"""
    roots: Dict[str, Path] = {}
    for base in bases_of(items):
        try:
            roots[base] = local_root(base)
        except Exception:  # noqa: BLE001 - 单个根解析失败不应连累其余分组
            continue
    return roots


class PeerLayout(ABC):
    """对端（另一个系统 / 中转目录）的路径解析。"""

    @abstractmethod
    def root(self, base: str) -> Optional[Path]:
        """返回对端某个基准根；返回 None 表示该基准根不可用。"""

    def resolve(self, base: str, rel: str) -> Optional[Path]:
        """返回对端文件的绝对路径；基准根不可用时返回 None。"""
        root = self.root(base)
        if root is None:
            return None
        return root / Path(rel)


class HubLayout(PeerLayout):
    """中转目录布局：``hub/{project,user_data,study,companion}/<rel>``。

    两个系统都指向同一个中转目录（放在两边都能读写的分区上）即可星型同步，
    不需要知道对方的仓库在哪，也不需要对方在线。
    """

    def __init__(self, hub: Path):
        self._hub = hub

    @property
    def hub(self) -> Path:
        """中转目录本身。"""
        return self._hub

    def root(self, base: str) -> Optional[Path]:
        return self._hub / base


class RepoLayout(PeerLayout):
    """对端仓库布局：直接按对端仓库根 / 数据根 / 学习库根拼接。

    适用于 Linux 挂载了 Windows 的 D 盘这类"能直接看到对方仓库"的场景。
    数据根默认取 ``<对端仓库根>/companion_data/user_data``；学习库根必须位于
    另一个系统上，无法凭空推导，只能靠跨平台镜像表猜，猜不出来就返回 None。
    """

    def __init__(
        self,
        peer_root: Path,
        peer_data_root: Optional[Path] = None,
        peer_study_root: Optional[Path] = None,
    ):
        self._peer_root = peer_root
        self._peer_data_root = peer_data_root
        self._peer_study_root = peer_study_root

    def root(self, base: str) -> Optional[Path]:
        if base == BASE_PROJECT:
            return self._peer_root
        if base == BASE_USER_DATA:
            return self._peer_data_root or (self._peer_root / "companion_data" / "user_data")
        if base == BASE_COMPANION:
            return self._peer_root / "companion_data"
        if base == BASE_STUDY:
            if self._peer_study_root:
                return self._peer_study_root
            try:
                return guess_peer_study_root(local_root(BASE_STUDY))
            except Exception:  # noqa: BLE001 - 猜不出来由调用方提示用户显式指定
                return None
        return None


def guess_peer_study_root(local_study_root: Path) -> Optional[Path]:
    """按跨平台镜像表推断「另一个系统」上的学习库根。

    Windows 侧学习库通常是 ``D:\\AI\\Study``，Linux 侧经镜像表落到 ``~/Study``。
    本机在 Windows 时按镜像表正向查；本机在 Linux 时反查镜像表还原盘符路径。
    查不到就返回 None，由调用方要求用户显式传 ``--peer-study-root``。
    """
    mirrors = _mirror_table()
    if os.name == "nt":
        key = str(local_study_root).replace("\\", "/").strip().rstrip("/").lower()
        mirrored = mirrors.get(key)
        return Path(mirrored).expanduser() if mirrored else None
    for windows_path, posix_path in mirrors.items():
        try:
            if Path(posix_path).expanduser().resolve() == Path(local_study_root).resolve():
                return Path(windows_path)
        except OSError:
            continue
    return None


def _mirror_table() -> Dict[str, str]:
    """读取 data_paths 的跨平台镜像表（读不到时用内置默认值兜底）。"""
    try:
        from core.utils.data import data_paths

        table = getattr(data_paths, "_POSIX_WINDOWS_PATH_MIRRORS", None)
        if table:
            return dict(table)
    except Exception:  # noqa: BLE001 - 镜像表只是辅助推断，取不到走内置默认
        pass
    return {"d:/ai/study": "~/Study"}
