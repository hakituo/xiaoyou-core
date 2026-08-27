import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List

from config.integrated_config import get_settings
from core.services.data_ops.summary_worker import _normalize_date
from core.services.data_ops.summary_worker import DataSummaryWorker
from core.utils.data_paths import get_user_data_dir, get_user_latest_device_context_file


class HumanDigestWorker:
    def __init__(self):
        self._summary_worker = DataSummaryWorker()
        self._project_root = Path(get_user_data_dir().parent)
        self._daily_base_dir = get_user_data_dir()

    def _hash_payload(self, payload: Any) -> str:
        try:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            data = str(payload)
        return f"sha1:{hashlib.sha1(data.encode('utf-8')).hexdigest()}"

    def _read_latest_device_context(self) -> Dict[str, Any]:
        latest_file = get_user_latest_device_context_file()
        if not latest_file.exists() or not latest_file.is_file():
            return {}
        try:
            return json.loads(latest_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_daily_sections(
        self,
        date_key: str,
        daily_data: Dict[str, Any],
        include_device_context: bool,
    ) -> Dict[str, Any]:
        study_digest = daily_data.get("study_digest") or {}
        daily_record = daily_data.get("daily_record") or {}
        task_stats = daily_data.get("task_stats") or {}
        task_focus = daily_data.get("task_focus") or {}
        diary_summary = daily_data.get("diary_summary") or {}
        mood_obj = daily_record.get("mood") or {}
        mood_text = ""
        if isinstance(mood_obj, dict):
            mood_text = str(mood_obj.get("mood") or "").strip()
        elif isinstance(mood_obj, str):
            mood_text = mood_obj.strip()

        completed_total = int(task_stats.get("completed_total") or 0)
        timed_total = int(task_stats.get("timed_total") or 0)
        untimed_total = int(task_stats.get("untimed_total") or 0)
        task_total = timed_total + untimed_total
        study_minutes = int(study_digest.get("total_minutes") or 0)
        study_sessions = int(study_digest.get("total_sessions") or 0)
        focus_subject = str(task_focus.get("subject") or "").strip()

        rhythm_line = f"{date_key} 的节奏数据已归档。"
        if mood_text:
            rhythm_line += f" 当前心情记录为「{mood_text}」。"
        if study_minutes > 0:
            rhythm_line += f" 学习时长约 {study_minutes} 分钟。"
        if study_sessions > 0:
            rhythm_line += f" 学习会话 {study_sessions} 次。"

        task_line = f"任务总数 {task_total}，已完成 {completed_total}。"
        if focus_subject:
            task_line += f" 当前重点科目为「{focus_subject}」。"
        if isinstance(study_digest, dict) and study_digest.get("top_subjects"):
            subjects = study_digest.get("top_subjects") or []
            top_names = [str(x.get("subject") or "").strip() for x in subjects[:3]]
            top_names = [x for x in top_names if x]
            if top_names:
                task_line += f" 主要学习方向：{'、'.join(top_names)}。"

        state_line = "状态与提醒数据已同步。"
        if isinstance(diary_summary, dict):
            summary_text = str(diary_summary.get("summary") or "").strip()
            if summary_text:
                state_line += f" 日记总结：{summary_text[:120]}"

        latest_device_context: Dict[str, Any] = {}
        if include_device_context:
            latest_device_context = self._read_latest_device_context()
            battery = latest_device_context.get("battery_level")
            step_count = latest_device_context.get("step_count")
            if battery is not None:
                state_line += f" 设备电量 {battery}% 。"
            if step_count is not None:
                state_line += f" 今日步数 {step_count}。"

        highlights: List[str] = []
        if study_minutes > 0:
            highlights.append(f"学习投入 {study_minutes} 分钟")
        if completed_total > 0:
            highlights.append(f"完成任务 {completed_total} 项")
        if mood_text:
            highlights.append(f"记录了心情状态：{mood_text}")
        if not highlights:
            highlights.append("已完成当日基础数据归档")

        risks: List[str] = []
        if task_total > 0 and completed_total * 2 < task_total:
            risks.append("任务完成率偏低，可能影响次日压力")
        if study_minutes == 0 and study_sessions == 0:
            risks.append("学习数据为空，可能存在漏记")
        if not mood_text:
            risks.append("缺少心情记录，主动关怀判断信息不足")

        next_actions: List[str] = []
        if study_minutes == 0:
            next_actions.append("补录今日学习内容或确认休息日标记")
        if task_total > 0 and completed_total < task_total:
            next_actions.append("优先清理未完成任务中的高优先级项")
        if not mood_text:
            next_actions.append("补充心情与状态记录，提升关怀决策质量")
        if not next_actions:
            next_actions.append("维持当前节奏并在晚间做一次短复盘")

        sections = [
            {"title": "今日节奏", "content": rhythm_line},
            {"title": "学习与任务", "content": task_line},
            {"title": "状态与提醒", "content": state_line},
        ]

        return {
            "sections": sections,
            "highlights": highlights[:5],
            "risks": risks[:5],
            "next_actions": next_actions[:5],
            "latest_device_context": (
                latest_device_context if include_device_context else {}
            ),
        }

    def build_human_daily_digest(
        self, *, date: str = "", include_device_context: bool = True
    ) -> Dict[str, Any]:
        settings = get_settings()
        date_key = _normalize_date(date)
        daily_data = self._summary_worker.build_daily_digest(
            date=date_key, include_diary_summary=False
        )
        built = self._build_daily_sections(
            date_key=date_key,
            daily_data=daily_data,
            include_device_context=include_device_context,
        )
        return {
            "date": date_key,
            "version": str(settings.data_ops.human_digest_version),
            "source_version": {
                "taxonomy": str(settings.data_ops.taxonomy_version),
                "memory_compactor": "mc_v1",
                "summary_worker": "sw_v1",
            },
            "input_digest": {
                "daily_record_hash": self._hash_payload(
                    daily_data.get("daily_record") or {}
                ),
                "study_digest_hash": self._hash_payload(
                    daily_data.get("study_digest") or {}
                ),
                "task_panel_hash": self._hash_payload(
                    {
                        "task_focus": daily_data.get("task_focus") or {},
                        "task_stats": daily_data.get("task_stats") or {},
                    }
                ),
            },
            "sections": built["sections"],
            "highlights": built["highlights"],
            "risks": built["risks"],
            "next_actions": built["next_actions"],
        }

    def build_human_weekly_report(
        self, *, anchor_date: str = "", include_device_context: bool = False
    ) -> Dict[str, Any]:
        settings = get_settings()
        weekly = self._summary_worker.build_weekly_report(anchor_date=anchor_date)
        metrics = weekly.get("metrics") or {}
        top_subjects = weekly.get("top_subjects") or []
        summary = (
            f"近 7 天学习会话 {int(metrics.get('study_sessions') or 0)} 次，"
            f"完成任务 {int(metrics.get('tasks_completed') or 0)} 项，"
            f"未完成任务 {int(metrics.get('tasks_pending') or 0)} 项。"
        )
        top_names = [str(x.get("subject") or "").strip() for x in top_subjects[:5]]
        top_names = [x for x in top_names if x]
        if top_names:
            summary += f" 高频主题：{'、'.join(top_names)}。"
        risks: List[str] = []
        if int(metrics.get("tasks_pending") or 0) > int(
            metrics.get("tasks_completed") or 0
        ):
            risks.append("待办堆积高于完成量，建议下周收缩目标")
        if int(metrics.get("study_sessions") or 0) == 0:
            risks.append("学习会话为零，建议检查记录链路")
        next_actions: List[str] = []
        if risks:
            next_actions.append("下周先清理高优任务，再补充学习节奏")
        else:
            next_actions.append("保持当前节奏，周中增加一次阶段复盘")
        return {
            "range": weekly.get("range") or {},
            "version": str(settings.data_ops.human_digest_version),
            "source_version": {
                "taxonomy": str(settings.data_ops.taxonomy_version),
                "summary_worker": "sw_v1",
            },
            "input_digest": {
                "weekly_report_hash": self._hash_payload(weekly),
            },
            "sections": [
                {"title": "周总结", "content": summary},
            ],
            "highlights": [
                f"学习会话 {int(metrics.get('study_sessions') or 0)} 次",
                f"任务完成 {int(metrics.get('tasks_completed') or 0)} 项",
            ],
            "risks": risks[:5],
            "next_actions": next_actions[:5],
            "include_device_context": bool(include_device_context),
        }
