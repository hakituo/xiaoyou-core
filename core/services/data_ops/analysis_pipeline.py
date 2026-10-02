import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from config.integrated_config import get_settings
from core.services.data_ops.bert_analyzer import get_bert_analyzer
from core.utils.logger import get_logger
from memory.weighted_memory_manager import get_weighted_memory_manager

logger = get_logger("DataOps.ANALYSIS")


@dataclass
class _WorkerGroupConfig:
    name: str
    enabled: bool
    worker_count: int
    queue_max: int
    batch_size: int
    extra_stats: Dict[str, Any] = field(default_factory=dict)


class _WorkerGroup:
    """通用异步Worker组，封装队列、去重、启动、循环等公共逻辑"""

    def __init__(self, config: _WorkerGroupConfig):
        self._config = config
        self._queue: Optional[asyncio.Queue[str]] = None
        self._worker_tasks: List[asyncio.Task] = []
        self._workers_started = False
        self._shutdown_event: Optional[asyncio.Event] = None
        self._scheduled_users: Set[str] = set()
        base_stats: Dict[str, Any] = {
            "scheduled": 0,
            "deduplicated": 0,
            "dropped": 0,
            "processed_tasks": 0,
            "processed_memories": 0,
            "failed_tasks": 0,
            "last_error": "",
            "last_latency_ms": 0.0,
        }
        base_stats.update(config.extra_stats)
        self._stats: Dict[str, Any] = base_stats

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def queue(self) -> Optional[asyncio.Queue[str]]:
        return self._queue

    @property
    def stats(self) -> Dict[str, Any]:
        return self._stats

    @property
    def scheduled_users(self) -> Set[str]:
        return self._scheduled_users

    def queue_fill_ratio(self) -> float:
        if self._queue is None or self._config.queue_max <= 0:
            return 0.0
        return float(self._queue.qsize()) / float(max(1, self._config.queue_max))

    async def ensure_started(
        self,
        handler: Callable[[str], Awaitable[Dict[str, Any]]],
    ) -> None:
        if not self._config.enabled:
            return
        if self._workers_started:
            return
        self._queue = asyncio.Queue(maxsize=self._config.queue_max)
        self._shutdown_event = asyncio.Event()
        self._worker_tasks = []
        for idx in range(self._config.worker_count):
            worker_name = f"{self._config.name}-{idx}"
            self._worker_tasks.append(
                asyncio.create_task(self._worker_loop(worker_name, handler))
            )
        self._workers_started = True
        logger.info(
            "DataOps %s workers started (count=%s, queue_max=%s, batch=%s)",
            self._config.name,
            str(self._config.worker_count),
            str(self._config.queue_max),
            str(self._config.batch_size),
        )

    async def shutdown(self, timeout: float = 10.0) -> None:
        if not self._workers_started:
            return
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        for task in self._worker_tasks:
            task.cancel()
        if self._worker_tasks:
            await asyncio.wait(self._worker_tasks, timeout=timeout)
        self._workers_started = False
        self._worker_tasks = []
        logger.info("DataOps %s workers shut down", self._config.name)

    async def _worker_loop(
        self,
        worker_name: str,
        handler: Callable[[str], Awaitable[Dict[str, Any]]],
    ) -> None:
        while True:
            if self._shutdown_event is not None and self._shutdown_event.is_set():
                break
            if self._queue is None:
                await asyncio.sleep(0.05)
                continue
            try:
                user_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            t0 = time.time()
            try:
                result = await handler(user_id)
                self._stats["processed_tasks"] += 1
                self._stats["processed_memories"] += int(
                    result.get("processed") or 0
                )
                if "applied" in result:
                    self._stats["applied"] = self._stats.get("applied", 0) + int(
                        result.get("applied") or 0
                    )
                if "rejected" in result:
                    self._stats["rejected"] = self._stats.get("rejected", 0) + int(
                        result.get("rejected") or 0
                    )
                if "rolled_back" in result:
                    self._stats["rolled_back"] = (
                        self._stats.get("rolled_back", 0)
                        + int(result.get("rolled_back") or 0)
                    )
                self._stats["last_latency_ms"] = round(
                    (time.time() - t0) * 1000.0, 2
                )
            except Exception as e:
                self._stats["failed_tasks"] += 1
                self._stats["last_error"] = str(e)
                logger.error(
                    "DataOps %s worker failed (%s, user=%s): %s",
                    self._config.name,
                    worker_name,
                    user_id,
                    str(e),
                )
            finally:
                self._scheduled_users.discard(user_id)
                self._queue.task_done()

    async def enqueue_user(self, user_id: str) -> Dict[str, Any]:
        if user_id in self._scheduled_users:
            self._stats["deduplicated"] += 1
            return {"status": "queued", "message": "deduplicated", "user_id": user_id}
        if self._queue is None:
            return {
                "status": "error",
                "message": f"{self._config.name}_queue_unavailable",
            }
        if self._queue.full():
            self._stats["dropped"] += 1
            return {
                "status": "dropped",
                "message": f"{self._config.name}_queue_full",
                "user_id": user_id,
            }
        self._scheduled_users.add(user_id)
        await self._queue.put(user_id)
        self._stats["scheduled"] += 1
        return {
            "status": "queued",
            "user_id": user_id,
            "queue_size": int(self._queue.qsize()),
        }

    def get_metrics(self, **extra_fields: Any) -> Dict[str, Any]:
        queue_size = 0
        if self._queue is not None:
            queue_size = int(self._queue.qsize())
        result: Dict[str, Any] = {
            "enabled": bool(self._config.enabled),
            "workers_started": bool(self._workers_started),
            "worker_count": int(self._config.worker_count),
            "queue_max": int(self._config.queue_max),
            "queue_size": queue_size,
            "scheduled_user_count": int(len(self._scheduled_users)),
            "stats": dict(self._stats),
        }
        result.update(extra_fields)
        return result


