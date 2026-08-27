import asyncio
import re
import time
import hashlib
import json
import os
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from core.services.auto_heal.models import (
    AnomalyEvent,
    AnomalyRule,
    AnomalyType,
    ErrorFingerprint,
    DEFAULT_ANOMALY_RULES,
)
from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("AnomalyDetector")

_TRACEBACK_FILE_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+)')
_TRACEBACK_REL_RE = re.compile(r'File\s+"[^"]*?/(core/[^"]+)",\s+line\s+(\d+)')
_IGNORED_ERROR_TYPES = {
    "KeyboardInterrupt",
    "SystemExit",
    "asyncio.CancelledError",
}

# P1-5: 持久化配置 - 错误指纹 + 抑制状态 + 最近异常
# 解决重启后"重复错误检测失忆"和"已抑制规则重复触发"问题
_STATE_FILE_NAME = "anomaly_state.json"
_PERSIST_INTERVAL_SECONDS = 60.0  # 至少间隔 60 秒保存一次，避免高频写入
_MAX_PERSISTED_FINGERPRINTS = 500  # 防止无界增长
_MAX_PERSISTED_ANOMALIES = 100


class AnomalyDetector:
    def __init__(self, rules: Optional[List[AnomalyRule]] = None, suppress_duration: float = 300.0):
        self._rules = rules or list(DEFAULT_ANOMALY_RULES)
        self._errors: Deque[Tuple[float, Dict[str, Any]]] = deque(maxlen=10000)
        self._fingerprints: Dict[str, ErrorFingerprint] = {}
        self._anomalies: List[AnomalyEvent] = []
        self._last_check_ts: float = 0.0
        self._suppressed: Dict[str, float] = {}
        self._suppress_duration: float = suppress_duration
        # P1-5: 持久化相关
        self._state_file: Optional[Path] = self._resolve_state_file()
        self._last_persist_ts: float = 0.0
        self._dirty: bool = False  # 标记是否有未保存的状态变更
        self._load_state_sync()

    @classmethod
    def _resolve_state_file(cls) -> Optional[Path]:
        """解析持久化文件路径：{project_root}/logs/auto_heal/anomaly_state.json"""
        try:
            from core.utils.common import get_project_root

            return Path(get_project_root()) / "logs" / "auto_heal" / _STATE_FILE_NAME
        except Exception:
            return None

    def _load_state_sync(self) -> None:
        """P1-5: 启动时加载错误指纹和抑制状态"""
        if not self._state_file or not self._state_file.exists():
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 加载错误指纹
            for fp_dict in data.get("fingerprints") or []:
                try:
                    fp = ErrorFingerprint.from_dict(fp_dict)
                    if fp.fingerprint:
                        self._fingerprints[fp.fingerprint] = fp
                except Exception as e:
                    logger.warning("加载错误指纹失败（跳过）: %s", e)
            # 加载抑制状态
            self._suppressed = {
                str(k): float(v) for k, v in (data.get("suppressed") or {}).items()
            }
            # 加载最近异常事件（用于历史查看）
            for a_dict in data.get("anomalies") or []:
                try:
                    event = AnomalyEvent(
                        id=str(a_dict.get("id", "")),
                        anomaly_type=AnomalyType(a_dict.get("anomaly_type", "error_cluster")),
                        severity=a_dict.get("severity", "medium"),
                        title=str(a_dict.get("title", "")),
                        description=str(a_dict.get("description", "")),
                        detected_at=float(a_dict.get("detected_at", 0) or time.time()),
                        metric_name=str(a_dict.get("metric_name", "")),
                        metric_value=float(a_dict.get("metric_value", 0) or 0),
                        metric_threshold=float(a_dict.get("metric_threshold", 0) or 0),
                        auto_fixable=bool(a_dict.get("auto_fixable", False)),
                        metadata=dict(a_dict.get("metadata", {})),
                    )
                    self._anomalies.append(event)
                except Exception as e:
                    logger.warning("加载异常事件失败（跳过）: %s", e)
            logger.info(
                "AnomalyDetector 已加载持久化状态: %d 指纹, %d 抑制规则, %d 历史",
                len(self._fingerprints), len(self._suppressed), len(self._anomalies),
            )
        except Exception as e:
            logger.warning("加载异常检测状态失败（忽略，使用空状态）: %s", e)

    async def _save_state_async(self) -> None:
        """P1-5: 异步原子写入状态到磁盘"""
        if not self._state_file:
            self._dirty = False
            return
        try:
            # 取 Top N 指纹（按 count 降序），避免无界增长
            sorted_fps = sorted(
                self._fingerprints.values(), key=lambda f: f.count, reverse=True
            )[:_MAX_PERSISTED_FINGERPRINTS]
            # 只保留最近的 N 个异常事件
            recent_anomalies = self._anomalies[-_MAX_PERSISTED_ANOMALIES:]
            data = {
                "fingerprints": [fp.to_dict() for fp in sorted_fps],
                "suppressed": dict(self._suppressed),
                "anomalies": [a.to_dict() for a in recent_anomalies],
                "last_check_ts": self._last_check_ts,
                "saved_at": time.time(),
            }

            def _write_atomic():
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = str(self._state_file) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp_path, self._state_file)

            await asyncio.to_thread(_write_atomic)
            self._dirty = False
            self._last_persist_ts = time.time()
        except Exception as e:
            logger.warning("保存异常检测状态失败: %s", e)

    def on_error(self, error_id: str, error_report: Dict[str, Any]) -> None:
        error_type = str(error_report.get("error_type", "UnknownError"))
        if error_type in _IGNORED_ERROR_TYPES:
            return

        now = time.time()
        self._errors.append((now, error_report))

        fp = self._compute_fingerprint(error_report)
        if fp.fingerprint in self._fingerprints:
            existing = self._fingerprints[fp.fingerprint]
            existing.count += 1
            existing.last_seen = now
            if not existing.sample_traceback and fp.sample_traceback:
                existing.sample_traceback = fp.sample_traceback
        else:
            fp.first_seen = now
            fp.last_seen = now
            fp.count = 1
            self._fingerprints[fp.fingerprint] = fp
        # P1-5: 标记脏数据，等待下次 flush_state_async 落盘
        self._dirty = True

    def check_anomalies(self) -> List[AnomalyEvent]:
        now = time.time()
        new_anomalies: List[AnomalyEvent] = []

        for rule in self._rules:
            if self._is_suppressed(rule.name, now):
                continue

            anomaly = self._evaluate_rule(rule, now)
            if anomaly is not None:
                self._suppressed[rule.name] = now
                new_anomalies.append(anomaly)

        self._anomalies.extend(new_anomalies)
        if len(self._anomalies) > 500:
            self._anomalies = self._anomalies[-500:]

        self._last_check_ts = now
        # P1-5: 状态变更（新异常或新抑制）标记脏，等待 flush
        if new_anomalies:
            self._dirty = True
        return new_anomalies

    async def flush_state_async(self, force: bool = False) -> None:
        """P1-5: 周期性调用，将脏状态落盘

        - force=True：立即写入（用于 shutdown 等场景）
        - force=False：至少间隔 _PERSIST_INTERVAL_SECONDS 才写入
        """
        if not force:
            if not self._dirty:
                return
            if (time.time() - self._last_persist_ts) < _PERSIST_INTERVAL_SECONDS:
                return
        await self._save_state_async()

    def get_active_anomalies(self, limit: int = 50) -> List[AnomalyEvent]:
        return self._anomalies[-limit:]

    def get_error_stats(self) -> Dict[str, Any]:
        now = time.time()
        recent_1h = sum(1 for ts, _ in self._errors if (now - ts) < 3600)
        recent_5m = sum(1 for ts, _ in self._errors if (now - ts) < 300)
        top_errors = sorted(
            self._fingerprints.values(), key=lambda f: f.count, reverse=True
        )[:10]
        return {
            "total_errors_tracked": len(self._errors),
            "errors_last_1h": recent_1h,
            "errors_last_5m": recent_5m,
            "unique_fingerprints": len(self._fingerprints),
            "top_errors": [
                {
                    "fingerprint": fp.fingerprint[:16],
                    "error_type": fp.error_type,
                    "file_path": fp.file_path,
                    "count": fp.count,
                    "last_seen_ago": round(now - fp.last_seen, 1),
                }
                for fp in top_errors
            ],
            "total_anomalies": len(self._anomalies),
            "suppressed_rules": list(self._suppressed.keys()),
        }

    def _evaluate_rule(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        if rule.anomaly_type == AnomalyType.ERROR_BURST:
            return self._check_error_burst(rule, now)
        elif rule.anomaly_type == AnomalyType.REPEATED_EXCEPTION:
            return self._check_repeated_exception(rule, now)
        elif rule.anomaly_type == AnomalyType.BUSINESS_METRIC_ANOMALY:
            return self._check_business_metric(rule, now)
        elif rule.anomaly_type == AnomalyType.ERROR_CLUSTER:
            return self._check_error_cluster(rule, now)
        elif rule.anomaly_type == AnomalyType.SERVICE_DEGRADATION:
            return self._check_service_degradation(rule, now)
        return None

    def _check_error_burst(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        window = rule.window_seconds
        threshold = rule.threshold
        count = sum(1 for ts, _ in self._errors if (now - ts) < window)
        if count >= threshold:
            return AnomalyEvent(
                anomaly_type=rule.anomaly_type,
                severity=rule.severity,
                title=f"错误暴增: {count}次/{window}秒",
                description=f"在{window}秒内检测到{count}次错误，超过阈值{threshold}",
                metric_name=rule.metric_name,
                metric_value=float(count),
                metric_threshold=threshold,
                auto_fixable=rule.auto_fix,
                metadata={"window_seconds": window, "error_count": count},
            )
        return None

    def _check_repeated_exception(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        window = rule.window_seconds
        threshold = int(rule.threshold)
        for fp_key, fp in self._fingerprints.items():
            if (now - fp.last_seen) > window:
                continue
            if fp.count >= threshold and fp.file_path:
                return AnomalyEvent(
                    anomaly_type=rule.anomaly_type,
                    severity=rule.severity,
                    title=f"重复错误: {fp.error_type} in {fp.file_path}:{fp.line_number}",
                    description=(
                        f"错误 {fp.error_type} 在 {fp.file_path}:{fp.line_number} "
                        f"出现{fp.count}次（{window}秒内），阈值{threshold}"
                    ),
                    fingerprint=fp,
                    metric_name=rule.metric_name,
                    metric_value=float(fp.count),
                    metric_threshold=threshold,
                    auto_fixable=rule.auto_fix,
                    metadata={
                        "error_type": fp.error_type,
                        "file_path": fp.file_path,
                        "line_number": fp.line_number,
                        "count": fp.count,
                    },
                )
        return None

    def _check_business_metric(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        metric_value = self._collect_business_metric(rule.metric_name, now)
        if metric_value >= rule.threshold:
            return AnomalyEvent(
                anomaly_type=rule.anomaly_type,
                severity=rule.severity,
                title=f"业务指标异常: {rule.metric_name}={metric_value}",
                description=rule.description,
                metric_name=rule.metric_name,
                metric_value=metric_value,
                metric_threshold=rule.threshold,
                auto_fixable=rule.auto_fix,
                metadata={"rule_name": rule.name},
            )
        return None

    def _check_error_cluster(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        window = rule.window_seconds
        threshold = int(rule.threshold)
        error_type_counts: Dict[str, int] = {}
        for ts, report in self._errors:
            if (now - ts) < window:
                et = str(report.get("error_type", "Unknown"))
                error_type_counts[et] = error_type_counts.get(et, 0) + 1

        for et, count in error_type_counts.items():
            if count >= threshold:
                matching_fp = None
                for fp in self._fingerprints.values():
                    if fp.error_type == et and fp.file_path:
                        matching_fp = fp
                        break
                return AnomalyEvent(
                    anomaly_type=rule.anomaly_type,
                    severity=rule.severity,
                    title=f"错误聚集: {et} x{count}",
                    description=f"错误类型 {et} 在{window}秒内出现{count}次",
                    fingerprint=matching_fp,
                    metric_name=rule.metric_name,
                    metric_value=float(count),
                    metric_threshold=threshold,
                    auto_fixable=rule.auto_fix,
                    metadata={"error_type": et, "count": count},
                )
        return None

    def _check_service_degradation(
        self, rule: AnomalyRule, now: float
    ) -> Optional[AnomalyEvent]:
        try:
            from core.async_monitor import get_health_checker

            checker = get_health_checker()
            results = checker.check_all_services_sync()
            unhealthy = [
                name
                for name, status in results.items()
                if str(status.get("status", "")) in {"unhealthy", "error"}
            ]
            if len(unhealthy) >= int(rule.threshold):
                return AnomalyEvent(
                    anomaly_type=rule.anomaly_type,
                    severity=rule.severity,
                    title=f"服务降级: {', '.join(unhealthy)}",
                    description=f"{len(unhealthy)}个服务不健康: {', '.join(unhealthy)}",
                    metric_name=rule.metric_name,
                    metric_value=float(len(unhealthy)),
                    metric_threshold=rule.threshold,
                    auto_fixable=rule.auto_fix,
                    metadata={"unhealthy_services": unhealthy},
                )
        except Exception:
            pass
        return None

    def _collect_business_metric(self, metric_name: str, now: float) -> float:
        if metric_name == "active_care_messages_today":
            return self._count_active_care_messages_today()
        return 0.0

    def _count_active_care_messages_today(self) -> float:
        try:
            from core.services.active_care.storage.storage import get_active_care_storage

            storage = get_active_care_storage()
            stats = storage.get_stats()
            return float(stats.get("messages_sent_today", 0))
        except Exception:
            pass

        try:

            today_str = now_str("%Y-%m-%d")
            from core.services.active_care.storage.storage import ActiveCareStorage

            storage = ActiveCareStorage()
            data = storage._load()
            today_data = data.get(today_str, {})
            return float(len(today_data.get("messages", [])))
        except Exception:
            return 0.0

    def _compute_fingerprint(self, error_report: Dict[str, Any]) -> ErrorFingerprint:
        error_type = str(error_report.get("error_type", "UnknownError"))
        error_message = str(error_report.get("error_message", ""))
        traceback_str = str(error_report.get("traceback", ""))

        file_path, line_number, func_name = self._parse_traceback(traceback_str)
        if not file_path:
            file_path = self._extract_file_from_message(error_message)
        if not file_path:
            file_path, line_number, func_name = self._extract_from_source_info(error_report)

        fp_raw = f"{error_type}:{file_path}:{line_number}:{func_name}"
        fp_hash = hashlib.md5(fp_raw.encode()).hexdigest()

        return ErrorFingerprint(
            fingerprint=fp_hash,
            error_type=error_type,
            error_message=error_message[:500],
            file_path=file_path,
            line_number=line_number,
            function_name=func_name,
            sample_traceback=traceback_str[:3000] if traceback_str else "",
            sample_context=error_report.get("context", {}),
        )

    def _parse_traceback(
        self, traceback_str: str
    ) -> Tuple[str, int, str]:
        if not traceback_str:
            return "", 0, ""

        for match in _TRACEBACK_REL_RE.finditer(traceback_str):
            rel_path = match.group(1)
            line_num = int(match.group(2))
            func_match = _TRACEBACK_FILE_RE.search(
                traceback_str[match.start() :]
            )
            func_name = func_match.group(3) if func_match else ""
            return rel_path, line_num, func_name

        for match in _TRACEBACK_FILE_RE.finditer(traceback_str):
            abs_path = match.group(1)
            line_num = int(match.group(2))
            func_name = match.group(3)
            if "core" in abs_path or "config" in abs_path:
                idx = abs_path.find("core")
                if idx >= 0:
                    return abs_path[idx:], line_num, func_name
                idx = abs_path.find("config")
                if idx >= 0:
                    return abs_path[idx:], line_num, func_name
            return abs_path, line_num, func_name

        return "", 0, ""

    def _extract_file_from_message(self, message: str) -> str:
        file_hint = re.search(r'(core[/\\][\w./\\]+\.py)', message)
        if file_hint:
            return file_hint.group(1).replace("\\", "/")
        return ""

    def _extract_from_source_info(
        self, error_report: Dict[str, Any]
    ) -> Tuple[str, int, str]:
        source_file = str(error_report.get("source_file", ""))
        source_line = int(error_report.get("source_line", 0))
        source_func = str(error_report.get("source_func", ""))
        if not source_file:
            return "", 0, ""
        for keyword in ("core", "config"):
            idx = source_file.replace("\\", "/").find(f"/{keyword}/")
            if idx >= 0:
                return source_file[idx + 1:].replace("\\", "/"), source_line, source_func
        return source_file.replace("\\", "/"), source_line, source_func

    def _is_suppressed(self, rule_name: str, now: float) -> bool:
        last_suppress = self._suppressed.get(rule_name, 0.0)
        return (now - last_suppress) < self._suppress_duration
