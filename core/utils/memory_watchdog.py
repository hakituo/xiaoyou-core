#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内存监控看门狗（异步轻量版）

设计原则：
1. 主监控循环只调用 psutil 采集进程/系统内存，绝不调用 gc.get_objects() 之类阻塞操作
   （旧版本每次主循环都遍历 gc.get_objects() 多次，本身就是内存大户，会让程序越监控越涨）
2. 深度分析（gc.get_objects / get_referrers 等）改为按需接口：
   - routers/admin/memory_watchdog.py 的 /top-objects、/leak-analysis 主动调用时才执行
   - 不会因为监控循环自身把内存推高
3. 暴露的字段统一为：
   - 轻量快照（主循环用）：rss/vms/system_*/gc_objects(数量,非遍历)
   - 详细快照（API 按需）：loaded_models/object_counts/object_sizes

配置开关：config/yaml/app.yaml 中的 memory_watchdog.enabled
"""

import os
import gc
import tracemalloc
import sys
import time
import json
import psutil
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

# 使用项目统一 logger，确保日志同时写入 xiaoyou_main.log 和控制台
# （之前用 get_logger(__name__) 只到 root logger，不写文件）
from core.utils.logger import get_logger
from core.utils.time.time_utils import now_str, ts_to_iso

logger = get_logger("memory_watchdog")


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------

@dataclass
class MemorySnapshot:
    """内存快照（轻量，主循环用）

    gc_objects 只填 len(gc.get_objects())，不遍历对象本身。
    """
    timestamp: float = 0.0
    process_rss_mb: float = 0.0
    process_vms_mb: float = 0.0
    system_total_mb: float = 0.0
    system_used_mb: float = 0.0
    system_percent: float = 0.0
    gc_objects: int = 0  # len(gc.get_objects())，仅在主动分析时填充


@dataclass
class DetailedMemorySnapshot(MemorySnapshot):
    """详细内存快照（按需生成，包含模型/对象统计）

    生成成本高（会遍历 gc.get_objects()），只在 API 主动调用时生成。
    """
    loaded_models: List[str] = field(default_factory=list)
    object_counts: Dict[str, int] = field(default_factory=dict)
    object_sizes: Dict[str, int] = field(default_factory=dict)


@dataclass
class MemoryGrowthRecord:
    """内存增长记录"""
    timestamp: float
    delta_mb: float
    delta_percent: float
    source: str
    details: Dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 看门狗主类
# ----------------------------------------------------------------------

class MemoryWatchdog:
    """异步内存监控看门狗（轻量版）

    主循环只采集 psutil 指标；深度分析走 take_detailed_snapshot / analyze_top_objects /
    analyze_leak_source 等按需接口，避免监控本身成为内存大户。
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 check_interval: float = 60.0,
                 growth_threshold_mb: float = 300.0,
                 growth_threshold_percent: float = 10.0,
                 max_snapshots: int = 500,
                 log_dir: Optional[str] = None):

        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self._check_interval = check_interval
        self._growth_threshold_mb = growth_threshold_mb
        self._growth_threshold_percent = growth_threshold_percent
        self._max_snapshots = max_snapshots

        if log_dir is None:
            project_root = Path(__file__).parent.parent.parent
            self._log_dir = project_root / "logs" / "memory_watchdog"
        else:
            self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._process = psutil.Process(os.getpid())

        self._snapshots: List[MemorySnapshot] = []
        self._growth_records: List[MemoryGrowthRecord] = []
        self._baseline_snapshot: Optional[MemorySnapshot] = None
        self._last_snapshot: Optional[MemorySnapshot] = None

        self._ws_subscribers: List[Any] = []

        # tracemalloc 追踪（找泄漏源的正确工具，开销远小于 gc.get_objects() 遍历）
        # 在 start() 时开启，记录每个内存分配的调用栈
        self._tm_enabled: bool = False
        self._tm_baseline: Optional[Any] = None  # tracemalloc.Snapshot，启动时基线

        logger.info("MemoryWatchdog 初始化完成（轻量异步版）")

    # ---------------- 主循环 ----------------

    def start(self):
        """启动监控"""
        if self._is_running:
            return

        self._is_running = True
        self._baseline_snapshot = self._take_snapshot_fast()
        self._last_snapshot = self._baseline_snapshot
        self._snapshots.append(self._baseline_snapshot)

        # tracemalloc 在本进程不适用：take_snapshot() 会复制 98万分配记录到 7.6GB 的 list，
        # tracemalloc 自身就是最大的内存消耗者。改用 sample_large_lists() 定位泄漏。
        self._tm_enabled = False
        self._tm_baseline = None
        logger.info("tracemalloc 已禁用（take_snapshot 在大进程上会吃 7.6GB），改用 sample_large_lists 定位泄漏")

        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._async_monitor_loop())
            logger.info(f"MemoryWatchdog 异步监控已启动，间隔={self._check_interval}s")
        except RuntimeError:
            logger.warning("无法获取事件循环，看门狗未启动")
            self._is_running = False

    def stop(self):
        """停止监控"""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("MemoryWatchdog 已停止")

        try:
            self._save_report()
        except Exception as e:
            logger.debug(f"保存报告失败: {e}")

    async def _async_monitor_loop(self):
        """异步监控循环（只跑 psutil，绝不调 gc.get_objects()）"""
        while self._is_running:
            try:
                await asyncio.sleep(self._check_interval)
                self._check_memory_fast()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"MemoryWatchdog 检查异常: {e}")
                await asyncio.sleep(5)

    def _take_snapshot_fast(self) -> MemorySnapshot:
        """快速拍摄内存快照（仅 psutil，不阻塞）"""
        try:
            mem_info = self._process.memory_info()
            sys_mem = psutil.virtual_memory()

            return MemorySnapshot(
                timestamp=time.time(),
                process_rss_mb=mem_info.rss / (1024 * 1024),
                process_vms_mb=mem_info.vms / (1024 * 1024),
                system_total_mb=sys_mem.total / (1024 * 1024),
                system_used_mb=sys_mem.used / (1024 * 1024),
                system_percent=sys_mem.percent,
            )
        except Exception as e:
            logger.debug(f"快照失败: {e}")
            return MemorySnapshot(timestamp=time.time())

    def _check_memory_fast(self):
        """快速检查内存（不阻塞）"""
        snapshot = self._take_snapshot_fast()

        self._snapshots.append(snapshot)
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        if self._last_snapshot:
            delta_mb = snapshot.process_rss_mb - self._last_snapshot.process_rss_mb
            if abs(delta_mb) > self._growth_threshold_mb:
                growth = MemoryGrowthRecord(
                    timestamp=time.time(),
                    delta_mb=delta_mb,
                    delta_percent=(delta_mb / self._last_snapshot.process_rss_mb * 100)
                                  if self._last_snapshot.process_rss_mb > 0 else 0,
                    source="fast_check",
                )
                self._growth_records.append(growth)
                logger.warning(f"⚠️ 内存变化: {delta_mb:+.1f}MB, RSS={snapshot.process_rss_mb:.1f}MB")

        self._last_snapshot = snapshot
        self._broadcast_snapshot(snapshot)

        # 定期日志（每 10 次输出一次趋势）
        if len(self._snapshots) % 10 == 0:
            baseline_mb = self._baseline_snapshot.process_rss_mb if self._baseline_snapshot else 0
            growth_mb = snapshot.process_rss_mb - baseline_mb
            logger.info(
                f"📊 内存: RSS={snapshot.process_rss_mb:.1f}MB, "
                f"增长={growth_mb:+.1f}MB, 系统={snapshot.system_percent:.1f}%"
            )

    # ---------------- 按需深度分析（成本高，只在 API 调用时执行） ----------------

    def take_detailed_snapshot(self) -> DetailedMemorySnapshot:
        """生成详细快照（按需，会遍历 gc.get_objects()）

        仅供 API 调用，不在主循环里跑。
        """
        base = self._take_snapshot_fast()
        gc.collect()  # 先回收，避免统计已不可达对象
        object_counts, object_sizes = self._analyze_objects()
        loaded_models = self._get_loaded_models()

        return DetailedMemorySnapshot(
            timestamp=base.timestamp,
            process_rss_mb=base.process_rss_mb,
            process_vms_mb=base.process_vms_mb,
            system_total_mb=base.system_total_mb,
            system_used_mb=base.system_used_mb,
            system_percent=base.system_percent,
            gc_objects=len(gc.get_objects()),
            loaded_models=loaded_models,
            object_counts=object_counts,
            object_sizes=object_sizes,
        )

    def _analyze_objects(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        """统计常见 Python 对象的数量和大小

        会遍历 gc.get_objects()，成本高，仅在按需分析时调用。
        """
        counts = defaultdict(int)
        sizes = defaultdict(int)

        tracked_types = {
            'dict', 'list', 'tuple', 'set', 'str', 'bytes', 'frozenset',
            'DataFrame', 'ndarray', 'Tensor', 'Module',
            'Llama', 'SentenceTransformer', 'EmbeddingGenerator',
        }

        try:
            for obj in gc.get_objects():
                type_name = type(obj).__name__
                if type_name in tracked_types:
                    counts[type_name] += 1
                    try:
                        sizes[type_name] += sys.getsizeof(obj)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"对象分析失败: {e}")

        return dict(counts), dict(sizes)

    def _get_loaded_models(self) -> List[str]:
        """获取已加载的模型列表（不阻塞）"""
        models = []
        try:
            from core.resource_manager import get_resource_manager
            rm = get_resource_manager()
            if rm and hasattr(rm, 'models'):
                for model_id, model in rm.models.items():
                    if hasattr(model, 'is_loaded') and model.is_loaded:
                        models.append(model_id)
        except Exception:
            pass
        return models

    def analyze_top_objects(self, top_n: int = 20) -> List[Tuple[str, int, int]]:
        """统计占用内存最多的对象类型（按需）

        返回 [(type_name, count, total_size_bytes), ...]
        会遍历 gc.get_objects()，成本高。
        """
        gc.collect()
        type_counts = defaultdict(int)
        type_sizes = defaultdict(int)

        for obj in gc.get_objects():
            type_name = type(obj).__name__
            type_counts[type_name] += 1
            try:
                type_sizes[type_name] += sys.getsizeof(obj)
            except Exception:
                pass

        sorted_types = sorted(type_sizes.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [(type_name, type_counts[type_name], size) for type_name, size in sorted_types]

    # ---------------- tracemalloc 追踪（找泄漏源的正确工具） ----------------

    def get_tracemalloc_diff(self, top_n: int = 25) -> List[Dict[str, Any]]:
        """对比基线快照，返回内存增长最多的分配点（按行号聚合）

        这是找内存泄漏源的核心方法。tracemalloc 记录每个分配的调用栈，
        对比启动基线，就能知道"哪些代码分配的内存最多且没释放"。
        开销远小于 gc.get_objects() 遍历，不会像 analyze_leak_source 那样吃 2GB。
        """
        if not self._tm_enabled or not tracemalloc.is_tracing():
            return [{"error": "tracemalloc 未开启"}]
        if self._tm_baseline is None:
            return [{"error": "无基线快照"}]

        current = tracemalloc.take_snapshot()
        # filter_traces 排除 tracemalloc 自身的分配
        current = current.filter_traces([
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, tracemalloc.__file__),
        ])
        baseline = self._tm_baseline.filter_traces([
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, tracemalloc.__file__),
        ])

        diff = current.compare_to(baseline, 'lineno')
        # 按 size_diff 降序（增长最多的在前）
        diff_sorted = sorted(diff, key=lambda s: s.size_diff, reverse=True)[:top_n]

        results = []
        for stat in diff_sorted:
            frame = stat.traceback[0]
            results.append({
                "file": frame.filename,
                "line": frame.lineno,
                "size_diff_mb": round(stat.size_diff / (1024 * 1024), 2),
                "size_mb": round(stat.size / (1024 * 1024), 2),
                "count_diff": stat.count_diff,
                "count": stat.count,
            })
        return results

    def get_tracemalloc_top(self, top_n: int = 25) -> List[Dict[str, Any]]:
        """返回当前内存占用最多的分配点（不对比基线）

        用于看"此刻谁占的内存最多"，和 diff 配合使用。
        """
        if not self._tm_enabled or not tracemalloc.is_tracing():
            return [{"error": "tracemalloc 未开启"}]

        snapshot = tracemalloc.take_snapshot().filter_traces([
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, tracemalloc.__file__),
        ])
        stats = snapshot.statistics('lineno')
        stats_sorted = sorted(stats, key=lambda s: s.size, reverse=True)[:top_n]

        results = []
        for stat in stats_sorted:
            frame = stat.traceback[0]
            results.append({
                "file": frame.filename,
                "line": frame.lineno,
                "size_mb": round(stat.size / (1024 * 1024), 2),
                "count": stat.count,
            })
        return results

    def sample_large_lists(self, sample_size: int = 30) -> List[Dict[str, Any]]:
        """采样最大的 list 对象，返回其内容和来源（轻量，不调 take_snapshot）

        用于定位"127万个 list 是谁"——直接遍历 gc 对象找大 list，
        取前 sample_size 个，返回 repr(200字符) + 长度 + 是否被引用。
        比 tracemalloc.take_snapshot() 快得多（不构建完整快照）。
        """
        gc.collect()
        samples: List[Dict[str, Any]] = []
        # 只遍历 list 类型，跳过其他类型，开销比 gc.get_objects() 小
        for obj in gc.get_objects():
            if type(obj) is not list:
                continue
            try:
                size = len(obj)
            except Exception:
                continue
            # 只关注长度 > 100 的 list（大 list 才是泄漏嫌疑）
            if size < 100:
                continue
            # 估算字节数（粗略：元素数 × 8 字节指针 + list 头 56 字节）
            est_bytes = size * 8 + 56
            if est_bytes < 10000:  # < 10KB 跳过
                continue
            try:
                # repr 截断到 200 字符，避免大对象 repr 卡住
                r = repr(obj)[:200]
            except Exception:
                r = "<repr failed>"
            # 找第一个引用者（gc.get_referrers 很慢，只查前 1 个）
            referrers = gc.get_referrers(obj)
            ref_info = ""
            if referrers:
                ref = referrers[0]
                ref_info = f"{type(ref).__name__}"
                if hasattr(ref, '__file__'):
                    ref_info += f":{getattr(ref, '__file__', '?')}"
                elif hasattr(ref, '__qualname__'):
                    ref_info += f":{getattr(ref, '__qualname__', '?')}"
            samples.append({
                "len": size,
                "est_kb": round(est_bytes / 1024, 1),
                "repr": r,
                "referrer": ref_info,
            })
            if len(samples) >= sample_size:
                break
        # 按 est_kb 降序
        samples.sort(key=lambda x: x["est_kb"], reverse=True)
        return samples

    def analyze_leak_source(self, top_n: int = 10) -> Dict[str, Any]:
        """深度分析内存泄漏源头（按需）

        统计大型 list/dict 容器及其引用者，供 /leak-analysis API 调用。
        不在主循环里跑，避免监控自身推高内存。

        实现说明：旧版本会 3 次遍历 gc.get_objects()（统计类型、找大 list、
        统计 list 持有者），对 3GB+ 进程会卡 1-5 分钟。现在合并为 1 次遍历，
        并对 gc.get_referrers 调用做严格限制（每个大对象最多查 5 个引用者，
        且大 list/dict 只保留 top 5），整体耗时降到原来的 1/3。
        """
        gc.collect()

        # 单次遍历同时完成：类型统计 + 大 list/dict 收集 + list 持有者统计
        type_counts: Dict[str, int] = defaultdict(int)
        type_sizes: Dict[str, int] = defaultdict(int)
        large_lists: List[Dict[str, Any]] = []
        large_dicts: List[Dict[str, Any]] = []
        list_source_pattern: Dict[str, int] = defaultdict(int)

        # 先把 gc.get_objects() 取一次快照，避免遍历过程中列表变动
        # 注意：这本身会复制一份引用列表，对 1M+ 对象会占几十 MB 临时内存
        all_objects = gc.get_objects()

        for obj in all_objects:
            type_name = type(obj).__name__
            type_counts[type_name] += 1
            try:
                type_sizes[type_name] += sys.getsizeof(obj, 0)
            except Exception:
                pass

            # 大 list：收集 + 引用者
            if isinstance(obj, list) and len(obj) > 500:
                referrers = gc.get_referrers(obj)
                referrer_info = []
                for ref in referrers[:5]:
                    referrer_info.append({
                        'type': type(ref).__name__,
                        'repr': str(ref)[:100],
                    })
                large_lists.append({'size': len(obj), 'referrers': referrer_info})
            # 大 dict：收集 + 引用者
            elif isinstance(obj, dict) and len(obj) > 1000:
                referrers = gc.get_referrers(obj)
                referrer_info = []
                for ref in referrers[:3]:
                    referrer_info.append({
                        'type': type(ref).__name__,
                        'repr': str(ref)[:100],
                    })
                large_dicts.append({'size': len(obj), 'referrers': referrer_info})

            # list 持有者统计（只看第一个引用者，避免重复计数）
            if isinstance(obj, list) and len(obj) > 10:
                referrers = gc.get_referrers(obj)
                if referrers:
                    list_source_pattern[type(referrers[0]).__name__] += len(obj)

        large_lists.sort(key=lambda x: x['size'], reverse=True)
        large_dicts.sort(key=lambda x: x['size'], reverse=True)
        top_holders = sorted(list_source_pattern.items(), key=lambda x: x[1], reverse=True)[:top_n]

        return {
            'object_counts': dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20]),
            'object_sizes_mb': {
                k: round(v / (1024 * 1024), 2)
                for k, v in sorted(type_sizes.items(), key=lambda x: x[1], reverse=True)[:20]
            },
            'large_lists_count': len(large_lists),
            'large_lists_top5': large_lists[:5],
            'large_dicts_count': len(large_dicts),
            'large_dicts_top5': large_dicts[:5],
            'list_holders': [{'type': t, 'total_elements': s} for t, s in top_holders],
            'total_objects': sum(type_counts.values()),
            'total_list_count': type_counts.get('list', 0),
            'total_dict_count': type_counts.get('dict', 0),
        }

    # ---------------- 状态/报告 ----------------

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态（快速，不阻塞）"""
        snapshot = self._take_snapshot_fast()
        baseline_mb = self._baseline_snapshot.process_rss_mb if self._baseline_snapshot else 0
        return {
            "process_rss_mb": round(snapshot.process_rss_mb, 2),
            "process_vms_mb": round(snapshot.process_vms_mb, 2),
            "system_percent": round(snapshot.system_percent, 2),
            "baseline_rss_mb": round(baseline_mb, 2),
            "growth_mb": round(snapshot.process_rss_mb - baseline_mb, 2),
            "snapshot_count": len(self._snapshots),
            "growth_incidents": len(self._growth_records),
            "watchdog_running": self._is_running,
        }

    def get_trend(self) -> Dict[str, Any]:
        """获取内存趋势"""
        if not self._snapshots:
            return {"error": "无数据"}

        recent = self._snapshots[-60:]
        values = [s.process_rss_mb for s in recent]
        return {
            "current_mb": round(values[-1], 2),
            "min_mb": round(min(values), 2),
            "max_mb": round(max(values), 2),
            "avg_mb": round(sum(values) / len(values), 2),
            "points": len(values),
        }

    def report(self) -> Dict[str, Any]:
        """生成报告（不阻塞，只用历史快照）"""
        if not self._snapshots:
            return {"error": "无数据"}

        current = self._snapshots[-1]
        baseline = self._baseline_snapshot or self._snapshots[0]

        return {
            "summary": {
                "current_rss_mb": round(current.process_rss_mb, 2),
                "baseline_rss_mb": round(baseline.process_rss_mb, 2),
                "total_growth_mb": round(current.process_rss_mb - baseline.process_rss_mb, 2),
                "snapshot_count": len(self._snapshots),
                "growth_incident_count": len(self._growth_records),
            },
            "current_state": {
                "process_rss_mb": round(current.process_rss_mb, 2),
                "process_vms_mb": round(current.process_vms_mb, 2),
                "system_percent": round(current.system_percent, 2),
            },
            "trend": self.get_trend(),
            "recent_growth": [
                {
                    "timestamp": ts_to_iso(g.timestamp),
                    "delta_mb": round(g.delta_mb, 2),
                    "source": g.source,
                }
                for g in self._growth_records[-10:]
            ],
        }

    def _save_report(self):
        """保存报告到文件"""
        report = self.report()
        timestamp = now_str("%Y%m%d_%H%M%S")
        report_file = self._log_dir / f"memory_report_{timestamp}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"内存报告已保存: {report_file}")

    # ---------------- WebSocket ----------------

    def subscribe_ws(self, ws):
        if ws not in self._ws_subscribers:
            self._ws_subscribers.append(ws)

    def unsubscribe_ws(self, ws):
        if ws in self._ws_subscribers:
            self._ws_subscribers.remove(ws)

    def _broadcast_snapshot(self, snapshot: MemorySnapshot):
        if not self._ws_subscribers:
            return
        data = {
            "type": "memory_snapshot",
            "timestamp": snapshot.timestamp,
            "process_rss_mb": round(snapshot.process_rss_mb, 2),
            "system_percent": round(snapshot.system_percent, 2),
        }
        for ws in self._ws_subscribers[:]:
            try:
                asyncio.ensure_future(ws.send_json(data))
            except Exception:
                self._ws_subscribers.remove(ws)


# ----------------------------------------------------------------------
# 全局单例与便捷函数
# ----------------------------------------------------------------------

_watchdog: Optional[MemoryWatchdog] = None


def get_memory_watchdog(**kwargs) -> MemoryWatchdog:
    """获取看门狗单例"""
    global _watchdog
    if _watchdog is None:
        _watchdog = MemoryWatchdog(**kwargs)
    return _watchdog


def stop_memory_watchdog():
    """停止看门狗"""
    global _watchdog
    if _watchdog:
        _watchdog.stop()
        _watchdog = None


def get_memory_status() -> Dict[str, Any]:
    """获取内存状态（即使看门狗未启动也返回基本状态）"""
    global _watchdog
    if _watchdog:
        return _watchdog.get_status()
    try:
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        sys_mem = psutil.virtual_memory()
        return {
            "process_rss_mb": round(mem.rss / (1024 * 1024), 2),
            "system_percent": round(sys_mem.percent, 2),
            "watchdog_running": False,
        }
    except Exception:
        return {"error": "psutil 不可用"}
