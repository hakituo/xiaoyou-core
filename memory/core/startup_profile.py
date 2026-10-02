"""Memory 启动链路的分段耗时埋点（计划 §4.2）。

设计目标：**默认零开销、开启后可读**。

- 关闭时 ``phase()`` 只是一个 ``yield``，``accumulate()`` 只读一个全局 bool；
- 开启方式：环境变量 ``XY_MEMORY_STARTUP_PROFILE=1``，或调试配置
  ``memory_startup_profile``（``config/debug_config.py`` 的开关体系）；
- 埋点只累加，不打印、不落盘，由 ``profile_memory_startup.py`` 统一取 ``snapshot()``
  输出分段耗时表。

阶段编号沿用计划 §4.2 的 M1~M12，名称里带上人话，方便直接读表。
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

ENV_VAR = "XY_MEMORY_STARTUP_PROFILE"

#: 阶段顺序（用于报告排序，未发生的阶段也会列出来并标 0）
PHASE_ORDER: tuple[str, ...] = (
    "M1 weighted JSON 读取与反序列化",
    "M2 逐条规范化/去重合并",
    "M3 缺失 embedding 补算",
    "M3a 模型加载（含在 M3 内）",
    "M3a2 首次推理预热（含在 M3 内）",
    "M3b 逐条推理（含在 M3 内）",
    "M4 C++ addRecord 循环",
    "M5 rebuild_memory_indexes_locked",
    "M6 pending/shadow 统计 + gc.collect",
    "M7 short JSON 读 + 回填 + trim",
    "M7b 短期回填读 chat_history（含在 M7 内）",
    "M8 clean_memory_records",
    "M9 reclassify_all_memories",
    "M10 keyword 索引懒重建",
    "M11 relation graph 懒构建",
    "M12 legacy migration",
)

_LOCK = threading.Lock()
_ENTRIES: Dict[str, Dict[str, Any]] = {}
_ENABLED: Optional[bool] = None


def _resolve_enabled() -> bool:
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED
    enabled = False
    try:
        if str(os.environ.get(ENV_VAR, "")).strip().lower() in {"1", "true", "yes", "on"}:
            enabled = True
    except Exception:
        enabled = False
    if not enabled:
        try:
            from config.debug_config import is_debug_enabled

            enabled = bool(is_debug_enabled("memory_startup_profile"))
        except Exception:
            enabled = False
    _ENABLED = enabled
    return enabled


def is_enabled() -> bool:
    return _resolve_enabled()


def configure(enabled: bool) -> None:
    """显式开关（脚本/测试用），优先级高于环境变量与调试配置。"""
    global _ENABLED
    _ENABLED = bool(enabled)


def reset() -> None:
    with _LOCK:
        _ENTRIES.clear()


def accumulate(name: str, seconds: float, *, calls: int = 1) -> None:
    if _ENABLED is not True:
        return
    with _LOCK:
        entry = _ENTRIES.setdefault(name, {"seconds": 0.0, "calls": 0})
        entry["seconds"] += max(float(seconds), 0.0)
        entry["calls"] += int(calls)


@contextmanager
def phase(name: str):
    """给一段代码计时；未开启埋点时几乎无成本。"""
    if _ENABLED is not True:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        accumulate(name, time.perf_counter() - start)


def snapshot() -> List[Dict[str, Any]]:
    """按 PHASE_ORDER 返回分段耗时（含未发生的阶段，便于对比两次运行）。"""
    with _LOCK:
        raw = {key: dict(value) for key, value in _ENTRIES.items()}
    names = list(PHASE_ORDER) + [key for key in raw if key not in PHASE_ORDER]
    total = sum(
        float(raw.get(name, {}).get("seconds", 0.0))
        for name in names
        if not is_nested(name)
    )
    result = []
    for name in names:
        entry = raw.get(name, {"seconds": 0.0, "calls": 0})
        seconds = float(entry.get("seconds", 0.0))
        result.append(
            {
                "phase": name,
                "seconds": seconds,
                "calls": int(entry.get("calls", 0)),
                "nested": is_nested(name),
                "percent": (seconds / total * 100.0) if total > 0 else 0.0,
            }
        )
    return result


def is_nested(name: str) -> bool:
    """子阶段（已含在父阶段里）不参与合计，避免重复计数。"""
    return "（含在" in str(name)


def format_report(title: str = "Memory 启动分段耗时") -> str:
    rows = snapshot()
    total = sum(row["seconds"] for row in rows if not row["nested"])
    lines = [title, "-" * 76]
    lines.append(f"{'阶段':<44}{'耗时(s)':>10}{'占比':>9}{'次数':>8}")
    lines.append("-" * 76)
    for row in rows:
        label = f"  └ {row['phase']}" if row["nested"] else row["phase"]
        lines.append(
            f"{label:<44}{row['seconds']:>10.4f}"
            f"{row['percent']:>8.1f}%{row['calls']:>8}"
        )
    lines.append("-" * 76)
    lines.append(
        f"{'合计（不含子阶段）':<44}{total:>10.4f}"
        f"{100.0 if total > 0 else 0.0:>8.1f}%"
    )
    return "\n".join(lines)