class DataOpsAnalysisPipeline:
    def __init__(self, settings: Optional[Any] = None):
        settings = settings or get_settings()

        self._rule_only_degrade_enabled = bool(
            getattr(settings.data_ops, "rule_only_degrade_enabled", True)
        )
        self._rule_only_degrade_threshold_ratio = max(
            0.1,
            min(
                1.0,
                float(
                    getattr(
                        settings.data_ops,
                        "rule_only_degrade_threshold_ratio",
                        0.8,
                    )
                ),
            ),
        )

        self._rule_batch_size = max(
            1, int(getattr(settings.data_ops, "rule_analysis_batch_size", 32))
        )
        self._rule_group = _WorkerGroup(
            _WorkerGroupConfig(
                name="rule",
                enabled=bool(settings.data_ops.rule_analysis_worker_enabled),
                worker_count=max(
                    1,
                    int(getattr(settings.data_ops, "rule_analysis_worker_count", 2)),
                ),
                queue_max=max(
                    1,
                    int(getattr(settings.data_ops, "rule_analysis_queue_size", 512)),
                ),
                batch_size=self._rule_batch_size,
            )
        )

        self._ai_shadow_timeout_ms = max(
            100, int(getattr(settings.data_ops, "ai_shadow_timeout_ms", 1200))
        )
        self._ai_shadow_strategy = str(
            getattr(settings.data_ops, "ai_shadow_strategy", "auto") or "auto"
        ).strip().lower()
        if self._ai_shadow_strategy not in {"auto", "rule_fallback"}:
            self._ai_shadow_strategy = "auto"
        ai_shadow_batch_size = max(
            1, int(getattr(settings.data_ops, "ai_shadow_batch_size", 8))
        )
        self._ai_shadow_group = _WorkerGroup(
            _WorkerGroupConfig(
                name="ai-shadow",
                enabled=bool(
                    getattr(settings.data_ops, "ai_shadow_worker_enabled", False)
                ),
                worker_count=max(
                    1,
                    int(getattr(settings.data_ops, "ai_shadow_worker_count", 1)),
                ),
                queue_max=max(
                    1,
                    int(getattr(settings.data_ops, "ai_shadow_queue_size", 256)),
                ),
                batch_size=ai_shadow_batch_size,
                extra_stats={
                    "llm_calls": 0,
                    "fallback_calls": 0,
                    "degraded_rule_only": 0,
                },
            )
        )

        self._fusion_override_min_confidence = max(
            0.0,
            min(
                1.0,
                float(
                    getattr(settings.data_ops, "fusion_override_min_confidence", 0.75)
                ),
            ),
        )
        self._fusion_supplement_min_confidence = max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        settings.data_ops, "fusion_supplement_min_confidence", 0.5
                    )
                ),
            ),
        )
        if (
            self._fusion_supplement_min_confidence
            > self._fusion_override_min_confidence
        ):
            self._fusion_supplement_min_confidence = (
                self._fusion_override_min_confidence
            )
        self._fusion_allow_override = bool(
            getattr(settings.data_ops, "fusion_allow_override", False)
        )
        fusion_batch_size = max(
            1, int(getattr(settings.data_ops, "fusion_batch_size", 16))
        )
        self._fusion_group = _WorkerGroup(
            _WorkerGroupConfig(
                name="fusion",
                enabled=bool(
                    getattr(settings.data_ops, "fusion_worker_enabled", False)
                ),
                worker_count=max(
                    1,
                    int(getattr(settings.data_ops, "fusion_worker_count", 1)),
                ),
                queue_max=max(
                    1,
                    int(getattr(settings.data_ops, "fusion_queue_size", 256)),
                ),
                batch_size=fusion_batch_size,
                extra_stats={
                    "applied": 0,
                    "rejected": 0,
                    "rolled_back": 0,
                    "degraded_rule_only": 0,
                },
            )
        )

    async def shutdown(self, timeout: float = 10.0) -> None:
        await self._rule_group.shutdown(timeout)
        await self._ai_shadow_group.shutdown(timeout)
        await self._fusion_group.shutdown(timeout)

    def _should_degrade_to_rule_only(self) -> bool:
        if not self._rule_only_degrade_enabled:
            return False
        return self._rule_group.queue_fill_ratio() >= float(
            self._rule_only_degrade_threshold_ratio
        )

    def _handle_memory_rule_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "default").strip() or "default"
        limit = int(payload.get("limit") or self._rule_batch_size)
        manager = get_weighted_memory_manager(user_id)
        result = manager.process_pending_analysis(limit=limit)
        return {
            "status": "success",
            "user_id": user_id,
            "processed": int(result.get("processed") or 0),
            "pending_before": int(result.get("pending_before") or 0),
            "pending_after": int(result.get("pending_after") or 0),
            "timestamp": time.time(),
        }

    async def _rule_handler(self, user_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._handle_memory_rule_analysis,
            {"user_id": user_id, "limit": self._rule_batch_size},
        )

    async def _ensure_rule_workers_started(self) -> None:
        await self._rule_group.ensure_started(self._rule_handler)

    async def _ai_shadow_handler(self, user_id: str) -> Dict[str, Any]:
        return await self._handle_memory_ai_shadow_analysis_async(
            {
                "user_id": user_id,
                "limit": self._ai_shadow_group._config.batch_size,
                "timeout_ms": self._ai_shadow_timeout_ms,
                "strategy": self._ai_shadow_strategy,
                "chain_fusion": True,
            }
        )

    async def _ensure_ai_shadow_workers_started(self) -> None:
        await self._ai_shadow_group.ensure_started(self._ai_shadow_handler)

    async def _infer_ai_shadow_for_content(
        self,
        *,
        content: str,
        timeout_ms: int,
        strategy: str,
    ) -> Dict[str, Any]:
        analyzer = get_bert_analyzer()

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, analyzer.analyze, content)

            if result.get("reason") == "bert_model_not_loaded":
                self._ai_shadow_group.stats["fallback_calls"] += 1
                return self._rule_fallback(content)

            self._ai_shadow_group.stats["llm_calls"] += 1

            return {
                "topics": result.get("topics", []),
                "category": result.get("category", "uncategorized"),
                "confidence": result.get("confidence", 0.0),
                "weight_delta": result.get("weight_delta", 0.0),
                "reason": result.get("reason", "bert_inference"),
                "source": "bert_local",
                "status": "ok",
            }

        except Exception as e:
            logger.error("BERT analysis failed: %s", e)
            self._ai_shadow_group.stats["fallback_calls"] += 1
            return self._rule_fallback(content)

    def _rule_fallback(self, content: str) -> Dict[str, Any]:
        from memory.core.utils import classify_category, detect_topics

        topics = [str(t).strip() for t in detect_topics(content) if str(t).strip()]
        category = str(classify_category(content) or "uncategorized")
        if category and category != "uncategorized" and category not in topics:
            topics.append(category)
        return {
            "topics": topics[:8],
            "category": category,
            "confidence": 0.35,
            "weight_delta": 0.0,
            "reason": "rule_fallback",
            "source": "rule_fallback",
            "status": "fallback",
        }

    async def _handle_memory_ai_shadow_analysis_async(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "default").strip() or "default"
        limit = max(
            1,
            int(payload.get("limit") or self._ai_shadow_group._config.batch_size),
        )
        timeout_ms = max(
            100,
            int(payload.get("timeout_ms") or self._ai_shadow_timeout_ms),
        )
        strategy = (
            str(payload.get("strategy") or self._ai_shadow_strategy)
            .strip()
            .lower()
        )
        chain_fusion = bool(payload.get("chain_fusion", False))
        if strategy not in {"auto", "rule_fallback"}:
            strategy = "auto"

        manager = get_weighted_memory_manager(user_id)
        pending_items = manager.get_pending_analysis_items(limit=limit)
        if not pending_items:
            return {
                "status": "success",
                "user_id": user_id,
                "processed": 0,
                "timestamp": time.time(),
            }
        processed = 0
        for item in pending_items:
            memory_id = str(item.get("memory_id") or "").strip()
            content = str(item.get("content") or "").strip()
            if not memory_id or not content:
                continue
            t0 = time.time()
            result = await self._infer_ai_shadow_for_content(
                content=content,
                timeout_ms=timeout_ms,
                strategy=strategy,
            )
            ok = manager.attach_ai_shadow_result(
                memory_id=memory_id,
                ai_topics=list(result.get("topics") or []),
                ai_category=str(result.get("category") or "uncategorized"),
                ai_confidence=float(result.get("confidence") or 0.0),
                ai_weight_delta=float(result.get("weight_delta") or 0.0),
                ai_discourse_label=str(result.get("discourse_label") or "GENERIC_CHAT"),
                ai_state_event=str(result.get("state_event") or "NONE"),
                ai_trigger_allowed=bool(result.get("trigger_allowed", False)),
                ai_reason=str(result.get("reason") or ""),
                source=str(result.get("source") or "llm"),
                status=str(result.get("status") or "ok"),
                latency_ms=(time.time() - t0) * 1000.0,
            )
            if ok:
                processed += 1
        chained = False
        if chain_fusion and processed > 0 and self._fusion_group.enabled:
            chained = True
            await self.submit_memory_fusion_adjudication(
                user_id=user_id,
                use_queue=True,
            )
        return {
            "status": "success",
            "user_id": user_id,
            "processed": processed,
            "fusion_chained": chained,
            "timestamp": time.time(),
        }

    def _handle_memory_fusion_adjudication(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "default").strip() or "default"
        limit = max(
            1,
            int(payload.get("limit") or self._fusion_group._config.batch_size),
        )
        override_min = float(
            payload.get("override_min_confidence")
            or self._fusion_override_min_confidence
        )
        supplement_min = float(
            payload.get("supplement_min_confidence")
            or self._fusion_supplement_min_confidence
        )
        allow_override = bool(
            payload.get("allow_override", self._fusion_allow_override)
        )
        manager = get_weighted_memory_manager(user_id)
        result = manager.apply_ai_shadow_adjudication(
            limit=limit,
            override_min_confidence=override_min,
            supplement_min_confidence=supplement_min,
            allow_override=allow_override,
        )
        return {
            "status": "success",
            "user_id": user_id,
            "processed": int(result.get("processed") or 0),
            "applied": int(result.get("applied") or 0),
            "rejected": int(result.get("rejected") or 0),
            "rolled_back": int(result.get("rolled_back") or 0),
            "pending_before": int(result.get("pending_before") or 0),
            "pending_after": int(result.get("pending_after") or 0),
            "timestamp": time.time(),
        }

    async def _fusion_handler(self, user_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._handle_memory_fusion_adjudication,
            {
                "user_id": user_id,
                "limit": self._fusion_group._config.batch_size,
                "override_min_confidence": self._fusion_override_min_confidence,
                "supplement_min_confidence": self._fusion_supplement_min_confidence,
                "allow_override": self._fusion_allow_override,
            },
        )

    async def _ensure_fusion_workers_started(self) -> None:
        await self._fusion_group.ensure_started(self._fusion_handler)

    async def submit_memory_rule_analysis(
        self,
        *,
        user_id: str,
        use_queue: bool = True,
        idempotency_key: str = "",
        limit: int = 0,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": str(user_id or "default").strip() or "default",
            "limit": int(limit or self._rule_batch_size),
            "idempotency_key": str(idempotency_key or "").strip(),
        }
        if not use_queue or not self._rule_group.enabled:
            return await asyncio.to_thread(self._handle_memory_rule_analysis, payload)
        await self._ensure_rule_workers_started()
        return await self._rule_group.enqueue_user(payload["user_id"])

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
        if not self._ai_shadow_group.enabled and use_queue:
            return {"status": "skipped", "message": "ai_shadow_disabled"}
        payload = {
            "user_id": str(user_id or "default").strip() or "default",
            "limit": int(limit or self._ai_shadow_group._config.batch_size),
            "timeout_ms": int(timeout_ms or self._ai_shadow_timeout_ms),
            "strategy": str(strategy or self._ai_shadow_strategy).strip().lower(),
            "idempotency_key": str(idempotency_key or "").strip(),
        }
        if payload["strategy"] not in {"auto", "rule_fallback"}:
            payload["strategy"] = self._ai_shadow_strategy
        if not use_queue:
            payload["chain_fusion"] = False
            return await self._handle_memory_ai_shadow_analysis_async(payload)
        if self._should_degrade_to_rule_only():
            self._ai_shadow_group.stats["degraded_rule_only"] += 1
            return {
                "status": "skipped",
                "message": "degraded_rule_only",
                "user_id": payload["user_id"],
            }
        await self._ensure_ai_shadow_workers_started()
        return await self._ai_shadow_group.enqueue_user(payload["user_id"])

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
        if not self._fusion_group.enabled and use_queue:
            return {"status": "skipped", "message": "fusion_disabled"}
        payload = {
            "user_id": str(user_id or "default").strip() or "default",
            "limit": int(limit or self._fusion_group._config.batch_size),
            "override_min_confidence": float(
                override_min_confidence or self._fusion_override_min_confidence
            ),
            "supplement_min_confidence": float(
                supplement_min_confidence or self._fusion_supplement_min_confidence
            ),
            "allow_override": self._fusion_allow_override
            if allow_override is None
            else bool(allow_override),
            "idempotency_key": str(idempotency_key or "").strip(),
        }
        if not use_queue:
            return await asyncio.to_thread(
                self._handle_memory_fusion_adjudication, payload
            )
        if self._should_degrade_to_rule_only():
            self._fusion_group.stats["degraded_rule_only"] += 1
            return {
                "status": "skipped",
                "message": "degraded_rule_only",
                "user_id": payload["user_id"],
            }
        await self._ensure_fusion_workers_started()
        return await self._fusion_group.enqueue_user(payload["user_id"])

    def get_memory_rule_analysis_metrics(self) -> Dict[str, Any]:
        return self._rule_group.get_metrics()

    def get_memory_ai_shadow_metrics(self) -> Dict[str, Any]:
        return self._ai_shadow_group.get_metrics(
            strategy=str(self._ai_shadow_strategy),
            timeout_ms=int(self._ai_shadow_timeout_ms),
            rule_only_degrade_enabled=bool(self._rule_only_degrade_enabled),
            rule_only_degrade_threshold_ratio=float(
                self._rule_only_degrade_threshold_ratio
            ),
        )

    def get_memory_fusion_metrics(self) -> Dict[str, Any]:
        return self._fusion_group.get_metrics(
            override_min_confidence=float(self._fusion_override_min_confidence),
            supplement_min_confidence=float(self._fusion_supplement_min_confidence),
            allow_override=bool(self._fusion_allow_override),
            rule_only_degrade_enabled=bool(self._rule_only_degrade_enabled),
            rule_only_degrade_threshold_ratio=float(
                self._rule_only_degrade_threshold_ratio
            ),
        )
