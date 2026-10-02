import asyncio
import threading
import time
from typing import Any, Callable, Dict, Optional

from config.integrated_config import get_settings
from core.services.data_ops.analysis_pipeline import DataOpsAnalysisPipeline
from core.services.data_ops.human_digest_worker import HumanDigestWorker
from core.services.data_ops.memory_compactor import MemoryCompactor
from core.services.data_ops.queue import DataOpsQueue
from core.services.data_ops.summary_worker import DataSummaryWorker
from core.services.data_ops.task_planner_worker import TaskPlannerWorker
from core.utils.logger import get_logger

logger = get_logger("DataOps.SERVICE")


class DataOpsService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        settings = get_settings()
        self._queue = DataOpsQueue()
        self._memory_compactor = MemoryCompactor()
        self._summary_worker = DataSummaryWorker()
        self._task_planner_worker = TaskPlannerWorker()
        self._human_digest_worker = HumanDigestWorker()
        self._analysis = DataOpsAnalysisPipeline(settings=settings)
        self._queue.register_handler(
            "memory_denoise_summary", self._handle_memory_denoise
        )
        self._queue.register_handler("daily_digest", self._handle_daily_digest)
        self._queue.register_handler(
            "weekly_report", self._handle_weekly_report
        )
        self._queue.register_handler("task_plan", self._handle_task_plan)
        self._queue.register_handler(
            "human_daily_digest", self._handle_human_daily_digest
        )
        self._queue.register_handler(
            "human_weekly_report", self._handle_human_weekly_report
        )

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def _submit_to_queue(
        self,
        *,
        task_type: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        payload: Dict[str, Any],
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        if not use_queue:
            return await asyncio.to_thread(handler, payload)
        task = await asyncio.to_thread(
            self._queue.enqueue,
            task_type=task_type,
            payload=payload,
            idempotency_key=idempotency_key,
            max_retries=1,
        )
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "created_at": task.created_at,
        }

    def _handle_memory_denoise(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "default")
        min_weight = float(payload.get("min_weight") or 1.0)
        max_items = int(payload.get("max_items") or 200)
        data = self._memory_compactor.build_denoise_summary(
            user_id=user_id, min_weight=min_weight, max_items=max_items
        )
        return {"status": "success", "data": data, "timestamp": time.time()}

    def _handle_daily_digest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        date = str(payload.get("date") or "").strip()
        include_diary_summary = bool(payload.get("include_diary_summary", True))
        data = self._summary_worker.build_daily_digest(
            date=date,
            include_diary_summary=include_diary_summary,
        )
        return {"status": "success", "data": data, "timestamp": time.time()}

    def _handle_weekly_report(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        anchor_date = str(payload.get("anchor_date") or "").strip()
        data = self._summary_worker.build_weekly_report(anchor_date=anchor_date)
        return {"status": "success", "data": data, "timestamp": time.time()}

    def _handle_task_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        date = str(payload.get("date") or "").strip()
        force = bool(payload.get("force", False))
        data = self._task_planner_worker.plan_daily_tasks(date=date, force=force)
        return {"status": "success", "data": data, "timestamp": time.time()}

    def _handle_human_daily_digest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings = get_settings()
        if not bool(settings.data_ops.human_digest_enabled):
            return {
                "status": "error",
                "message": "human_digest_disabled",
                "timestamp": time.time(),
            }
        date = str(payload.get("date") or "").strip()
        include_device_context = bool(
            payload.get(
                "include_device_context",
                bool(settings.data_ops.human_digest_include_device_context),
            )
        )
        data = self._human_digest_worker.build_human_daily_digest(
            date=date,
            include_device_context=include_device_context,
        )
        return {"status": "success", "data": data, "timestamp": time.time()}

    def _handle_human_weekly_report(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings = get_settings()
        if not bool(settings.data_ops.human_digest_enabled):
            return {
                "status": "error",
                "message": "human_digest_disabled",
                "timestamp": time.time(),
            }
        anchor_date = str(payload.get("anchor_date") or "").strip()
        include_device_context = bool(payload.get("include_device_context", False))
        data = self._human_digest_worker.build_human_weekly_report(
            anchor_date=anchor_date,
            include_device_context=include_device_context,
        )
        return {"status": "success", "data": data, "timestamp": time.time()}

    async def submit_memory_denoise_summary(
        self,
        *,
        user_id: str,
        min_weight: float = 1.0,
        max_items: int = 200,
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="memory_denoise_summary",
            handler=self._handle_memory_denoise,
            payload={
                "user_id": user_id,
                "min_weight": min_weight,
                "max_items": max_items,
            },
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def submit_memory_rule_analysis(
        self,
        *,
        user_id: str,
        use_queue: bool = True,
        idempotency_key: str = "",
        limit: int = 0,
    ) -> Dict[str, Any]:
        return await self._analysis.submit_memory_rule_analysis(
            user_id=user_id,
            use_queue=use_queue,
            idempotency_key=idempotency_key,
            limit=limit,
        )

    async def submit_memory_ai_shadow_analysis(
        self,
        *,
        user_id: str,
        use_queue: bool = True,
        idempotency_key: str = "",
        limit: int = 0,
        timeout_ms: int = 0,
        strategy: str = "",
    ) -> Dict[str, Any]:
        return await self._analysis.submit_memory_ai_shadow_analysis(
            user_id=user_id,
            use_queue=use_queue,
            idempotency_key=idempotency_key,
            limit=limit,
            timeout_ms=timeout_ms,
            strategy=strategy,
        )

    async def submit_memory_fusion_adjudication(
        self,
        *,
        user_id: str,
        use_queue: bool = True,
        idempotency_key: str = "",
        limit: int = 0,
        override_min_confidence: float = 0.0,
        supplement_min_confidence: float = 0.0,
        allow_override: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return await self._analysis.submit_memory_fusion_adjudication(
            user_id=user_id,
            use_queue=use_queue,
            idempotency_key=idempotency_key,
            limit=limit,
            override_min_confidence=override_min_confidence,
            supplement_min_confidence=supplement_min_confidence,
            allow_override=allow_override,
        )

    async def submit_daily_digest(
        self,
        *,
        date: str = "",
        include_diary_summary: bool = True,
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="daily_digest",
            handler=self._handle_daily_digest,
            payload={"date": date, "include_diary_summary": include_diary_summary},
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def submit_weekly_report(
        self,
        *,
        anchor_date: str = "",
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="weekly_report",
            handler=self._handle_weekly_report,
            payload={"anchor_date": anchor_date},
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def submit_task_plan(
        self,
        *,
        date: str = "",
        force: bool = False,
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="task_plan",
            handler=self._handle_task_plan,
            payload={"date": date, "force": force},
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def submit_human_daily_digest(
        self,
        *,
        date: str = "",
        include_device_context: bool = True,
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="human_daily_digest",
            handler=self._handle_human_daily_digest,
            payload={"date": date, "include_device_context": include_device_context},
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def submit_human_weekly_report(
        self,
        *,
        anchor_date: str = "",
        include_device_context: bool = False,
        use_queue: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        return await self._submit_to_queue(
            task_type="human_weekly_report",
            handler=self._handle_human_weekly_report,
            payload={
                "anchor_date": anchor_date,
                "include_device_context": include_device_context,
            },
            use_queue=use_queue,
            idempotency_key=idempotency_key,
        )

    async def run_task(self, task_id: str) -> Dict[str, Any]:
        task = await asyncio.to_thread(self._queue.run_task, task_id)
        if not task:
            return {"status": "error", "message": "task_not_found"}
        return {
            "status": task.status,
            "task_id": task.task_id,
            "result": task.result,
            "error": task.error,
            "updated_at": task.updated_at,
        }

    def get_task(self, task_id: str) -> Dict[str, Any]:
        task = self._queue.get_task(task_id)
        if not task:
            return {"status": "error", "message": "task_not_found"}
        return {
            "status": task.status,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def get_memory_rule_analysis_metrics(self) -> Dict[str, Any]:
        return self._analysis.get_memory_rule_analysis_metrics()

    def get_memory_ai_shadow_metrics(self) -> Dict[str, Any]:
        return self._analysis.get_memory_ai_shadow_metrics()

    def get_memory_fusion_metrics(self) -> Dict[str, Any]:
        return self._analysis.get_memory_fusion_metrics()


def get_data_ops_service() -> DataOpsService:
    return DataOpsService.get_instance()
