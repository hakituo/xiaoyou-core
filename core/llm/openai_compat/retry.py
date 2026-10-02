#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 请求重试策略

只负责「传输层瞬时错误」的重试判定与退避（判定本身在 error_handling 里），
让 chat / stream_chat 不再各自手搓 `for attempt in range(3)` + `0.25 * (attempt + 1)`。
"""

import asyncio

from core.llm.openai_compat.error_handling import is_transient_error


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.25


class RetryPolicy:
    """重试次数与退避策略

    Args:
        max_attempts: 总尝试次数（含首次），即最多重试 max_attempts - 1 次
        backoff_base: 退避基数，第 n 次重试前 sleep base * (attempt + 1) 秒
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
    ):
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def has_next(self, attempt: int) -> bool:
        """当前 attempt（从 0 开始）之后是否还有重试机会"""
        return attempt < self.max_attempts - 1

    def should_retry(
        self,
        error: Exception,
        attempt: int,
        condition: bool = True,
    ) -> bool:
        """判断是否值得重试：还有次数 + 调用方附加条件 + 错误是瞬时故障"""
        return bool(condition) and self.has_next(attempt) and is_transient_error(error)

    async def backoff(self, attempt: int) -> None:
        """重试前退避等待"""
        await asyncio.sleep(self.backoff_base * (attempt + 1))

    def delay(self, attempt: int) -> float:
        """第 attempt 次失败后的退避秒数（供测试断言）"""
        return self.backoff_base * (attempt + 1)
