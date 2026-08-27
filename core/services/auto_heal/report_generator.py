import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.services.auto_heal.models import (
    HealReport,
    Patch,
    ReportType,
)
from core.utils.logger import get_logger
from core.utils.time_utils import ts_to_str

logger = get_logger("ReportGenerator")

_REPORT_DIR = "auto_heal_reports"


class ReportGenerator:
    """报告生成器，负责生成、保存和管理自愈报告"""

    def __init__(self):
        self._reports: List[HealReport] = []

    @property
    def reports(self) -> List[HealReport]:
        return self._reports

    async def save_report(self, report: HealReport) -> None:
        """保存报告到内存和文件"""
        self._reports.append(report)
        if len(self._reports) > 200:
            self._reports = self._reports[-200:]

        try:
            from core.utils.common import get_project_root

            report_dir = Path(get_project_root()) / "logs" / _REPORT_DIR
        except Exception:
            return

        try:
            report_dir.mkdir(parents=True, exist_ok=True)

            ts = ts_to_str(report.created_at, "%Y%m%d_%H%M%S")
            filename = f"{ts}_{report.report_type.value}_{report.id}.md"
            report_path = report_dir / filename

            md_content = report.to_markdown()

            def _write():
                report_path.write_text(md_content, encoding="utf-8")

            await asyncio.to_thread(_write)
            logger.info(f"报告已保存: {filename}")
        except Exception as e:
            logger.warning(f"保存报告失败: {e}")

        await self._update_updates_md(report)
        await self._update_ai_debug_questions(report)
        await self._write_heal_diary(report)

    def get_reports(self, limit: int = 20, report_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取报告列表"""
        reports = self._reports
        if report_type:
            reports = [r for r in reports if r.report_type.value == report_type]
        reports = sorted(reports, key=lambda r: r.created_at, reverse=True)
        return [
            {
                "id": r.id,
                "type": r.report_type.value,
                "title": r.title,
                "created_at": r.created_at,
                "file_path": r.file_path,
                "is_protected": r.is_protected,
                "confidence": r.confidence,
                "patch_id": r.patch_id,
                "patch_status": r.patch_status,
                "conclusion": r.conclusion,
            }
            for r in reports[:limit]
        ]

    def get_report_detail(self, report_id: str) -> Optional[str]:
        """获取报告详情（Markdown格式）"""
        for r in self._reports:
            if r.id == report_id:
                return r.to_markdown()
        return None

    def get_morning_brief(self, stats: Dict[str, Any]) -> str:
        """生成早晨报告"""
        patches_by_status = stats.get("patches_by_status", {})
        error_stats = stats.get("error_stats", {})

        applied = patches_by_status.get("applied", 0)
        pending = patches_by_status.get("awaiting_approval", 0)
        failed = patches_by_status.get("failed", 0)
        rolled_back = patches_by_status.get("rolled_back", 0)
        suggestions = patches_by_status.get("suggestion_only", 0)
        errors_1h = error_stats.get("errors_last_1h", 0)
        top_errors = error_stats.get("top_errors", [])[:3]

        if applied == 0 and pending == 0 and failed == 0 and errors_1h == 0:
            return ""

        lines = ["【夜间自愈报告】"]
        if applied > 0:
            lines.append(f"✅ 自动修复了 {applied} 个 bug")
        if pending > 0:
            lines.append(f"⏳ 有 {pending} 个补丁等你审批")
        if failed > 0:
            lines.append(f"❌ {failed} 个补丁验证未通过")
        if rolled_back > 0:
            lines.append(f"↩️ {rolled_back} 个补丁已回滚")
        if suggestions > 0:
            lines.append(f"💡 {suggestions} 条受保护文件建议")

        if top_errors:
            lines.append("主要错误:")
            for err in top_errors:
                lines.append(f"  - {err.get('error_type', '?')} in {err.get('file_path', '?')} (×{err.get('count', 0)})")

        if errors_1h > 0:
            lines.append(f"最近1小时错误: {errors_1h} 条")

        return "\n".join(lines)

    def get_kanban(self, patches: List[Patch], stats: Dict[str, Any]) -> Dict[str, Any]:
        """生成看板数据"""
        error_stats = stats.get("error_stats", {})

        columns = {
            "detected": [],
            "analyzing": [],
            "awaiting_approval": [],
            "applied": [],
            "failed": [],
            "rolled_back": [],
        }

        for patch in patches:
            status_key = patch.status.value
            if status_key in columns:
                columns[status_key].append({
                    "id": patch.id,
                    "file_path": patch.file_path,
                    "description": patch.description[:100],
                    "created_at": patch.created_at,
                    "verified": patch.verified,
                })
            elif status_key == "awaiting_approval":
                columns["awaiting_approval"].append({
                    "id": patch.id,
                    "file_path": patch.file_path,
                    "description": patch.description[:100],
                    "created_at": patch.created_at,
                    "verified": patch.verified,
                })

        protected_suggestions = [
            {
                "id": r.id,
                "file_path": r.file_path,
                "analysis": r.root_cause_analysis[:200],
                "confidence": r.confidence,
                "created_at": r.created_at,
            }
            for r in self._reports
            if r.report_type == ReportType.SUGGESTION_FOR_PROTECTED
        ]

        return {
            "columns": columns,
            "protected_suggestions": protected_suggestions,
            "error_stats": error_stats,
            "daily_patch_count": stats.get("daily_patch_count", 0),
            "daily_patch_limit": stats.get("daily_patch_limit", 10),
            "heal_count": stats.get("heal_count", 0),
            "running": stats.get("running", False),
        }

    async def _update_updates_md(self, report: HealReport) -> None:
        """更新 UPDATES.md 文件"""
        try:
            from core.utils.common import get_project_root

            updates_path = Path(get_project_root()) / "UPDATES.md"
        except Exception:
            return

        try:
            ts = ts_to_str(report.created_at, "%Y-%m-%d %H:%M")

            if report.report_type == ReportType.SUGGESTION_FOR_PROTECTED:
                entry = (
                    f"- **🔍 自愈建议（受保护文件）**: `{report.file_path}` — "
                    f"{report.root_cause_analysis[:100]}（置信度: {report.confidence:.2f}）\n"
                )
            elif report.report_type == ReportType.PATCH_APPLIED:
                entry = (
                    f"- **🔧 自愈补丁已应用**: `{report.file_path}` — "
                    f"{report.suggested_fix[:100]}（补丁ID: `{report.patch_id}`）\n"
                )
            elif report.report_type == ReportType.PATCH_GENERATED:
                entry = (
                    f"- **📋 自愈补丁待审批**: `{report.file_path}` — "
                    f"{report.root_cause_analysis[:100]}（置信度: {report.confidence:.2f}）\n"
                )
            else:
                entry = (
                    f"- **🤖 自愈报告**: `{report.file_path}` — {report.title}\n"
                )

            def _prepend():
                if not updates_path.exists():
                    return
                content = updates_path.read_text(encoding="utf-8")
                date_header = f"## {ts[:10]}"
                if date_header in content:
                    content = content.replace(
                        date_header, date_header + "\n" + entry, 1
                    )
                else:
                    content = date_header + "\n" + entry + "\n" + content
                updates_path.write_text(content, encoding="utf-8")

            await asyncio.to_thread(_prepend)
        except Exception as e:
            logger.warning(f"更新 UPDATES.md 失败: {e}")

    async def _update_ai_debug_questions(self, report: HealReport) -> None:
        """将自愈发现的问题记录到 AI_DEBUG_QUESTIONS.md"""
        if report.report_type not in (
            ReportType.PATCH_APPLIED,
            ReportType.PATCH_GENERATED,
            ReportType.SUGGESTION_FOR_PROTECTED,
        ):
            return

        try:
            from core.utils.common import get_project_root

            debug_path = Path(get_project_root()) / "AI_DEBUG_QUESTIONS.md"
        except Exception:
            return

        try:
            ts = ts_to_str(report.created_at, "%Y-%m-%d %H:%M")
            date_str = ts_to_str(report.created_at, "%Y-%m-%d")

            if report.report_type == ReportType.SUGGESTION_FOR_PROTECTED:
                section = (
                    f"\n## [{date_str}] 受保护文件问题 - {report.file_path}\n\n"
                    f"**发现时间**: {ts}\n\n"
                    f"**问题描述**: `{report.file_path}` 存在潜在问题，该文件受保护无法自动修改\n\n"
                    f"**复现步骤**: 自愈服务通过日志异常检测自动发现\n"
                    f"- 异常类型: {report.anomaly_type}\n"
                    f"- 异常描述: {report.anomaly_description}\n\n"
                    f"**预期行为**: 修复后该异常不再出现\n\n"
                    f"**实际行为**: 异常被检测到并记录，等待人工修复\n\n"
                    f"**根因分析**: \n{report.root_cause_analysis}\n\n"
                    f"**修复建议**: \n{report.suggested_fix}\n\n"
                    f"**置信度**: {report.confidence:.2f}\n\n"
                    f"**状态**: 🔒 待人工处理\n\n"
                    f"---\n"
                )
            elif report.report_type == ReportType.PATCH_GENERATED:
                section = (
                    f"\n## [{date_str}] 补丁待审批 - {report.file_path}\n\n"
                    f"**发现时间**: {ts}\n\n"
                    f"**问题描述**: `{report.file_path}` 存在 bug，补丁已生成待审批\n\n"
                    f"**复现步骤**: 自愈服务通过日志异常检测自动发现\n"
                    f"- 异常类型: {report.anomaly_type}\n"
                    f"- 异常描述: {report.anomaly_description}\n\n"
                    f"**预期行为**: 修复后该异常不再出现\n\n"
                    f"**实际行为**: 补丁已生成，等待审批（补丁ID: `{report.patch_id}`）\n\n"
                    f"**根因分析**: \n{report.root_cause_analysis}\n\n"
                    f"**修复方案**: \n{report.suggested_fix}\n\n"
                    f"**置信度**: {report.confidence:.2f}\n\n"
                    f"**状态**: ⏳ 待审批\n\n"
                    f"---\n"
                )
            else:
                section = (
                    f"\n## [{date_str}] 已修复 - {report.file_path}\n\n"
                    f"**修复时间**: {ts}\n\n"
                    f"**问题描述**: `{report.file_path}` 存在 bug\n\n"
                    f"**复现步骤**: 自愈服务通过日志异常检测自动发现\n"
                    f"- 异常类型: {report.anomaly_type}\n"
                    f"- 异常描述: {report.anomaly_description}\n\n"
                    f"**预期行为**: 修复后该异常不再出现\n\n"
                    f"**实际行为**: 补丁已自动应用（补丁ID: `{report.patch_id}`）\n\n"
                    f"**根因分析**: \n{report.root_cause_analysis}\n\n"
                    f"**修复方案**: \n{report.suggested_fix}\n\n"
                    f"**置信度**: {report.confidence:.2f}\n\n"
                    f"**状态**: ✅ 已自动修复\n\n"
                    f"---\n"
                )

            def _append():
                with open(debug_path, "a", encoding="utf-8") as f:
                    f.write(section)

            await asyncio.to_thread(_append)
            logger.info(f"已记录到 AI_DEBUG_QUESTIONS.md: {report.file_path}")
        except Exception as e:
            logger.warning(f"更新 AI_DEBUG_QUESTIONS.md 失败: {e}")

    async def _write_heal_diary(self, report: HealReport) -> None:
        """写入自愈日记"""
        if report.report_type not in (
            ReportType.PATCH_APPLIED,
            ReportType.SUGGESTION_FOR_PROTECTED,
            ReportType.PATCH_GENERATED,
        ):
            return

        try:
            from core.services.journal.service import get_journal_service

            journal = get_journal_service()

            if report.report_type == ReportType.PATCH_APPLIED:
                content = (
                    f"自愈系统修复了 `{report.file_path}` 中的 bug。"
                    f"根因: {report.root_cause_analysis[:200]}"
                )
                mood = "neutral"
                tags = ["auto_heal", "bug_fix", report.file_path.replace("/", "_")]
            elif report.report_type == ReportType.SUGGESTION_FOR_PROTECTED:
                content = (
                    f"自愈系统发现受保护文件 `{report.file_path}` 存在问题: "
                    f"{report.root_cause_analysis[:200]}。"
                    f"建议: {report.suggested_fix[:200]}"
                )
                mood = "concerned"
                tags = ["auto_heal", "suggestion", report.file_path.replace("/", "_")]
            else:
                content = (
                    f"自愈系统生成了 `{report.file_path}` 的修复补丁，等待审批。"
                    f"根因: {report.root_cause_analysis[:200]}"
                )
                mood = "neutral"
                tags = ["auto_heal", "patch_pending", report.file_path.replace("/", "_")]

            await journal.write_entry(
                content=content,
                mood=mood,
                thought=report.conclusion[:300] if report.conclusion else None,
                type="event",
                source="auto_heal",
                tags=tags,
            )
        except Exception as e:
            logger.warning(f"写入自愈日记失败: {e}")
