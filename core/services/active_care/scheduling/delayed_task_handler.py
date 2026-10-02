"""Active Care 延迟任务处理器
负责延迟任务触发回调、动作解析
"""
import time
from typing import Any, Dict

from core.utils.logger import get_module_logger
from core.utils.client_utils import probe_client_type
from core.utils.config_accessor import get_active_care_config

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")


class DelayedTaskHandler:
    """延迟任务处理器，负责延迟任务触发回调和动作解析"""

    def __init__(self, service):
        """Args:
            service: ActiveCareService 实例，用于访问其属性和方法
        """
        self._service = service

    async def on_delayed_task_trigger(
        self, task_id: str, task_type: str, context: Dict[str, Any],
        source_message: str, action_hint: str,
    ):
        """延迟任务触发回调"""
        if not self._service._running:
            return

        logger.info(f"Active Care: 延迟任务触发 {task_id}, 类型={task_type}")

        try:
            now = time.time()
            min_gap_seconds = int(
                get_active_care_config(
                    "active_care_min_gap_seconds", default=600, settings=self._service.settings
                )
                or 600
            )

            if self._service.checker and self._service.checker.next_decision_ts > now:
                remaining = int(self._service.checker.next_decision_ts - now)
                logger.info(
                    "Active Care: 延迟任务 %s 被推迟，next_decision_ts 还有 %ds，重新调度 %ds 后",
                    task_id, remaining, min_gap_seconds,
                )
                self._service.delayed_scheduler.schedule_task(
                    delay_seconds=min_gap_seconds,
                    task_type=task_type,
                    context=context,
                    source_message=source_message,
                    action_hint=action_hint,
                )
                return

            if self._service.executor and hasattr(self._service.executor, "_last_trigger_ts_by_persona"):
                # 取所有 persona 中最近的触发时间
                all_ts = list(self._service.executor._last_trigger_ts_by_persona.values()) or [0.0]
                last_trigger_ts = max(all_ts)
                elapsed_since_last = now - last_trigger_ts
                if elapsed_since_last < min_gap_seconds:
                    remaining = int(min_gap_seconds - elapsed_since_last)
                    logger.info(
                        "Active Care: 延迟任务 %s 被推迟，距上次触发仅 %ds（需 %ds），重新调度 %ds 后",
                        task_id, int(elapsed_since_last), min_gap_seconds, remaining,
                    )
                    self._service.delayed_scheduler.schedule_task(
                        delay_seconds=remaining,
                        task_type=task_type,
                        context=context,
                        source_message=source_message,
                        action_hint=action_hint,
                    )
                    return

            chosen_action, thought = self.resolve_delayed_task_action(
                task_type, context, action_hint
            )

            delivered = await self._service.executor.trigger_message(
                sys_prompt_type=chosen_action,
                user_input_mock=f"[DELAYED_FOLLOW_UP:{action_hint}]",
                thought=thought,
                client_type=probe_client_type(),
            )

            if delivered:
                self._service.last_intent = chosen_action

        except Exception as e:
            logger.error(f"Active Care: 延迟任务回调执行失败: {e}")

    @staticmethod
    def resolve_delayed_task_action(
        task_type: str, context: Dict[str, Any], action_hint: str,
    ) -> tuple:
        """解析延迟任务动作"""
        action_map = {
            "action_follow_up": ("curious_question", f"用户说要去{action_hint}，问问情况"),
            "urgent_follow_up": ("emotional_support", "用户提到紧急的事情，需要跟进"),
            "time_based_follow_up": ("curious_question", f"用户说{action_hint}，跟进一下"),
            "user_requested_follow_up": ("curious_question", f"用户请求的定时关怀：{action_hint}"),
        }
        return action_map.get(task_type, ("curious_question", f"跟进{action_hint or '事情'}"))
