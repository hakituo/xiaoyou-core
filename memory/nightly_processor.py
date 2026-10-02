#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜间自动处理门面。

该模块保留既有对外接口，内部职责拆分到 `memory/nightly/` 下的兄弟模块：
- `analysis_service.py` 负责消息分析与结果落盘
- `task_runner.py` 负责异步任务桥接与记忆蒸馏
- `user_loader.py` 负责睡眠状态检测与磁盘用户扫描
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import schedule

from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time, get_diary_target_date

from .nightly import (
    ANALYSIS_DIR as NIGHTLY_ANALYSIS_DIR,
    DEFAULT_NIGHTLY_CONFIG,
    NightlyAnalysisService,
    NightlyRunStateStore,
    NightlyTaskRunner,
    check_user_sleeping,
    filter_real_users,
    get_memory_distillation_model as nightly_get_memory_distillation_model,
    load_users_from_disk,
)
from .weighted_memory_manager import get_weighted_memory_manager

logger = get_module_logger(__name__, "nightly_processor.log")
ANALYSIS_DIR = NIGHTLY_ANALYSIS_DIR


def get_memory_distillation_model() -> Optional[str]:
    """兼容保留的蒸馏模型获取接口。"""
    return nightly_get_memory_distillation_model()


class NightlyProcessor:
    """夜间自动处理组件，对外保留原有接口。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        base_config = DEFAULT_NIGHTLY_CONFIG.copy()
        if config:
            base_config.update(config)

        self.config = base_config
        self._stop_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._last_run_date: Optional[datetime.date] = None
        self._sleep_detected_time: Optional[datetime.datetime] = None
        self._task_executed_today = False
        self._run_state_store = NightlyRunStateStore()

        if self.config["enabled"] and self.config["auto_run"]:
            self._start_scheduler()

    def _get_analysis_service(self) -> NightlyAnalysisService:
        service = getattr(self, "_analysis_service", None)
        if service is None or service.config is not self.config:
            service = NightlyAnalysisService(self.config)
            self._analysis_service = service
        return service

    def _get_task_runner(self) -> NightlyTaskRunner:
        runner = getattr(self, "_task_runner", None)
        if runner is None or runner.config is not self.config:
            runner = NightlyTaskRunner(self.config)
            self._task_runner = runner
        return runner

    def _start_scheduler(self) -> None:
        """启动睡眠感知调度线程。"""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("调度器线程已存在，停止旧线程")
            self._stop_event.set()
            try:
                if (
                    hasattr(self._scheduler_thread, "_started")
                    and self._scheduler_thread._started.is_set()
                ):
                    self._scheduler_thread.join(timeout=3.0)
            except RuntimeError as exc:
                logger.error(f"停止旧调度器线程时出错: {exc}")

        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._sleep_aware_scheduler_loop,
            daemon=True,
            name="nightly-scheduler",
        )
        try:
            self._scheduler_thread.start()
            self._is_running = True
            logger.info("夜间处理调度器已启动（睡眠检测模式）")
        except RuntimeError as exc:
            logger.error(f"启动调度器线程失败: {exc}")
            self._is_running = False

    def _scheduler_loop(self) -> None:
        """兼容保留的旧调度循环。"""
        logger.info("调度器循环已启动")
        try:
            while not self._stop_event.is_set():
                try:
                    schedule.run_pending()
                    if self._stop_event.wait(timeout=60):
                        break
                except Exception as exc:
                    logger.error(f"调度器循环异常: {exc}")
                    if self._stop_event.wait(timeout=60):
                        break
        finally:
            self._is_running = False
            logger.info("调度器循环已停止")

    def _sleep_aware_scheduler_loop(self) -> None:
        """按睡眠状态与兜底时间触发夜间处理。"""
        logger.info("睡眠感知调度器循环已启动")
        check_interval = 600
        sleep_delay_seconds = 3600
        fallback_hour = 5

        try:
            while not self._stop_event.is_set():
                try:
                    now = datetime.datetime.now()
                    today = now.date()
                    if self._last_run_date != today:
                        self._task_executed_today = False
                        self._sleep_detected_time = None
                        self._last_run_date = today

                    if self._task_executed_today:
                        if self._stop_event.wait(timeout=check_interval):
                            break
                        continue

                    is_sleeping = self._check_user_sleeping()
                    sleep_triggered = False
                    if is_sleeping:
                        if self._sleep_detected_time is None:
                            self._sleep_detected_time = now
                            logger.info("检测到用户开始睡觉，将在 1 小时后执行夜间处理")
                        else:
                            elapsed = (now - self._sleep_detected_time).total_seconds()
                            if elapsed >= sleep_delay_seconds:
                                logger.info(f"用户已睡 {elapsed / 60:.0f} 分钟，开始执行夜间处理")
                                self._task_executed_today = self.process_all_users(
                                    trigger_reason="sleep"
                                )
                                sleep_triggered = True
                            else:
                                remaining = sleep_delay_seconds - elapsed
                                logger.debug(f"用户睡觉中，还需等待 {remaining / 60:.0f} 分钟")
                    elif self._sleep_detected_time is not None:
                        logger.info("用户已醒来，重置睡眠检测")
                        self._sleep_detected_time = None

                    if sleep_triggered:
                        if self._stop_event.wait(timeout=check_interval):
                            break
                        continue

                    # Fallback 只在睡眠延迟尚未满足时兜底。若两者同时
                    # 满足，优先保留真实的 sleep 触发来源。
                    if fallback_hour <= now.hour < 12:
                        logger.info(
                            f"到达 Fallback 时间 {fallback_hour}:00，强制执行夜间处理"
                        )
                        self._task_executed_today = self.process_all_users(
                            trigger_reason="fallback"
                        )
                        if self._stop_event.wait(timeout=check_interval):
                            break
                        continue

                    if self._stop_event.wait(timeout=check_interval):
                        break
                except Exception as exc:
                    logger.error(f"睡眠感知调度器循环异常: {exc}")
                    if self._stop_event.wait(timeout=check_interval):
                        break
        finally:
            self._is_running = False
            logger.info("睡眠感知调度器循环已停止")

    def _check_user_sleeping(self) -> bool:
        """兼容保留的睡眠检测接口。"""
        return check_user_sleeping()

    def process_all_users(
        self,
        *,
        trigger_reason: str = "manual",
        target_date: Optional[datetime.date] = None,
    ) -> bool:
        """处理目标日期的所有记忆 scope 与全局夜间任务。"""
        if not self._is_in_time_window():
            logger.info("当前不在配置的时间窗口内，跳过处理")
            return False

        resolved_target = target_date or get_diary_target_date().date()
        if isinstance(resolved_target, datetime.datetime):
            resolved_target = resolved_target.date()
        target_key = resolved_target.isoformat()
        claim = self._run_state_store.begin(target_key, trigger_reason)
        if claim == "completed":
            logger.info("夜间任务已完成，直接跳过: target_date=%s", target_key)
            return True
        if claim == "active":
            logger.info("夜间任务正在执行，跳过并发触发: target_date=%s", target_key)
            return False

        try:
            from memory.weighted_memory_manager import _instances, _instances_lock

            with _instances_lock:
                memory_managers = dict(_instances)

            if not memory_managers:
                logger.info("运行时实例为空，尝试从磁盘扫描已有记忆 scope...")
                memory_managers = self._load_users_from_disk()

            memory_scopes = filter_real_users(memory_managers)
            completed_scopes = self._run_state_store.get_completed_scopes(target_key)
            scope_failures = 0
            logger.info(
                "开始夜间 scope 阶段: target_date=%s scopes=%d resumed=%d",
                target_key,
                len(memory_scopes),
                len(completed_scopes),
            )
            for scope_id, manager in memory_scopes.items():
                if scope_id in completed_scopes:
                    logger.info("跳过已完成 scope: %s", scope_id)
                    continue
                try:
                    result = self.process_user_chat_history(
                        scope_id,
                        manager,
                        target_date=resolved_target,
                    )
                    if result.get("nightly_scope_error"):
                        raise RuntimeError(str(result["nightly_scope_error"]))
                    self._run_state_store.mark_scope_completed(target_key, scope_id)
                except Exception as exc:
                    scope_failures += 1
                    self._run_state_store.mark_scope_failed(
                        target_key, scope_id, str(exc)
                    )
                    logger.error(
                        "处理记忆 scope=%s 时出错: %s", scope_id, exc
                    )

            global_failed = False
            if not self._run_state_store.is_global_completed(target_key):
                try:
                    global_result = self._run_nightly_global_tasks(
                        resolved_target,
                        memory_scopes,
                    )
                    global_error = global_result.get("_nightly_error") or global_result.get(
                        "global_error"
                    )
                    if global_error:
                        raise RuntimeError(str(global_error))
                    self._run_state_store.mark_global_completed(target_key)
                except Exception as exc:
                    global_failed = True
                    self._run_state_store.mark_global_failed(target_key, str(exc))
                    logger.error(
                        "执行全局 nightly 阶段失败: target_date=%s error=%s",
                        target_key,
                        exc,
                    )
            else:
                logger.info("跳过已完成全局 nightly 阶段: %s", target_key)

            all_scopes_completed = set(memory_scopes).issubset(
                self._run_state_store.get_completed_scopes(target_key)
            )
            completed = (
                scope_failures == 0
                and not global_failed
                and all_scopes_completed
                and self._run_state_store.is_global_completed(target_key)
            )
            self._run_state_store.finish(target_key, completed=completed)
            logger.info(
                "夜间处理结束: target_date=%s status=%s scope_failures=%d",
                target_key,
                "completed" if completed else "partial",
                scope_failures,
            )
            return completed
        except Exception as exc:
            logger.error(f"夜间处理过程中发生错误: {exc}")
            try:
                self._run_state_store.finish(target_key, completed=False)
            except Exception:
                self._run_state_store.release(target_key)
            return False

    def _load_users_from_disk(self) -> Dict[str, Any]:
        """兼容保留的用户扫描接口。"""
        return load_users_from_disk()

    def process_user_chat_history(
        self,
        user_id: str,
        manager: Any = None,
        *,
        target_date: Optional[datetime.date] = None,
    ) -> Dict[str, Any]:
        """处理单个记忆 scope 的夜间分析。"""
        if manager is None:
            manager = get_weighted_memory_manager(user_id)
        resolved_target = target_date or get_diary_target_date().date()
        if isinstance(resolved_target, datetime.datetime):
            resolved_target = resolved_target.date()
        return self._get_analysis_service().process_user_chat_history(
            user_id,
            manager,
            target_date=resolved_target,
            run_nightly_async_tasks=self._run_nightly_scope_tasks,
        )

    def _run_nightly_scope_tasks(self, user_id: str, manager: Any) -> Dict[str, Any]:
        """同步桥接单个记忆 scope 的夜间任务。"""
        return self._get_task_runner().run_nightly_async_tasks(
            user_id,
            manager,
            self._execute_scope_tasks,
        )

    def _run_nightly_global_tasks(
        self,
        target_date: datetime.date,
        memory_managers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """同步桥接每个目标日期仅一次的全局任务。"""

        async def execute_global(_user_id: str, _manager: Any) -> Dict[str, Any]:
            return await self._get_task_runner().execute_global_tasks(
                target_date,
                memory_managers=memory_managers,
            )

        return self._get_task_runner().run_nightly_async_tasks(
            f"global:{target_date.isoformat()}",
            None,
            execute_global,
        )

    def _run_nightly_async_tasks(self, user_id: str, manager: Any) -> Dict[str, Any]:
        """同步桥接夜间异步任务。"""
        return self._get_task_runner().run_nightly_async_tasks(
            user_id,
            manager,
            self._execute_async_tasks,
        )

    async def _execute_async_tasks(self, user_id: str, manager: Any) -> Dict[str, Any]:
        """兼容保留：执行 scope 与全局夜间任务。"""
        return await self._get_task_runner().execute_async_tasks(
            user_id,
            manager,
            self._distill_memories_async,
        )

    async def _execute_scope_tasks(self, user_id: str, manager: Any) -> Dict[str, Any]:
        """执行单个记忆 scope 的异步任务。"""
        return await self._get_task_runner().execute_scope_tasks(
            user_id,
            manager,
            self._distill_memories_async,
        )

    async def _distill_memories_async(self, user_id: str, manager: Any) -> int:
        """兼容保留的蒸馏入口。"""
        return await self._get_task_runner().distill_memories_async(user_id, manager)

    def _generate_distillation_prompt(self, content: str) -> str:
        """兼容保留的 Prompt 生成方法。"""
        return self._get_task_runner().generate_distillation_prompt(content)

    def _parse_distillation_response(self, response: str) -> Tuple[str, List[str]]:
        """兼容保留的蒸馏解析方法。"""
        return self._get_task_runner().parse_distillation_response(response)

    def _analyze_message_content(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """兼容保留的消息分析方法。"""
        return self._get_analysis_service().analyze_message_content(messages)

    def _save_analysis_result(self, user_id: str, result: Dict[str, Any]) -> None:
        """兼容保留的分析结果落盘方法。"""
        self._get_analysis_service().save_analysis_result(
            user_id,
            result,
            target_date=get_diary_target_date().date(),
        )

    def _is_in_time_window(self) -> bool:
        """检查当前时间是否在配置的时间窗口内。"""
        current_time = get_current_time().time()
        start_time = datetime.datetime.strptime(self.config["start_time"], "%H:%M").time()
        end_time = datetime.datetime.strptime(self.config["end_time"], "%H:%M").time()
        if start_time <= end_time:
            return start_time <= current_time <= end_time
        return current_time >= start_time or current_time <= end_time

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """更新配置并在必要时重启调度器。"""
        self.config.update(new_config)
        logger.info(f"夜间处理器配置已更新: {new_config}")
        if any(key in new_config for key in ("enabled", "auto_run", "start_time", "end_time")):
            if self.config["enabled"] and self.config["auto_run"]:
                self._start_scheduler()
            else:
                self.stop()

    def stop(self) -> None:
        """停止夜间处理器。"""
        logger.info("正在停止夜间处理器...")
        self._stop_event.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            try:
                self._scheduler_thread.join(timeout=5.0)
                logger.info("调度器线程已停止")
            except Exception as exc:
                logger.error(f"停止调度器线程时出错: {exc}")
        schedule.clear()
        self._is_running = False
        logger.info("夜间处理器已停止")

    def get_status(self) -> Dict[str, Any]:
        """获取处理器状态。"""
        return {
            "enabled": self.config["enabled"],
            "running": self._is_running,
            "next_run_time": self._get_next_run_time(),
            "config": self.config.copy(),
        }

    def _get_next_run_time(self) -> Optional[str]:
        """获取下次运行时间。"""
        try:
            jobs = schedule.get_jobs()
            if jobs:
                next_run = jobs[0].next_run
                return next_run.isoformat() if next_run else None
        except Exception as exc:
            logger.error(f"获取下次运行时间时出错: {exc}")
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="夜间记忆处理工具")
    parser.add_argument("--user", type=str, help="指定处理的用户ID")
    parser.add_argument("--auto", action="store_true", help="启动自动调度模式")
    args = parser.parse_args()

    processor = NightlyProcessor()
    if args.user:
        logger.info(f"开始手动处理用户 {args.user} 的记忆...")
        result = processor.process_user_chat_history(args.user)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.auto:
        logger.info("启动自动调度模式，按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("已停止自动调度")
    else:
        logger.info("未指定参数，默认处理所有用户...")
        processor.process_all_users()
