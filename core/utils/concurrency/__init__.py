"""并发与异步基础设施。

集中放置异步锁、后台任务、资源锁、单例、Saga 事务等并发相关工具。
"""
from core.utils.concurrency.async_locks import LazyAsyncLock
from core.utils.concurrency.async_subprocess import run_subprocess_with_timeout
from core.utils.concurrency.async_tasks import spawn_bg_task
from core.utils.concurrency.resource_lock import GlobalResourceLock, get_resource_lock
from core.utils.concurrency.singleton import singleton, SingletonFactory
from core.utils.concurrency.saga_manager import SagaStep, SagaTransaction

__all__ = [
    "LazyAsyncLock",
    "run_subprocess_with_timeout",
    "spawn_bg_task",
    "GlobalResourceLock",
    "get_resource_lock",
    "singleton",
    "SingletonFactory",
    "SagaStep",
    "SagaTransaction",
]
