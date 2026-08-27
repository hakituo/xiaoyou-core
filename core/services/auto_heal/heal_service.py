import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.services.auto_heal.models import (
    AnomalyEvent,
    AnomalySeverity,
    HealReport,
    Patch,
    PatchStatus,
    ReportType,
    RootCauseReport,
)
from core.services.auto_heal.report_generator import ReportGenerator
from core.services.auto_heal.patch_manager import PatchManager
from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("AutoHealService")

_HEAL_HISTORY_FILE = "auto_heal_history.jsonl"
_MAX_HISTORY_ENTRIES = 500

# P0-24: auto_apply 风险限制 —— 即使配置开启 auto_apply，
# 修改以下关键基础设施路径的补丁仍必须人工审批（避免 LLM 修改安全关键代码）
_AUTO_APPLY_BLOCKED_PREFIXES = (
    "routers/",
    "core/services/auto_heal/",
    "core/utils/log_sanitizer",
    "core/utils/logger",
    "core/utils/error_handler",
    "core/utils/atomic_io",
    "core/utils/async_subprocess",
    "core/utils/resource_lock",
    "core/interfaces/websocket/",
    "config/",
    "scripts/doc_records/",
)

# auto_apply 允许的异常严重程度（仅 LOW/MEDIUM 可自动应用，HIGH/CRITICAL 必须人工审批）
_AUTO_APPLY_ALLOWED_SEVERITIES = {
    AnomalySeverity.LOW,
    AnomalySeverity.MEDIUM,
}


