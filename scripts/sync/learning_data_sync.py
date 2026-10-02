"""学习数据跨系统同步入口（Windows / Linux 双启动场景）。

双启动下同一时刻只有一个系统在线，两端各持有一份仓库与运行时数据，因此同步走
:「中转目录（hub）」或「直接读对端仓库」两种对端布局：

- ``--hub``：两个系统都指向同一个中转目录（必须放在两边都能读写的分区上），
  切换系统后各跑一次即可拉平，不需要对方在线；
- ``--peer-root``：Linux 挂载了 Windows 的 D 盘时用，直接和对端仓库对账。

比对用「本机 / 对端 / 上次基线」三向判定方向；其中 ``chat`` 分组（聊天历史）
两端都可能往同一个 JSONL 追加，整文件覆盖会丢消息，因此改走按 ``event_id``
的并集合并——详细清单与判定规则见 ``scripts/sync/README.md``。

默认只出计划（dry-run），确认无误后加 ``--apply`` 才真正落盘。

用法示例::

    # Windows：把学习数据推到 G 盘中转目录
    python scripts/sync/learning_data_sync.py --hub G:\\xiaoyou-sync --apply
    # Linux：挂载 G 盘后拉回本机
    python scripts/sync/learning_data_sync.py --hub /mnt/G/xiaoyou-sync --apply

详见 ``scripts/sync/README.md``。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.utils.logger import get_logger  # noqa: E402

from scripts.sync.learning_data.items import (  # noqa: E402
    MERGE_COPY,
    HubLayout,
    PeerLayout,
    RepoLayout,
    SyncItem,
    bases_of,
    items_for,
    local_roots,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.planner import (  # noqa: E402
    CONFLICT,
    DELETE_LOCAL,
    DELETE_PEER,
    MERGE,
    PULL,
    PUSH,
    SKIP,
    DROPPED,
    plan,
)
from scripts.sync.learning_data.transfer import (  # noqa: E402
    apply_actions,
    load_state,
    save_state,
)

logger = get_logger("LearningDataSync")

#: 中转目录路径的环境变量兜底，便于把同步挂进启动脚本
HUB_ENV = "XIAOYOU_LEARNING_SYNC_HUB"

#: 基准根 → 显式指定对端目录用的命令行参数
_PEER_FLAG_OF = {
    "project": "--peer-root",
    "user_data": "--peer-data-root",
    "study": "--peer-study-root",
    "companion": "--peer-root",
}

_PLAN_LIMIT = 40


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="learning_data_sync",
        description="在 Windows / Linux 双系统之间同步学习数据与聊天历史（默认只出计划）",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--hub", help="中转目录（两边都能读写的分区上的同一个目录）")
    target.add_argument("--peer-root", help="对端仓库根目录（能直接看到对方仓库时用）")
    parser.add_argument("--peer-data-root", help="对端用户数据目录，默认 <对端仓库>/companion_data/user_data")
    parser.add_argument("--peer-study-root", help="对端学习库根目录，默认按跨平台镜像表推断")
    parser.add_argument("--groups", help=f"只同步指定分组，逗号分隔；可选：{', '.join(_group_names())}")
    parser.add_argument("--apply", action="store_true", help="真正执行同步（默认只打印计划）")
    parser.add_argument(
        "--propagate-delete",
        action="store_true",
        help="一端删除时同步删除另一端（默认只报告不删除）",
    )
    parser.add_argument("--state", help="同步基线文件路径，默认 companion_data/sync/learning_data_state.json")
    parser.add_argument("--max-mb", type=float, default=16.0, help="单文件体积上限（MB），超过则跳过")
    parser.add_argument("--auto", action="store_true", help="无人值守模式：没有可用对端时静默退出")
    return parser


def _ensure_dir(path: Path) -> bool:
    """目录不存在时补建最后一层；父目录也不存在则放弃，返回目录是否可用。"""
    if path.exists():
        return True
    if not path.parent.exists():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _group_names() -> List[str]:
    from scripts.sync.learning_data.items import GROUPS

    return list(GROUPS)


def build_peer_layout(args: argparse.Namespace) -> Optional[PeerLayout]:
    """按参数构造对端布局；无法确定对端时返回 None。"""
    hub = args.hub or os.environ.get(HUB_ENV, "").strip()
    if not hub:
        # 配了跨系统共享根时默认用它下面的 learning_hub，两个系统天然对上同一个目录
        from core.utils.shared_roots import get_learning_hub_root

        fallback = get_learning_hub_root()
        hub = str(fallback) if fallback else ""
    if hub:
        return HubLayout(Path(hub).expanduser())
    if args.peer_root:
        return RepoLayout(
            Path(args.peer_root).expanduser(),
            Path(args.peer_data_root).expanduser() if args.peer_data_root else None,
            Path(args.peer_study_root).expanduser() if args.peer_study_root else None,
        )
    return None


def default_state_path() -> Path:
    """返回默认同步基线路径（companion_data/sync/learning_data_state.json）。"""
    try:
        from core.utils.data.data_paths import get_companion_data_dir

        return get_companion_data_dir() / "sync" / "learning_data_state.json"
    except Exception:  # noqa: BLE001 - 数据根不可用时退回仓库内的默认位置
        return _PROJECT_ROOT / "companion_data" / "sync" / "learning_data_state.json"


def verify_peer(layout: PeerLayout, items: Sequence[SyncItem]) -> List[str]:
    """校验对端基准根可用；返回错误列表（空表示可用）。

    hub 布局会自动创建缺失的子目录（hub 本身不存在则报错），
    对端仓库布局只校验不创建，避免把数据写到错误的位置。
    """
    errors: List[str] = []
    for base in bases_of(items):
        root = layout.root(base)
        if root is None:
            errors.append(f"无法确定对端 {base} 目录，请用 {_PEER_FLAG_OF.get(base, '--peer-root')} 显式指定")
            continue
        if root.exists():
            continue
        if isinstance(layout, HubLayout):
            # 中转目录按需创建：只补最后一层，父目录不存在就报错，避免写错位置
            if not _ensure_dir(root.parent):
                errors.append(f"中转目录的父目录不存在：{root.parent}")
                continue
            root.mkdir(parents=True, exist_ok=True)
        else:
            errors.append(f"对端目录不存在：{root}")
    return errors


def run(args: argparse.Namespace) -> int:
    """执行一次同步，返回进程退出码。"""
    items = items_for(args.groups.split(",") if args.groups else None)
    if not items:
        print("没有匹配的学习数据分组，可用分组：" + ", ".join(_group_names()))
        return 2

    layout = build_peer_layout(args)
    if layout is None:
        message = f"未指定对端：用 --hub（或环境变量 {HUB_ENV}）指定中转目录，或用 --peer-root 指定对端仓库"
        if args.auto:
            logger.info("自动同步跳过：%s", message)
            return 0
        print(message)
        return 2
    errors = verify_peer(layout, items)
    if errors:
        for line in errors:
            print(line)
        return 2

    roots = local_roots(items)
    max_bytes = int(max(args.max_mb, 0.0) * 1024 * 1024)
    skipped: List[dict] = []
    modes: Dict[str, str] = {}
    local = scan(items, roots.get, max_bytes=max_bytes, skipped=skipped, modes=modes)
    peer = scan(items, layout.root, max_bytes=max_bytes, skipped=skipped, modes=modes)

    state_path = Path(args.state).expanduser() if args.state else default_state_path()
    state = load_state(state_path)
    actions = plan(
        local,
        peer,
        state,
        propagate_delete=args.propagate_delete,
        merge_mode_of=lambda key: modes.get(key, MERGE_COPY),
    )

    print(f"学习数据同步（{'执行' if args.apply else '计划'}）：本机 {len(local)} 项 / 对端 {len(peer)} 项")
    _print_plan(actions, skipped)

    if not args.apply:
        print("\n这是计划预览，加 --apply 才会真正同步。")
        return 0

    result = apply_actions(
        actions,
        local_of=lambda base, rel: roots[base] / Path(rel),
        peer_of=lambda base, rel: layout.resolve(base, rel),
        state=state,
    )
    save_state(state_path, state)
    _print_result(result)
    return 1 if result.failed else 0


def _print_plan(actions, skipped: List[dict]) -> None:
    """打印同步计划（超长时截断）。"""
    active = [a for a in actions if a.kind not in (SKIP, DROPPED)]
    counts = {kind: sum(1 for a in actions if a.kind == kind) for kind in _kinds()}
    print(
        "计划：推送 {push} / 拉取 {pull} / 合并 {merge} / 冲突 {conflict} / 删除 {dele} / 跳过 {skip}".format(
            push=counts.get(PUSH, 0),
            pull=counts.get(PULL, 0),
            merge=counts.get(MERGE, 0),
            conflict=counts.get(CONFLICT, 0),
            dele=counts.get(DELETE_LOCAL, 0) + counts.get(DELETE_PEER, 0),
            skip=counts.get(SKIP, 0) + counts.get(DROPPED, 0),
        )
    )
    for action in active[:_PLAN_LIMIT]:
        print(f"  [{action.direction or action.kind}] {action.key} —— {action.reason}")
    if len(active) > _PLAN_LIMIT:
        print(f"  …… 其余 {len(active) - _PLAN_LIMIT} 项省略")
    for item in skipped[:10]:
        print(f"  [跳过] {item['key']} —— {item['reason']}")


def _print_result(result) -> None:
    """打印执行结果。"""
    print(
        "完成：推送 {} / 拉取 {} / 合并 {} / 冲突 {} / 删除 {}".format(
            result.pushed, result.pulled, result.merged, result.conflicts, result.deleted
        )
    )
    for path in result.backups[:10]:
        print(f"  冲突副本：{path}")
    for line in result.failed[:10]:
        print(f"  失败：{line}")


def _kinds() -> List[str]:
    return [PUSH, PULL, MERGE, CONFLICT, DELETE_LOCAL, DELETE_PEER, SKIP, DROPPED]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口。"""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
