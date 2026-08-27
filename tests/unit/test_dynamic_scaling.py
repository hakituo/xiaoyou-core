import asyncio
import logging
import os
import time
import pytest
from core.services.scheduler.task.task_scheduler import get_global_scheduler, TaskPriority
from core.services.scheduler.task.task_scheduler_adapter import TaskSchedulerAdapter

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_scaling")

async def mock_task(duration):
    logger.info(f"Task started, duration: {duration}s")
    await asyncio.sleep(duration)
    logger.info(f"Task finished")
    return "done"

async def _test_dynamic_scaling_async():
    adapter = TaskSchedulerAdapter()
    adapter._base_worker_count = 2
    adapter._max_worker_count = 4

    logger.info("Initializing adapter...")
    await adapter.initialize()

    scheduler = get_global_scheduler()
    initial_workers = len(scheduler._workers)
    logger.info(f"Initial workers: {initial_workers}")

    logger.info("Submitting tasks...")
    for i in range(8):
        await scheduler.schedule_task(
            func=mock_task,
            name=f"task-{i}",
            priority=TaskPriority.MEDIUM,
            args=(2,)
        )

    logger.info("Waiting for monitor to trigger scaling...")
    scaled = False
    for i in range(12):
        current_workers = len(scheduler._workers)
        queue_size = scheduler._task_queue.qsize()
        logger.info(f"Step {i}: Workers={current_workers}, Queue={queue_size}")
        if current_workers > initial_workers:
            scaled = True
            break
        await asyncio.sleep(1)

    await scheduler.stop()
    assert scaled, "Dynamic worker scaling not detected."


def test_dynamic_scaling():
    if str(os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS", "") or "").strip() != "1":
        pytest.skip("需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试")
    asyncio.run(_test_dynamic_scaling_async())

if __name__ == "__main__":
    asyncio.run(_test_dynamic_scaling_async())
