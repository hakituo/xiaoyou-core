"""
延迟任务调度器
用于管理基于用户时间预期的延迟跟进任务
"""
import time
import asyncio
import heapq
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from core.utils.logger import get_logger
from core.utils.time_utils import ts_to_iso, ts_to_str
from config.integrated_config import get_settings

logger = get_logger("DELAYED_SCHEDULER")


@dataclass(order=True)
class DelayedTask:
    """延迟任务数据类"""
    trigger_ts: float
    task_id: str = field(compare=False)
    task_type: str = field(compare=False)
    context: Dict[str, Any] = field(compare=False, default_factory=dict)
    created_ts: float = field(compare=False, default_factory=time.time)
    priority: int = field(compare=False, default=0)
    source_message: str = field(compare=False, default="")
    action_hint: str = field(compare=False, default="")


class DelayedTaskScheduler:
    """
    延迟任务调度器
    支持基于时间预期的智能跟进
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._tasks: List[DelayedTask] = []
        self._task_counter = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._wakeup_event = asyncio.Event()
        self._on_task_trigger: Optional[Callable] = None
        self._max_tasks = 50
        
    def set_callback(self, callback: Callable):
        """设置任务触发时的回调函数"""
        self._on_task_trigger = callback
    
    def schedule_task(
        self,
        delay_seconds: float,
        task_type: str,
        context: Dict[str, Any],
        priority: int = 0,
        source_message: str = "",
        action_hint: str = "",
    ) -> str:
        """
        调度一个延迟任务
        
        Args:
            delay_seconds: 延迟秒数
            task_type: 任务类型 (如 "follow_up", "reminder", "check_in")
            context: 任务上下文
            priority: 优先级 (越高越优先)
            source_message: 触发此任务的用户消息
            action_hint: 动作提示 (如 "洗漱", "吃饭")
        
        Returns:
            task_id: 任务ID
        """
        if delay_seconds < 30:
            delay_seconds = 30
        
        self._task_counter += 1
        task_id = f"delayed_{int(time.time())}_{self._task_counter}"
        
        trigger_ts = time.time() + delay_seconds
        
        task = DelayedTask(
            trigger_ts=trigger_ts,
            task_id=task_id,
            task_type=task_type,
            context=context,
            priority=priority,
            source_message=source_message,
            action_hint=action_hint,
        )
        
        heapq.heappush(self._tasks, task)
        
        if len(self._tasks) > self._max_tasks:
            self._prune_old_tasks()
        
        self._wakeup_event.set()
        
        logger.info(
            f"DelayedTaskScheduler: 已调度任务 {task_id}, "
            f"类型={task_type}, 延迟={int(delay_seconds)}秒, "
            f"触发时间={ts_to_str(trigger_ts, '%H:%M:%S')}, "
            f"提示={action_hint}"
        )
        
        return task_id
    
    def schedule_from_proactive_context(
        self,
        proactive_context: Dict[str, Any],
        user_message: str,
    ) -> Optional[str]:
        """
        根据主动关怀上下文自动调度任务
        
        Args:
            proactive_context: analyze_proactive_context 的返回结果
            user_message: 用户消息
        
        Returns:
            task_id 或 None
        """
        if not proactive_context.get("should_follow_up_soon"):
            return None
        
        time_exp = proactive_context.get("time_expectation", {})
        urgency = proactive_context.get("urgency", {})
        topic_interrupt = proactive_context.get("topic_interrupt", {})
        
        delay_seconds = proactive_context.get("suggested_follow_up_seconds", 300)
        
        task_type = "follow_up"
        action_hint = ""
        priority = 0
        
        # 根据不同类型设置任务类型和优先级
        if time_exp.get("has_time_expectation"):
            if time_exp.get("time_type") == "after_action":
                task_type = "action_follow_up"
                action_hint = time_exp.get("action_hint", "")
            else:
                task_type = "time_based_follow_up"
                action_hint = time_exp.get("original_text", "")
        elif urgency.get("urgency") == "HIGH":
            task_type = "urgent_follow_up"
            priority = 10
        elif urgency.get("urgency") == "MEDIUM":
            task_type = "medium_urgency_follow_up"
            priority = 5
        elif topic_interrupt.get("has_interrupt"):
            task_type = "topic_interrupt_follow_up"
            action_hint = topic_interrupt.get("context_hint", "")
            priority = 3
        
        context = {
            "urgency": urgency,
            "time_expectation": time_exp,
            "topic_interrupt": topic_interrupt,
            "original_message": user_message,
        }
        
        return self.schedule_task(
            delay_seconds=delay_seconds,
            task_type=task_type,
            context=context,
            priority=priority,
            source_message=user_message,
            action_hint=action_hint,
        )
    
    def cancel_task(self, task_id: str) -> bool:
        """取消指定任务"""
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id:
                self._tasks.pop(i)
                heapq.heapify(self._tasks)
                logger.info(f"DelayedTaskScheduler: 已取消任务 {task_id}")
                return True
        return False
    
    def cancel_all_tasks(self):
        """取消所有任务"""
        count = len(self._tasks)
        self._tasks = []
        logger.info(f"DelayedTaskScheduler: 已取消所有任务 ({count}个)")
    
    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """获取所有待执行任务"""
        return [
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "trigger_ts": t.trigger_ts,
                "trigger_at": ts_to_iso(t.trigger_ts),
                "remaining_seconds": max(0, int(t.trigger_ts - time.time())),
                "priority": t.priority,
                "action_hint": t.action_hint,
                "source_message": t.source_message[:50] if t.source_message else "",
            }
            for t in sorted(self._tasks)
        ]
    
    def get_next_task_info(self) -> Optional[Dict[str, Any]]:
        """获取下一个待执行任务的信息"""
        if not self._tasks:
            return None
        next_task = self._tasks[0]
        return {
            "task_id": next_task.task_id,
            "task_type": next_task.task_type,
            "remaining_seconds": max(0, int(next_task.trigger_ts - time.time())),
            "action_hint": next_task.action_hint,
        }
    
    def _prune_old_tasks(self):
        """清理过期或过多的任务，只移除已触发超过1小时的旧任务，保留尚未触发的任务"""
        now = time.time()
        valid_tasks = [
            t for t in self._tasks
            if t.trigger_ts > now or (now - t.trigger_ts) < 3600
        ]
        
        if len(valid_tasks) > self._max_tasks:
            valid_tasks = sorted(valid_tasks, key=lambda t: (-t.priority, t.trigger_ts))
            valid_tasks = valid_tasks[:self._max_tasks]
        
        self._tasks = valid_tasks
        heapq.heapify(self._tasks)
    
    async def start(self):
        """启动调度器"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DelayedTaskScheduler: 调度器已启动")
    
    async def stop(self):
        """停止调度器"""
        self._running = False
        self._wakeup_event.set()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("DelayedTaskScheduler: 调度器已停止")
    
    async def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                now = time.time()
                
                ready_tasks = []
                while self._tasks and self._tasks[0].trigger_ts <= now:
                    task = heapq.heappop(self._tasks)
                    ready_tasks.append(task)
                
                for task in ready_tasks:
                    await self._execute_task(task)
                
                if self._tasks:
                    next_task = self._tasks[0]
                    wait_seconds = max(1.0, next_task.trigger_ts - time.time())
                else:
                    wait_seconds = 60.0
                
                try:
                    await asyncio.wait_for(
                        self._wakeup_event.wait(),
                        timeout=wait_seconds
                    )
                except asyncio.TimeoutError:
                    pass
                finally:
                    self._wakeup_event.clear()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DelayedTaskScheduler 循环错误: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _execute_task(self, task: DelayedTask):
        """执行任务"""
        logger.info(
            f"DelayedTaskScheduler: 执行任务 {task.task_id}, "
            f"类型={task.task_type}, 提示={task.action_hint}"
        )
        
        if self._on_task_trigger:
            try:
                await self._on_task_trigger(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    context=task.context,
                    source_message=task.source_message,
                    action_hint=task.action_hint,
                )
            except Exception as e:
                logger.error(f"DelayedTaskScheduler 回调执行失败: {e}", exc_info=True)


_delayed_scheduler: Optional[DelayedTaskScheduler] = None


def get_delayed_scheduler() -> DelayedTaskScheduler:
    """获取延迟任务调度器单例"""
    global _delayed_scheduler
    if _delayed_scheduler is None:
        _delayed_scheduler = DelayedTaskScheduler()
    return _delayed_scheduler
