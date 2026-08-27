import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

_TASK_TTL_SECONDS = 3600
_TASK_MAX_COUNT = 500


@dataclass
class DataOpsTask:
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    status: str = "queued"
    retries: int = 0
    max_retries: int = 1
    idempotency_key: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Optional[Dict[str, Any]] = None
    error: str = ""


class DataOpsQueue:
    """DataOps 任务队列。

    P1-9 修复要点：
    1. 引入 _lock 保护 _tasks / _idempotency_index / 状态机读改写，
       消除"检查 status==running → 设置 status=running"之间的 TOCTOU 窗口，
       避免多线程并发调用 run_task(task_id) 导致同一任务被双线程同时执行。
    2. run_task 进入时若 status 已是终态（done / failed），直接返回 task，
       不再重新触发 handler，避免"已完成任务被重复执行"。
    3. enqueue 路径同样在锁内做 idempotency_index 检查与写入，
       避免幂等键并发入队导致重复任务。
    """

    def __init__(self):
        self._tasks: Dict[str, DataOpsTask] = {}
        self._idempotency_index: Dict[str, str] = {}
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _evict_expired_locked(self) -> None:
        """在已持有 _lock 的前提下清理过期/超额任务。"""
        now = time.time()
        expired_ids = [
            tid
            for tid, task in self._tasks.items()
            if (now - task.updated_at) > _TASK_TTL_SECONDS
        ]
        for tid in expired_ids:
            task = self._tasks.pop(tid, None)
            if task and task.idempotency_key:
                self._idempotency_index.pop(task.idempotency_key, None)
        if len(self._tasks) > _TASK_MAX_COUNT:
            sorted_tasks = sorted(
                self._tasks.items(), key=lambda x: x[1].updated_at
            )
            for tid, task in sorted_tasks[: len(self._tasks) - _TASK_MAX_COUNT]:
                self._tasks.pop(tid, None)
                if task.idempotency_key:
                    self._idempotency_index.pop(task.idempotency_key, None)

    def register_handler(
        self, task_type: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        with self._lock:
            self._handlers[task_type] = handler

    def enqueue(
        self,
        *,
        task_type: str,
        payload: Dict[str, Any],
        idempotency_key: str = "",
        max_retries: int = 1,
    ) -> DataOpsTask:
        idem = str(idempotency_key or "").strip()
        # 锁内完成"幂等检查 + 任务创建 + 索引写入"原子三连，
        # 避免并发入队时两个线程都通过 idem not in index 检查后各自创建任务。
        with self._lock:
            self._evict_expired_locked()
            if idem and idem in self._idempotency_index:
                return self._tasks[self._idempotency_index[idem]]
            task = DataOpsTask(
                task_id=uuid.uuid4().hex,
                task_type=task_type,
                payload=payload,
                max_retries=max(0, int(max_retries)),
                idempotency_key=idem,
            )
            self._tasks[task.task_id] = task
            if idem:
                self._idempotency_index[idem] = task.task_id
            return task

    def get_task(self, task_id: str) -> Optional[DataOpsTask]:
        with self._lock:
            # 返回浅拷贝，避免调用方在锁外读取时与状态机写竞争产生中间态视图。
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return DataOpsTask(
                task_id=task.task_id,
                task_type=task.task_type,
                payload=dict(task.payload),
                status=task.status,
                retries=task.retries,
                max_retries=task.max_retries,
                idempotency_key=task.idempotency_key,
                created_at=task.created_at,
                updated_at=task.updated_at,
                result=dict(task.result) if task.result else None,
                error=task.error,
            )

    def run_task(self, task_id: str) -> Optional[DataOpsTask]:
        """执行指定任务。

        并发安全：通过 _lock 串行化状态机读改写。
        - 进入时若 status==running：已有线程在执行，直接返回当前 task。
        - 进入时若 status 为终态（done/failed）：不再重新触发，直接返回 task。
        - 进入时若 status==queued：原子地置为 running 后再释放锁执行 handler，
          保证同一 task_id 同一时刻只有一个线程在跑 handler。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # 已有线程在执行：直接返回，不重复触发
            if task.status == "running":
                return task

            # 终态：done（成功完成）或 failed（重试次数耗尽）都不再重新执行
            if task.status in ("done", "failed"):
                return task

            handler = self._handlers.get(task.task_type)
            if not handler:
                task.status = "failed"
                task.error = f"handler_not_found:{task.task_type}"
                task.updated_at = time.time()
                return task

            # 抢占式置为 running：在锁内修改状态，避免 TOCTOU
            task.status = "running"
            task.updated_at = time.time()
            # 在锁内拷贝 payload，避免 handler 执行期间外部修改 task.payload
            payload_snapshot = dict(task.payload)

        # handler 在锁外执行（可能耗时较长），避免长时间持锁阻塞其他任务
        try:
            result = handler(payload_snapshot)
            with self._lock:
                task.result = result
                task.status = "done"
                task.error = ""
                task.updated_at = time.time()
        except Exception as e:
            with self._lock:
                task.retries += 1
                task.error = str(e)
                # 重试次数耗尽置 failed，否则回 queued 等待下次 run_task
                task.status = "failed" if task.retries > task.max_retries else "queued"
                task.updated_at = time.time()

        # 返回最终状态的浅拷贝（与 get_task 一致，避免锁外读到中间态）
        with self._lock:
            return DataOpsTask(
                task_id=task.task_id,
                task_type=task.task_type,
                payload=dict(task.payload),
                status=task.status,
                retries=task.retries,
                max_retries=task.max_retries,
                idempotency_key=task.idempotency_key,
                created_at=task.created_at,
                updated_at=task.updated_at,
                result=dict(task.result) if task.result else None,
                error=task.error,
            )