class AutoHealService:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._detector = None
        self._analyzer = None
        self._generator = None
        self._sandbox = None
        self._history: List[Dict[str, Any]] = []
        self._history_dirty: bool = False
        self._registered_error_callback = False
        self._check_interval: float = 30.0
        self._auto_apply: bool = False
        self._skip_count: int = 0
        self._started_at: float = 0.0
        self._last_check_ts: float = 0.0
        self._last_anomaly_ts: float = 0.0
        self._registered_health_checker = False
        self._suppress_duration: float = 300.0

        # 初始化子模块
        self._report_generator = ReportGenerator()
        self._patch_manager = PatchManager()

    @property
    def detector(self):
        if self._detector is None:
            from core.services.auto_heal.anomaly_detector import AnomalyDetector
            self._detector = AnomalyDetector(suppress_duration=self._suppress_duration)
        return self._detector

    @property
    def analyzer(self):
        if self._analyzer is None:
            from core.services.auto_heal.root_cause_analyzer import RootCauseAnalyzer
            self._analyzer = RootCauseAnalyzer()
        return self._analyzer

    @property
    def generator(self):
        if self._generator is None:
            from core.services.auto_heal.patch_generator import PatchGenerator
            self._generator = PatchGenerator()
        return self._generator

    @property
    def sandbox(self):
        if self._sandbox is None:
            from core.services.auto_heal.patch_sandbox import PatchSandbox
            self._sandbox = PatchSandbox()
        return self._sandbox

    async def initialize(self):
        if self._running:
            return

        self._running = True
        self._started_at = time.time()

        async def _bg_init():
            _t0 = time.perf_counter()
            try:
                from config.integrated_config import get_settings
                settings = get_settings()
                heal_settings = getattr(settings, "auto_heal", None)
                if heal_settings is not None:
                    self._check_interval = float(
                        getattr(heal_settings, "check_interval", 30.0)
                    )
                    self._auto_apply = bool(
                        getattr(heal_settings, "auto_apply", False)
                    )
                    self._suppress_duration = float(
                        getattr(heal_settings, "suppress_duration", 300.0)
                    )
                    enabled = bool(getattr(heal_settings, "enabled", True))
                    if not enabled:
                        logger.info("自愈服务已禁用")
                        self._running = False
                        return
            except Exception:
                if is_debug_enabled("auto_heal"):
                    logger.info("读取自愈服务配置失败，使用默认值", exc_info=True)

            if not self._registered_error_callback:
                from core.utils.errors.log_sanitizer import register_error_callback
                register_error_callback(self._on_error_report)
                self._registered_error_callback = True

            if not self._registered_health_checker:
                self._register_health_checker()

            await self._load_history()

            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._loop())

            await self._publish_event("auto_heal.service_started")
            logger.info("自愈服务后台初始化完成 (%.3fs)", time.perf_counter() - _t0)

        self._bg_init_task = asyncio.create_task(_bg_init())
        logger.info("自愈服务初始化已调度到后台")

    async def shutdown(self):
        if not self._running:
            return

        self._running = False

        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        if self._registered_error_callback:
            try:
                from core.utils.errors.log_sanitizer import unregister_error_callback
                unregister_error_callback(self._on_error_report)
            except Exception:
                if is_debug_enabled("auto_heal"):
                    logger.info("注销错误回调失败", exc_info=True)
            self._registered_error_callback = False

        await self._save_history()
        await self._publish_event("auto_heal.service_stopped")
        logger.info("自愈服务已关闭")

    def _on_error_report(self, error_id: str, error_report: Dict[str, Any]):
        try:
            self.detector.on_error(error_id, error_report)
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("处理错误报告失败", error_id=error_id, exc_info=True)

    async def _loop(self):
        while self._running:
            try:
                await self._check_and_heal()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自愈循环异常: {e}", exc_info=True)
            await asyncio.sleep(max(5.0, self._check_interval))

    async def _check_and_heal(self):
        anomalies = self.detector.check_anomalies()
        self._last_check_ts = time.time()
        # P1-5: 每次检测后尝试 flush 异常检测器状态（带时间间隔节流）
        await self.detector.flush_state_async()
        if not anomalies:
            return

        self._last_anomaly_ts = time.time()

        for anomaly in anomalies:
            logger.info(
                f"检测到异常: [{anomaly.severity.value}] {anomaly.title}"
            )
            await self._publish_event(
                "auto_heal.anomaly_detected",
                anomaly_id=anomaly.id,
                anomaly_type=anomaly.anomaly_type.value,
                severity=anomaly.severity.value,
                title=anomaly.title,
            )

            if anomaly.severity in (AnomalySeverity.HIGH, AnomalySeverity.CRITICAL):
                await self._process_anomaly(anomaly)
            elif anomaly.auto_fixable:
                await self._process_anomaly(anomaly)
            else:
                logger.info(f"低优先级异常，跳过自动修复: {anomaly.title}")
                self._skip_count += 1

    async def _process_anomaly(
        self, anomaly: AnomalyEvent, persona_context: Optional[str] = None
    ):
        try:
            if not self._patch_manager.check_daily_limit():
                logger.warning("今日补丁数量已达上限，跳过")
                self._record_history(anomaly, "daily_limit_reached")
                return

            root_cause = await self.analyzer.analyze(
                anomaly, persona_context=persona_context
            )
            if root_cause is None:
                logger.info(f"无法定位根因: {anomaly.title}")
                self._record_history(anomaly, "no_root_cause")
                return

            logger.info(
                f"根因定位: {root_cause.file_path}:{root_cause.start_line} "
                f"(置信度: {root_cause.confidence:.2f})"
            )

            if root_cause.confidence < 0.3:
                logger.info(f"置信度过低({root_cause.confidence:.2f})，跳过修复")
                self._record_history(anomaly, "low_confidence", root_cause)
                return

            if not root_cause.file_path:
                logger.info("无文件路径，无法生成补丁")
                self._record_history(anomaly, "no_file_path", root_cause)
                return

            is_protected = self._patch_manager.is_protected_file(root_cause.file_path)

            if is_protected:
                logger.info(
                    f"受保护文件，生成建议报告（不自动修改）: {root_cause.file_path}"
                )
                report = HealReport(
                    report_type=ReportType.SUGGESTION_FOR_PROTECTED,
                    title=f"受保护文件问题建议: {root_cause.file_path}",
                    anomaly_id=anomaly.id,
                    anomaly_title=anomaly.title,
                    anomaly_severity=anomaly.severity.value,
                    file_path=root_cause.file_path,
                    is_protected=True,
                    root_cause_analysis=root_cause.analysis,
                    confidence=root_cause.confidence,
                    suggested_fix=root_cause.suggested_fix,
                    related_files=root_cause.related_files,
                    conclusion=(
                        f"文件 `{root_cause.file_path}` 是受保护的核心文件，"
                        f"自愈服务不会自动修改。请根据上述分析手动修复。"
                    ),
                )
                await self._report_generator.save_report(report)
                self._record_history(anomaly, "protected_file_suggestion", root_cause)
                return

            if not self._patch_manager.check_file_limit(root_cause.file_path):
                logger.warning(
                    f"文件今日补丁数已达上限: {root_cause.file_path}"
                )
                self._record_history(anomaly, "file_limit_reached", root_cause)
                return

            patch = await self.generator.generate(
                root_cause, persona_context=persona_context
            )
            if patch is None:
                logger.info("补丁生成失败")
                self._record_history(anomaly, "patch_generation_failed", root_cause)
                return

            if len(patch.patched_code.encode("utf-8")) > 512 * 1024:
                logger.warning(
                    f"补丁体积超限({len(patch.patched_code)}字节)，跳过"
                )
                self._record_history(anomaly, "patch_too_large", root_cause)
                return

            patch.status = PatchStatus.VERIFYING
            self._patch_manager.register_patch(patch)

            verification = await self.sandbox.verify(patch)
            patch.verification_result = verification
            patch.verified = bool(verification.get("overall_ok", False))

            if not patch.verified:
                logger.warning(
                    f"补丁验证未通过: {verification.get('errors', [])}"
                )
                patch.status = PatchStatus.FAILED
                # P1-5: 状态变更后持久化（FAILED 状态需落盘）
                await self._patch_manager._save_state_async()
                self._record_history(
                    anomaly, "verification_failed", root_cause, patch
                )
                return

            patch.status = PatchStatus.AWAITING_APPROVAL
            # P1-5: 待审批状态持久化（关键：重启后必须保留待审批补丁）
            await self._patch_manager._save_state_async()
            logger.info(f"补丁已生成并验证通过，等待审批: {patch.id}")

            report = HealReport(
                report_type=ReportType.PATCH_GENERATED,
                title=f"补丁待审批: {patch.file_path}",
                anomaly_id=anomaly.id,
                anomaly_title=anomaly.title,
                anomaly_severity=anomaly.severity.value,
                file_path=patch.file_path,
                is_protected=False,
                root_cause_analysis=root_cause.analysis,
                confidence=root_cause.confidence,
                suggested_fix=root_cause.suggested_fix,
                patch_id=patch.id,
                patch_status=patch.status.value,
                diff_summary=patch.diff[:3000],
                related_files=root_cause.related_files,
                conclusion="补丁已通过语法和 import 验证，等待人工审批。",
            )
            await self._report_generator.save_report(report)

            if self._auto_apply and self._can_auto_apply(anomaly, patch):
                logger.info(
                    f"auto_apply 已启用且补丁属低风险，自动应用: {patch.id} "
                    f"(severity={anomaly.severity.value}, file={patch.file_path})"
                )
                await self.apply_patch(patch.id)
            else:
                if self._auto_apply:
                    logger.warning(
                        f"auto_apply 已启用但补丁被风险限制阻止，改为人工审批: "
                        f"{patch.id} (severity={anomaly.severity.value}, "
                        f"file={patch.file_path})"
                    )
                await self._notify_patch_ready(patch)

        except Exception as e:
            logger.error(f"处理异常失败: {e}", exc_info=True)
            self._record_history(anomaly, "processing_error", error=str(e))

    async def apply_patch(self, patch_id: str) -> Dict[str, Any]:
        """应用补丁（委托给 PatchManager）"""
        result = await self._patch_manager.apply_patch(patch_id)
        
        if result.get("success"):
            patch = self._patch_manager.patches.get(patch_id)
            if patch:
                self._record_history(
                    patch.root_cause.anomaly if patch.root_cause else None,
                    "patch_applied",
                    patch.root_cause,
                    patch,
                )

                report = HealReport(
                    report_type=ReportType.PATCH_APPLIED,
                    title=f"补丁已应用: {patch.file_path}",
                    anomaly_id=patch.anomaly_id,
                    anomaly_title=(
                        patch.root_cause.anomaly.title if patch.root_cause else ""
                    ),
                    anomaly_severity=(
                        patch.root_cause.anomaly.severity.value
                        if patch.root_cause
                        else ""
                    ),
                    file_path=patch.file_path,
                    root_cause_analysis=(
                        patch.root_cause.analysis if patch.root_cause else ""
                    ),
                    confidence=patch.root_cause.confidence if patch.root_cause else 0.0,
                    suggested_fix=patch.description,
                    patch_id=patch.id,
                    patch_status=patch.status.value,
                    diff_summary=patch.diff[:3000],
                    conclusion=f"补丁已成功应用到 `{patch.file_path}`，备份已保存。",
                )
                await self._report_generator.save_report(report)
                await self._publish_event(
                    "auto_heal.patch_applied",
                    patch_id=patch.id,
                    file_path=patch.file_path,
                )
                # 通知自我改进系统记录学习
                try:
                    from core.services.self_improvement.service import get_self_improvement_service
                    from core.services.self_improvement.models import EntryArea, EntryPriority
                    si = get_self_improvement_service(scope="user")
                    await si.log_error(
                        priority=EntryPriority.HIGH,
                        area=EntryArea.INFRA,
                        summary=f"自愈补丁已应用: {patch.file_path}",
                        error_message=patch.description[:200] if patch.description else "",
                        context=f"异常: {patch.anomaly_id}",
                        suggested_fix=patch.diff[:200] if patch.diff else "",
                        related_files=[patch.file_path] if patch.file_path else [],
                    )
                except Exception as exc:
                    logger.warning("自愈补丁记录到自我改进系统失败: %s", exc)
        
        return result

    async def rollback_patch(self, patch_id: str) -> Dict[str, Any]:
        """回滚补丁（委托给 PatchManager）"""
        result = await self._patch_manager.rollback_patch(patch_id)
        
        if result.get("success"):
            patch = self._patch_manager.patches.get(patch_id)
            if patch:
                self._record_history(
                    patch.root_cause.anomaly if patch.root_cause else None,
                    "patch_rolled_back",
                    patch.root_cause,
                    patch,
                )
                await self._publish_event(
                    "auto_heal.patch_rolled_back",
                    patch_id=patch.id,
                    file_path=patch.file_path,
                )
        
        return result

    async def reject_patch(self, patch_id: str) -> Dict[str, Any]:
        """拒绝补丁（委托给 PatchManager）"""
        result = await self._patch_manager.reject_patch(patch_id)
        
        if result.get("success"):
            patch = self._patch_manager.patches.get(patch_id)
            if patch:
                self._record_history(
                    patch.root_cause.anomaly if patch.root_cause else None,
                    "patch_rejected",
                    patch.root_cause,
                    patch,
                )
        
        return result

    def get_pending_patches(self) -> List[Dict[str, Any]]:
        """获取待审批补丁（委托给 PatchManager）"""
        return self._patch_manager.get_pending_patches()

    def get_all_patches(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有补丁（委托给 PatchManager）"""
        return self._patch_manager.get_all_patches(limit)

    def get_patch_detail(self, patch_id: str) -> Optional[Dict[str, Any]]:
        """获取补丁详情（委托给 PatchManager）"""
        return self._patch_manager.get_patch_detail(patch_id)

    def get_stats(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        error_stats = self.detector.get_error_stats()
        patches_by_status: Dict[str, int] = {}
        for patch in self._patch_manager.patches.values():
            key = patch.status.value
            patches_by_status[key] = patches_by_status.get(key, 0) + 1

        return {
            "running": self._running,
            "uptime_seconds": round(time.time() - self._started_at, 0) if self._started_at else 0,
            "heal_count": self._patch_manager.heal_count,
            "skip_count": self._skip_count,
            "daily_patch_count": self._patch_manager.daily_patch_count,
            "daily_patch_limit": 10,
            "patches_total": len(self._patch_manager.patches),
            "patches_by_status": patches_by_status,
            "pending_patches_count": patches_by_status.get("awaiting_approval", 0),
            "error_stats": error_stats,
            "auto_apply": self._auto_apply,
            "check_interval": self._check_interval,
            "protected_files_count": 14,
            "last_check_ts": self._last_check_ts,
            "last_anomaly_ts": self._last_anomaly_ts,
            "reports_count": len(self._report_generator.reports),
        }

    async def trigger_check(
        self, persona_context: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """触发检查"""
        anomalies = self.detector.check_anomalies()
        results = []
        for anomaly in anomalies:
            await self._process_anomaly(anomaly, persona_context=persona_context)
            results.append(
                {
                    "anomaly_id": anomaly.id,
                    "type": anomaly.anomaly_type.value,
                    "severity": anomaly.severity.value,
                    "title": anomaly.title,
                    "auto_fixable": anomaly.auto_fixable,
                }
            )
        return results

    def _can_auto_apply(self, anomaly: AnomalyEvent, patch: Patch) -> bool:
        """
        P0-24: 判断补丁是否可以自动应用

        三层风险限制（任意一层不通过都改为人工审批）：
        1. 异常严重程度必须为 LOW 或 MEDIUM（HIGH/CRITICAL 影响范围大，必须人工确认）
        2. 补丁目标文件不能在 _AUTO_APPLY_BLOCKED_PREFIXES 黑名单内（关键基础设施）
        3. 补丁目标文件不能是 PatchManager 已声明的受保护文件
        """
        # 1. 严重程度检查
        if anomaly.severity not in _AUTO_APPLY_ALLOWED_SEVERITIES:
            return False

        # 2. 文件路径黑名单检查
        normalized = (patch.file_path or "").replace("\\", "/")
        for prefix in _AUTO_APPLY_BLOCKED_PREFIXES:
            if normalized.startswith(prefix) or f"/{prefix}" in normalized:
                return False

        # 3. 受保护文件检查（复用 PatchManager 的 _PROTECTED_FILES 列表）
        if self._patch_manager.is_protected_file(patch.file_path):
            return False

        return True

    async def _notify_patch_ready(self, patch: Patch):
        """通知补丁就绪"""
        await self._publish_event(
            "auto_heal.patch_ready",
            patch_id=patch.id,
            file_path=patch.file_path,
            description=patch.description,
        )

        try:
            from core.services.workspace.service import get_workspace_service

            ws = get_workspace_service()
            await ws._append_workspace_memory(
                content=f"自愈补丁待审批: {patch.file_path} - {patch.description[:100]}",
                category="auto_heal",
                topics=["auto_heal", "patch"],
                metadata={
                    "patch_id": patch.id,
                    "file_path": patch.file_path,
                    "status": patch.status.value,
                },
            )
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("通知补丁就绪(workspace memory)失败", exc_info=True)

    def _record_history(
        self,
        anomaly: Optional[AnomalyEvent],
        action: str,
        root_cause: Optional[RootCauseReport] = None,
        patch: Optional[Patch] = None,
        error: Optional[str] = None,
    ):
        """记录历史"""
        entry = {
            "timestamp": time.time(),
            "action": action,
            "error": error,
        }
        if anomaly:
            entry["anomaly_id"] = anomaly.id
            entry["anomaly_type"] = anomaly.anomaly_type.value
            entry["anomaly_title"] = anomaly.title
            entry["severity"] = anomaly.severity.value
        if root_cause:
            entry["file_path"] = root_cause.file_path
            entry["confidence"] = root_cause.confidence
        if patch:
            entry["patch_id"] = patch.id
            entry["patch_status"] = patch.status.value

        self._history.append(entry)
        if len(self._history) > _MAX_HISTORY_ENTRIES:
            self._history = self._history[-_MAX_HISTORY_ENTRIES:]
        self._history_dirty = True

    async def _load_history(self):
        """加载历史记录"""
        try:
            from core.utils.common import get_project_root

            history_path = Path(get_project_root()) / "logs" / _HEAL_HISTORY_FILE
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("获取项目根目录失败(加载历史)", exc_info=True)
            return

        if not history_path.exists():
            return

        try:

            def _read():
                entries = []
                with open(history_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except Exception:
                                if is_debug_enabled("auto_heal"):
                                    logger.info("解析历史记录行失败", line=line[:100], exc_info=True)
                                continue
                return entries

            self._history = await asyncio.to_thread(_read)
        except Exception:
            logger.warning("加载自愈历史记录失败", exc_info=True)
            self._history = []

    async def _save_history(self):
        """保存历史记录"""
        if not getattr(self, "_history_dirty", False):
            return
        try:
            from core.utils.common import get_project_root

            history_path = Path(get_project_root()) / "logs" / _HEAL_HISTORY_FILE
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("获取项目根目录失败(保存历史)", exc_info=True)
            return

        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)

            def _write():
                with open(history_path, "w", encoding="utf-8") as f:
                    for entry in self._history[-_MAX_HISTORY_ENTRIES:]:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            await asyncio.to_thread(_write)
            self._history_dirty = False
        except Exception as e:
            logger.warning(f"保存自愈历史失败: {e}")

    async def _publish_event(self, event_name: str, **kwargs):
        """发布事件"""
        try:
            from core.core_engine.event_bus import get_event_bus

            bus = get_event_bus()
            await bus.publish(event_name, **kwargs)
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("发布事件到event_bus失败", event_name=event_name, exc_info=True)

        try:
            from core.interfaces.websocket.websocket_manager import (
                get_websocket_manager,
            )

            ws_mgr = get_websocket_manager()
            payload = {
                "type": "auto_heal",
                "event": event_name,
                **kwargs,
            }
            await ws_mgr.broadcast(payload)
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("广播事件到WebSocket失败", event_name=event_name, exc_info=True)

    def _register_health_checker(self):
        """注册健康检查"""
        try:
            from core.async_monitor import get_health_checker

            checker = get_health_checker()

            def _health_check() -> Dict[str, Any]:
                stats = self.get_stats()
                return {
                    "status": "healthy" if self._running else "stopped",
                    "running": self._running,
                    "heal_count": stats["heal_count"],
                    "daily_patches": stats["daily_patch_count"],
                    "pending_patches": stats["pending_patches_count"],
                    "errors_last_5m": stats["error_stats"].get("errors_last_5m", 0),
                }

            checker.register_health_checker(
                "auto_heal_service", _health_check, interval=30.0
            )
            self._registered_health_checker = True
        except Exception:
            if is_debug_enabled("auto_heal"):
                logger.info("注册健康检查器失败", exc_info=True)

    def get_morning_brief(self) -> str:
        """生成早晨报告（委托给 ReportGenerator）"""
        stats = self.get_stats()
        return self._report_generator.get_morning_brief(stats)

    def get_kanban(self) -> Dict[str, Any]:
        """生成看板数据（委托给 ReportGenerator）"""
        stats = self.get_stats()
        return self._report_generator.get_kanban(
            list(self._patch_manager.patches.values()), stats
        )

    def get_reports(self, limit: int = 20, report_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取报告列表（委托给 ReportGenerator）"""
        return self._report_generator.get_reports(limit, report_type)

    def get_report_detail(self, report_id: str) -> Optional[str]:
        """获取报告详情（委托给 ReportGenerator）"""
        return self._report_generator.get_report_detail(report_id)


_auto_heal_instance: Optional[AutoHealService] = None
_auto_heal_lock = threading.Lock()


def get_auto_heal_service() -> AutoHealService:
    global _auto_heal_instance
    with _auto_heal_lock:
        if _auto_heal_instance is None:
            _auto_heal_instance = AutoHealService()
    return _auto_heal_instance


async def initialize_auto_heal():
    await get_auto_heal_service().initialize()


async def shutdown_auto_heal():
    global _auto_heal_instance
    with _auto_heal_lock:
        if _auto_heal_instance is not None:
            await _auto_heal_instance.shutdown()
            _auto_heal_instance = None
