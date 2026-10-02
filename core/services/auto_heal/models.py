import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.contracts import AnomalySeverity, PatchStatus
from core.utils.time_utils import ts_to_str


class ReportType(str, Enum):
    ANOMALY_DETECTED = "anomaly_detected"
    ROOT_CAUSE_FOUND = "root_cause_found"
    PATCH_GENERATED = "patch_generated"
    PATCH_APPLIED = "patch_applied"
    PATCH_ROLLED_BACK = "patch_rolled_back"
    SUGGESTION_FOR_PROTECTED = "suggestion_for_protected"
    DAILY_SUMMARY = "daily_summary"


class AnomalyType(str, Enum):
    ERROR_CLUSTER = "error_cluster"
    ERROR_BURST = "error_burst"
    BUSINESS_METRIC_ANOMALY = "business_metric_anomaly"
    SERVICE_DEGRADATION = "service_degradation"
    REPEATED_EXCEPTION = "repeated_exception"


@dataclass
class ErrorFingerprint:
    fingerprint: str
    error_type: str
    error_message: str
    file_path: str = ""
    line_number: int = 0
    function_name: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    count: int = 0
    sample_traceback: str = ""
    sample_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # P1-5: 完整序列化，支持 AnomalyDetector 持久化错误指纹（防重启"失忆"）
        return {
            "fingerprint": self.fingerprint,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "function_name": self.function_name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "count": self.count,
            "sample_traceback": self.sample_traceback,
            "sample_context": dict(self.sample_context or {}),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ErrorFingerprint":
        return cls(
            fingerprint=str(d.get("fingerprint", "")),
            error_type=str(d.get("error_type", "")),
            error_message=str(d.get("error_message", "")),
            file_path=str(d.get("file_path", "")),
            line_number=int(d.get("line_number", 0) or 0),
            function_name=str(d.get("function_name", "")),
            first_seen=float(d.get("first_seen", 0) or 0),
            last_seen=float(d.get("last_seen", 0) or 0),
            count=int(d.get("count", 0) or 0),
            sample_traceback=str(d.get("sample_traceback", "")),
            sample_context=dict(d.get("sample_context", {})),
        )


@dataclass
class AnomalyEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    anomaly_type: AnomalyType = AnomalyType.ERROR_CLUSTER
    severity: AnomalySeverity = AnomalySeverity.MEDIUM
    title: str = ""
    description: str = ""
    fingerprint: Optional[ErrorFingerprint] = None
    detected_at: float = field(default_factory=time.time)
    metric_name: str = ""
    metric_value: float = 0.0
    metric_threshold: float = 0.0
    auto_fixable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # P1-5: 完整序列化，支持补丁根因分析持久化
        return {
            "id": self.id,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "detected_at": self.detected_at,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "metric_threshold": self.metric_threshold,
            "auto_fixable": self.auto_fixable,
            "metadata": dict(self.metadata),
        }


@dataclass
class RootCauseReport:
    anomaly: AnomalyEvent
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    function_name: str = ""
    class_name: str = ""
    analysis: str = ""
    confidence: float = 0.0
    source_code: str = ""
    related_files: List[str] = field(default_factory=list)
    suggested_fix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        # P1-5: 完整序列化，支持 PatchManager 持久化补丁的根因分析
        return {
            "anomaly": self.anomaly.to_dict() if hasattr(self.anomaly, "to_dict") else {},
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "function_name": self.function_name,
            "class_name": self.class_name,
            "analysis": self.analysis,
            "confidence": self.confidence,
            "source_code": self.source_code,
            "related_files": list(self.related_files),
            "suggested_fix": self.suggested_fix,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RootCauseReport":
        anomaly_data = d.get("anomaly") or {}
        try:
            anomaly = AnomalyEvent(
                id=str(anomaly_data.get("id", "")),
                anomaly_type=AnomalyType(anomaly_data.get("anomaly_type", "error_cluster")),
                severity=AnomalySeverity(anomaly_data.get("severity", "medium")),
                title=str(anomaly_data.get("title", "")),
                description=str(anomaly_data.get("description", "")),
                detected_at=float(anomaly_data.get("detected_at", 0) or time.time()),
                metric_name=str(anomaly_data.get("metric_name", "")),
                metric_value=float(anomaly_data.get("metric_value", 0) or 0),
                metric_threshold=float(anomaly_data.get("metric_threshold", 0) or 0),
                auto_fixable=bool(anomaly_data.get("auto_fixable", False)),
                metadata=dict(anomaly_data.get("metadata", {})),
            )
        except Exception:
            anomaly = AnomalyEvent(title="(deserialize failed)")
        return cls(
            anomaly=anomaly,
            file_path=str(d.get("file_path", "")),
            start_line=int(d.get("start_line", 0) or 0),
            end_line=int(d.get("end_line", 0) or 0),
            function_name=str(d.get("function_name", "")),
            class_name=str(d.get("class_name", "")),
            analysis=str(d.get("analysis", "")),
            confidence=float(d.get("confidence", 0) or 0),
            source_code=str(d.get("source_code", "")),
            related_files=list(d.get("related_files", [])),
            suggested_fix=str(d.get("suggested_fix", "")),
        )


@dataclass
class Patch:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    anomaly_id: str = ""
    file_path: str = ""
    original_code: str = ""
    patched_code: str = ""
    diff: str = ""
    description: str = ""
    status: PatchStatus = PatchStatus.PENDING
    created_at: float = field(default_factory=time.time)
    applied_at: Optional[float] = None
    verified: bool = False
    verification_result: Dict[str, Any] = field(default_factory=dict)
    root_cause: Optional[RootCauseReport] = None
    rollback_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        # P1-5: 完整序列化（含 original_code/patched_code/rollback_code/root_cause），
        # 用于持久化补丁状态，支持进程重启后回滚与审批
        return {
            "id": self.id,
            "anomaly_id": self.anomaly_id,
            "file_path": self.file_path,
            "original_code": self.original_code,
            "patched_code": self.patched_code,
            "diff": self.diff,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
            "verified": self.verified,
            "verification_result": dict(self.verification_result or {}),
            "root_cause": self.root_cause.to_dict() if self.root_cause else None,
            "rollback_code": self.rollback_code,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Patch":
        try:
            status = PatchStatus(d.get("status", "pending"))
        except Exception:
            status = PatchStatus.PENDING
        root_cause_data = d.get("root_cause")
        root_cause = RootCauseReport.from_dict(root_cause_data) if root_cause_data else None
        try:
            applied_at = float(d["applied_at"]) if d.get("applied_at") is not None else None
        except (TypeError, ValueError):
            applied_at = None
        return cls(
            id=str(d.get("id", "")),
            anomaly_id=str(d.get("anomaly_id", "")),
            file_path=str(d.get("file_path", "")),
            original_code=str(d.get("original_code", "")),
            patched_code=str(d.get("patched_code", "")),
            diff=str(d.get("diff", "")),
            description=str(d.get("description", "")),
            status=status,
            created_at=float(d.get("created_at", 0) or time.time()),
            applied_at=applied_at,
            verified=bool(d.get("verified", False)),
            verification_result=dict(d.get("verification_result", {})),
            root_cause=root_cause,
            rollback_code=str(d.get("rollback_code", "")),
        )


@dataclass
class AnomalyRule:
    name: str
    anomaly_type: AnomalyType
    metric_name: str
    window_seconds: int
    threshold: float
    severity: AnomalySeverity
    auto_fix: bool = False
    description: str = ""


@dataclass
class HealReport:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    report_type: ReportType = ReportType.ANOMALY_DETECTED
    title: str = ""
    created_at: float = field(default_factory=time.time)
    anomaly_id: str = ""
    anomaly_title: str = ""
    anomaly_severity: str = ""
    file_path: str = ""
    is_protected: bool = False
    root_cause_analysis: str = ""
    confidence: float = 0.0
    suggested_fix: str = ""
    patch_id: str = ""
    patch_status: str = ""
    diff_summary: str = ""
    related_files: List[str] = field(default_factory=list)
    conclusion: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:

        ts = ts_to_str(self.created_at, "%Y-%m-%d %H:%M:%S")
        lines = [
            f"# 自愈报告: {self.title}",
            "",
            "| 字段 | 值 |",
            "|------|-----|",
            f"| 报告ID | `{self.id}` |",
            f"| 类型 | {self.report_type.value} |",
            f"| 时间 | {ts} |",
            f"| 异常ID | `{self.anomaly_id}` |",
            f"| 严重程度 | {self.anomaly_severity} |",
            f"| 涉及文件 | `{self.file_path}` |",
            f"| 受保护文件 | {'是（仅建议，不自动修改）' if self.is_protected else '否'} |",
            f"| 置信度 | {self.confidence:.2f} |",
        ]
        if self.patch_id:
            lines.append(f"| 补丁ID | `{self.patch_id}` |")
            lines.append(f"| 补丁状态 | {self.patch_status} |")
        lines.append("")

        if self.root_cause_analysis:
            lines.append("## 根因分析")
            lines.append("")
            lines.append(self.root_cause_analysis)
            lines.append("")

        if self.suggested_fix:
            lines.append("## 修复建议")
            lines.append("")
            lines.append(self.suggested_fix)
            lines.append("")

        if self.diff_summary:
            lines.append("## 变更摘要")
            lines.append("")
            lines.append("```diff")
            lines.append(self.diff_summary[:3000])
            lines.append("```")
            lines.append("")

        if self.related_files:
            lines.append("## 相关文件")
            lines.append("")
            for f in self.related_files:
                lines.append(f"- `{f}`")
            lines.append("")

        if self.conclusion:
            lines.append("## 结论")
            lines.append("")
            lines.append(self.conclusion)
            lines.append("")

        lines.append("---")
        lines.append("")
        return "\n".join(lines)


DEFAULT_ANOMALY_RULES: List[AnomalyRule] = [
    AnomalyRule(
        name="error_burst",
        anomaly_type=AnomalyType.ERROR_BURST,
        metric_name="error_count",
        window_seconds=300,
        threshold=5,
        severity=AnomalySeverity.HIGH,
        auto_fix=True,
        description="5分钟内错误超过5次",
    ),
    AnomalyRule(
        name="repeated_same_error",
        anomaly_type=AnomalyType.REPEATED_EXCEPTION,
        metric_name="same_error_count",
        window_seconds=600,
        threshold=3,
        severity=AnomalySeverity.MEDIUM,
        auto_fix=True,
        description="10分钟内同一错误出现3次以上",
    ),
    AnomalyRule(
        name="active_care_flood",
        anomaly_type=AnomalyType.BUSINESS_METRIC_ANOMALY,
        metric_name="active_care_messages_today",
        window_seconds=86400,
        threshold=50,
        severity=AnomalySeverity.HIGH,
        auto_fix=True,
        description="一天内主动关怀消息超过50条",
    ),
    AnomalyRule(
        name="llm_timeout_cluster",
        anomaly_type=AnomalyType.ERROR_CLUSTER,
        metric_name="llm_timeout_count",
        window_seconds=600,
        threshold=3,
        severity=AnomalySeverity.MEDIUM,
        auto_fix=True,
        description="10分钟内LLM超时3次以上",
    ),
    AnomalyRule(
        name="service_unhealthy",
        anomaly_type=AnomalyType.SERVICE_DEGRADATION,
        metric_name="unhealthy_service_count",
        window_seconds=60,
        threshold=1,
        severity=AnomalySeverity.HIGH,
        auto_fix=False,
        description="有服务处于不健康状态",
    ),
]
