"""Nightly 异步桥接与 scope/global 阶段编排门面。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from core.services.scheduler.task.task_scheduler import get_global_scheduler
from core.utils.logger import get_module_logger

from .distillation_service import MemoryDistillationService
from .global_tasks import NightlyGlobalTaskService

logger = get_module_logger(__name__, "nightly_processor.log")

AsyncTasksExecutor = Callable[[str, Any], Awaitable[Dict[str, Any]]]
DistillExecutor = Callable[[str, Any], Awaitable[int]]


class NightlyTaskRunner:
    """薄门面：只负责事件循环桥接和 nightly 阶段路由。"""

    NIGHTLY_TASK_TIMEOUT_SECONDS: int = 1800

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    def _distillation_service(self) -> MemoryDistillationService:
        """按当前配置创建无状态蒸馏服务。"""
        return MemoryDistillationService(self.config, get_global_scheduler)

    def run_nightly_async_tasks(
        self,
        user_id: str,
        manager: Any,
        execute_async_tasks: AsyncTasksExecutor,
    ) -> Dict[str, Any]:
        """把夜间协程调度到主事件循环执行。"""
        try:
            main_loop = None
            try:
                from core.lifecycle.lifespan import get_main_loop

                main_loop = get_main_loop()
            except Exception as exc:
                logger.warning("获取主事件循环失败: %s", exc)

            if main_loop is not None and main_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    execute_async_tasks(user_id, manager),
                    main_loop,
                )
                return future.result(timeout=self.NIGHTLY_TASK_TIMEOUT_SECONDS)

            logger.warning("未获取到运行中的主事件循环，回退到新建 event loop")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(execute_async_tasks(user_id, manager))
            finally:
                loop.close()
        except concurrent.futures.TimeoutError as exc:
            try:
                future.cancel()
            except Exception as cancel_exc:
                logger.warning("取消超时 nightly 协程失败: %s", cancel_exc)
            logger.error(
                f"运行夜间异步任务超时（{self.NIGHTLY_TASK_TIMEOUT_SECONDS}s）: "
                f"user_id={user_id}, exc_type={type(exc).__name__}, exc={exc}",
                exc_info=True,
            )
            return {"_nightly_error": f"timeout:{self.NIGHTLY_TASK_TIMEOUT_SECONDS}s"}
        except Exception as exc:
            logger.error(
                f"运行夜间异步任务失败: user_id={user_id}, "
                f"exc_type={type(exc).__name__}, exc={exc}",
                exc_info=True,
            )
            return {"_nightly_error": f"{type(exc).__name__}: {exc}"}

    async def execute_async_tasks(
        self,
        user_id: str,
        manager: Any,
        distill_memories_async: DistillExecutor,
        *,
        include_scope: bool = True,
        include_global: bool = True,
        target_date: Optional[datetime.date] = None,
        memory_managers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """兼容入口：按参数依次执行 scope 和 global 阶段。"""
        results: Dict[str, Any] = {}
        if include_scope:
            results.update(
                await self._execute_scope_phase(
                    user_id,
                    manager,
                    distill_memories_async,
                )
            )
        if not include_global:
            return results

        effective_managers = memory_managers
        if effective_managers is None and manager is not None:
            effective_managers = {user_id: manager}
        results.update(
            await NightlyGlobalTaskService().run(
                target_date,
                effective_managers,
            )
        )
        return results

    async def _execute_scope_phase(
        self,
        user_id: str,
        manager: Any,
        distill_memories_async: DistillExecutor,
    ) -> Dict[str, Any]:
        """执行单个记忆 scope 的蒸馏阶段。"""
        results: Dict[str, Any] = {}
        if self.config.get("distillation_enabled", True):
            try:
                results["distilled_count"] = await distill_memories_async(
                    user_id,
                    manager,
                )
            except Exception as exc:
                logger.error("记忆蒸馏失败: %s", exc)
                results["distilled_count"] = 0
        else:
            results["distilled_count"] = 0
            results["distillation"] = "disabled"
        results["people_profiles"] = "deferred_to_global_gate"
        return results

    async def execute_scope_tasks(
        self,
        user_id: str,
        manager: Any,
        distill_memories_async: DistillExecutor,
    ) -> Dict[str, Any]:
        """只执行属于单个记忆 scope 的夜间任务。"""
        return await self.execute_async_tasks(
            user_id,
            manager,
            distill_memories_async,
            include_scope=True,
            include_global=False,
        )

    async def execute_global_tasks(
        self,
        target_date: datetime.date,
        memory_managers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """只执行每个目标日期一次的全局任务。"""
        return await NightlyGlobalTaskService().run(target_date, memory_managers)

    async def distill_memories_async(self, user_id: str, manager: Any) -> int:
        """兼容门面：委托专用蒸馏服务。"""
        return await self._distillation_service().distill_memories_async(
            user_id,
            manager,
        )

    async def _distill_one_async(
        self,
        scheduler: Any,
        manager: Any,
        message: Dict[str, Any],
        distillation_model: Optional[str],
    ) -> bool:
        """兼容门面：委托单条蒸馏回退。"""
        return await self._distillation_service().distill_one_async(
            scheduler,
            manager,
            message,
            distillation_model,
        )

    group_memories_by_time = staticmethod(
        MemoryDistillationService.group_memories_by_time
    )
    generate_distillation_prompt = staticmethod(
        MemoryDistillationService.generate_distillation_prompt
    )
    generate_batch_distillation_prompt = staticmethod(
        MemoryDistillationService.generate_batch_distillation_prompt
    )
    parse_batch_distillation_response = staticmethod(
        MemoryDistillationService.parse_batch_distillation_response
    )
    empty_profile_signals = staticmethod(
        MemoryDistillationService.empty_profile_signals
    )
    parse_profile_signals = staticmethod(
        MemoryDistillationService.parse_profile_signals
    )
    parse_batch_profile_signals = staticmethod(
        MemoryDistillationService.parse_batch_profile_signals
    )
    detect_profile_signals_locally = staticmethod(
        MemoryDistillationService.detect_profile_signals_locally
    )
    parse_distillation_response = staticmethod(
        MemoryDistillationService.parse_distillation_response
    )
