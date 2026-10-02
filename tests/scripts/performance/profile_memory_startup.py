"""Memory 启动链路分段耗时 profiling（计划 §4）。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/performance/profile_memory_startup.py
    venv_core\\Scripts\\python.exe tests/scripts/performance/profile_memory_startup.py --user-id shared__scope__ling
    venv_core\\Scripts\\python.exe tests/scripts/performance/profile_memory_startup.py --all --with-search

产出：`WeightedMemoryManager._deferred_load` 全链路的分段耗时表（M1~M12）+ 占比，
用于决定后续优化方向（M3 embedding 补算 / M4 C++ addRecord / M2+M5+M6+M8 多次全量遍历）。

安全：**默认只读**——把 `save_memory` / `sync_save_memory` 换成 no-op，绝不改写真实记忆文件；
M8b/M9 里的落盘耗时因此不计入。要测真实落盘成本加 `--allow-write`（会重写真实记忆文件）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Memory 启动分段耗时 profiling")
    parser.add_argument("--user-id", default=None, help="记忆主体 ID，如 shared__scope__ling")
    parser.add_argument("--all", action="store_true", help="对数据量最大的前 3 个主体各跑一遍")
    parser.add_argument("--timeout", type=float, default=120.0, help="等待后台加载的秒数")
    parser.add_argument(
        "--with-search", action="store_true", help="额外触发一次首检索，测量 M10/M11 懒构建"
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="允许落盘（会重写真实记忆文件）；默认只读",
    )
    parser.add_argument(
        "--no-embedding",
        action="store_true",
        help="跳过 M3 缺失 embedding 补算（会顺带跳过 ORT/CUDA 预热，便于快速反复测其余阶段）",
    )
    parser.add_argument(
        "--save-profile",
        action="store_true",
        help="额外测量「整份 weighted JSON 重写」耗时（写临时目录，不动真实记忆文件），"
        "用于判断计划 §6 的 mutation journal 是否值得做",
    )
    parser.add_argument("--save-repeat", type=int, default=3, help="保存测量重复次数")
    parser.add_argument("--json", action="store_true", help="额外输出 JSON 明细")
    return parser.parse_args()


def _discover_user_ids() -> list[tuple[str, int]]:
    """扫描所有 scope 的 weighted 文件，按主体汇总字节数。"""
    totals: dict[str, int] = defaultdict(int)
    companion = ROOT / "companion_data"
    if not companion.exists():
        return []
    for path in companion.glob("*/memories/weighted/**/*_weighted.json"):
        user_id = path.name[: -len("_weighted.json")]
        if not user_id:
            continue
        try:
            totals[user_id] += path.stat().st_size
        except OSError:
            continue
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _profile_one(user_id: str, args: argparse.Namespace) -> dict:
    from memory.core import startup_profile
    from memory.weighted_memory_manager import WeightedMemoryManager

    startup_profile.reset()
    manager = WeightedMemoryManager(user_id=user_id, auto_save_interval=0)

    if not args.allow_write:
        manager.save_memory = lambda *a, **k: None
        manager.sync_save_memory = lambda *a, **k: None

    if args.no_embedding:
        manager.generate_missing_embeddings = lambda *a, **k: 0

    started = time.perf_counter()
    loaded = manager.ensure_data_loaded(timeout=args.timeout)
    wall_seconds = time.perf_counter() - started

    search_seconds = None
    if args.with_search:
        started = time.perf_counter()
        try:
            manager.hybrid_search("最近聊过什么", limit=5)
        except Exception as exc:  # 检索失败不影响分段表
            print(f"  [warn] 首检索失败（忽略）: {exc}")
        search_seconds = time.perf_counter() - started

    result = {
        "user_id": user_id,
        "loaded": loaded,
        "wall_seconds": wall_seconds,
        "weighted_memories": len(manager.weighted_memories),
        "short_term": len(manager.short_term_memory),
        "first_search_seconds": search_seconds,
        "phases": startup_profile.snapshot(),
    }
    try:
        manager.shutdown()
    except Exception:
        pass
    return result


def _profile_save(user_id: str, args: argparse.Namespace) -> dict:
    """测量「整份 weighted JSON 重写」的耗时与产物体积（计划 §6 的触发依据）。

    走的是生产同一条 `save_weighted_data_locked`（compaction + 按 category 分文件 +
    fsync + 原子替换 + 清理 stale 文件），但 `weighted_memory_dir` 指向临时目录，
    **不会碰真实记忆文件**。
    """
    import logging

    from memory.core import io_ops
    from memory.weighted_memory_manager import WeightedMemoryManager

    manager = WeightedMemoryManager(user_id=user_id, auto_save_interval=0)
    manager.save_memory = lambda *a, **k: None
    manager.sync_save_memory = lambda *a, **k: None
    manager.ensure_data_loaded(timeout=args.timeout)

    tmp = tempfile.mkdtemp(prefix="xy_memory_save_")
    logger = logging.getLogger("memory_save_profile")
    timings: list[float] = []
    try:
        for _ in range(max(args.save_repeat, 1)):
            started = time.perf_counter()
            io_ops.save_weighted_data_locked(
                manager,
                weighted_memory_dir=Path(tmp),
                logger=logger,
                time_module=time,
            )
            timings.append(time.perf_counter() - started)
        total_bytes = sum(
            path.stat().st_size for path in Path(tmp).rglob("*") if path.is_file()
        )
        file_count = sum(1 for path in Path(tmp).rglob("*") if path.is_file())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            manager.shutdown()
        except Exception:
            pass

    return {
        "user_id": user_id,
        "weighted_memories": len(manager.weighted_memories),
        "runs": len(timings),
        "min_seconds": min(timings),
        "max_seconds": max(timings),
        "avg_seconds": sum(timings) / len(timings),
        "written_bytes": total_bytes,
        "written_files": file_count,
    }


def main() -> int:
    args = _parse_args()

    # 必须先于 memory 包导入打开埋点，否则初始化阶段的埋点会被跳过
    from memory.core import startup_profile

    startup_profile.configure(True)

    from core.utils.data import data_paths

    candidates = _discover_user_ids()
    if args.user_id:
        targets = [(args.user_id, 0)]
    elif args.all:
        targets = candidates[:3]
    else:
        targets = candidates[:1]

    if not targets:
        print("未在 companion_data/*/memories/weighted 下找到任何 *_weighted.json")
        return 2

    print(
        f"可用主体（按 weighted 体积降序，前 5）: "
        f"{', '.join(f'{name}({size / 1024:.0f}KB)' for name, size in candidates[:5])}",
        flush=True,
    )

    reports = []
    for user_id, _size in targets:
        print("", flush=True)
        result = _profile_one(user_id, args)
        reports.append(result)
        title = (
            f"Memory 启动分段耗时 — {user_id}"
            f"（记忆 {result['weighted_memories']} 条 / 短期 {result['short_term']} 条）"
        )
        print(startup_profile.format_report(title), flush=True)
        print(
            f"ensure_data_loaded 实际等待: {result['wall_seconds']:.4f}s"
            f"（loaded={result['loaded']}）"
            + (
                f" | 首检索: {result['first_search_seconds']:.4f}s"
                if result["first_search_seconds"] is not None
                else ""
            ),
            flush=True,
        )
        if not args.allow_write:
            print("（只读模式：save_memory / sync_save_memory 已置为 no-op）", flush=True)

    if args.json:
        print("", flush=True)
        print("JSON: " + json.dumps(reports, ensure_ascii=False), flush=True)

    if args.save_profile:
        print("", flush=True)
        print("== 整份 weighted JSON 重写耗时（计划 §6 触发依据）==", flush=True)
        print(
            f"{'主体':<32}{'记忆数':>8}{'最小(s)':>10}{'平均(s)':>10}"
            f"{'最大(s)':>10}{'产物(MB)':>10}{'文件数':>8}",
            flush=True,
        )
        for user_id, _size in targets:
            save_result = _profile_save(user_id, args)
            print(
                f"{user_id:<32}{save_result['weighted_memories']:>8}"
                f"{save_result['min_seconds']:>10.4f}"
                f"{save_result['avg_seconds']:>10.4f}"
                f"{save_result['max_seconds']:>10.4f}"
                f"{save_result['written_bytes'] / 1024 / 1024:>10.2f}"
                f"{save_result['written_files']:>8}",
                flush=True,
            )
            if args.json:
                print("  JSON: " + json.dumps(save_result, ensure_ascii=False), flush=True)

    # `_ensure_initialized` 是懒触发的（第一次 get_* 才跑），必须等上面跑完再读
    print(
        "",
        flush=True,
    )
    print(
        f"data_paths._ensure_initialized: {data_paths._INIT_SECONDS:.4f}s"
        "（一次性，含 _migrate_legacy_layout / 角色目录 mkdir / "
        "_migrate_self_meals_from_user_records 全量扫描）",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
