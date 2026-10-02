"""
主动关怀检查器 - 时间检测

负责时间相关的覆盖逻辑，包括：
- 长沉默和无发送超时的覆盖逻辑

依赖通过构造函数注入 checker 实例，方法内通过 checker.xxx 访问原 self 属性，
参考 SleepSessionManager 的依赖注入模式。
"""
from core.utils.logger import get_module_logger
from core.services.active_care.decision.decision_context import DecisionFlowContext

msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class CheckerTimeGate:
    """主动关怀检查器 - 时间检测

    封装时间相关的覆盖逻辑，由 ProactiveChecker 委托调用。
    方法签名与原 ProactiveChecker 中对应方法保持一致（去掉 _ 前缀变公开方法）。
    """

    def __init__(self, checker):
        """
        Args:
            checker: ProactiveChecker 实例，用于访问 _decision_executor 等依赖
        """
        self._checker = checker

    def apply_silence_overrides(
        self,
        ctx: DecisionFlowContext,
        should_send: bool,
        thought: str,
        non_response_count: int,
    ) -> tuple:
        """统一应用长沉默和无发送超时覆盖逻辑，委托给 DecisionExecutor.should_force_send"""
        checker = self._checker
        if should_send:
            return should_send, thought

        force_send, reason = checker._decision_executor.should_force_send(
            ctx, non_response_count=non_response_count
        )

        if force_send:
            should_send = True
            if not thought:
                thought = reason
            if reason == "long_silence_fallback":
                msg_logger.info(
                    "Active Care: Forcing send due to long silence fallback (>%ss).",
                    int(ctx.long_silence_seconds),
                )
            elif reason == "no_send_timeout_fallback":
                msg_logger.info(
                    "Active Care: Forcing send due to no-send timeout (last_sent=%ss ago, user_silent=%ss).",
                    int(ctx.now - ctx.last_sent_ts) if ctx.last_sent_ts > 0 else -1,
                    int(ctx.elapsed),
                )

        return should_send, thought
