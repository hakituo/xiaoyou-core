"""
健康监控模块
负责GPU工作器健康检查和调度器重启
"""

from core.utils.logger import get_logger
import asyncio
import gc

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..cpp_scheduler_engine import CPPSchedulerEngine

logger = get_logger(__name__)


class HealthMonitor:
    """健康监控器"""

    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine

    async def health_check_gpu_worker(self) -> bool:
        """
        C++ GPU工作器健康检查：执行简单的推理测试。
        返回True表示健康检查通过，False表示失败。
        """
        if not self.engine.scheduler or not self.engine._gpu_worker_ready:
            logger.warning("健康检查：调度器或GPU工作器未就绪")
            return False

        try:
            logger.info("提交健康检查任务到C++调度器...")

            from ..scheduler_wrapper import _get_scheduler_py

            _scheduler_py = _get_scheduler_py()
            if _scheduler_py is None:
                logger.warning("C++ scheduler bindings not available for health check")
                return False

            req = _scheduler_py.LLMInferenceRequest()
            req.prompt = "Hi"
            req.maxTokens = 4
            req.temperature = 0.1
            req.streamOutput = False

            task = _scheduler_py.LLMTask(req)
            self.engine.scheduler.submitTask(task)

            start_time = time.time()
            max_wait = 15.0

            while time.time() - start_time < max_wait:
                status = task.getStatus()
                if status == _scheduler_py.TaskStatus.COMPLETED:
                    resp = task.getResponse()
                    if resp.success and resp.generatedText:
                        logger.info(
                            f"C++ GPU健康检查通过，响应: {resp.generatedText[:20]}"
                        )
                        return True
                    else:
                        logger.error(f"C++ GPU健康检查失败: {resp.errorMessage}")
                        return False
                elif status == _scheduler_py.TaskStatus.FAILED:
                    resp = task.getResponse()
                    logger.error(f"C++ GPU健康检查任务失败: {resp.errorMessage}")
                    return False

                await asyncio.sleep(0.1)

            logger.error(f"C++ GPU健康检查超时（{max_wait}秒）")
            try:
                task_id = task.getTaskId()
                await asyncio.to_thread(self.engine.scheduler.cancelTask, task_id)
            except Exception:
                pass
            return False

        except Exception as e:
            logger.error(f"C++ GPU健康检查异常: {e}")
            return False

    async def restart_scheduler(self) -> bool:
        """
        重启C++调度器，用于从GPU死锁中恢复。
        返回True表示重启成功，False表示失败。
        """
        try:
            logger.info("开始重启C++调度器...")

            saved_config = None
            if self.engine._gpu_config:
                saved_config = dict(self.engine._gpu_config)

            logger.info("停止当前C++调度器...")
            await self.engine.stop()

            try:
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logger.info("GPU缓存已清理")
            except Exception as e:
                logger.warning(f"清理GPU缓存时出错: {e}")

            await asyncio.sleep(2.0)

            logger.info("重新启动C++调度器...")
            # engine.start 是同步方法，须放到线程中执行；同时传入保存的
            # GPU 配置，使 _llm_backend 与 _gpu_config 在重启后正确恢复
            if saved_config:
                await asyncio.to_thread(self.engine.start, gpu_config=saved_config)
            else:
                await asyncio.to_thread(self.engine.start)

            if saved_config and self.engine._llm_backend == "cpp":
                logger.info("重新初始化GPU工作器...")
                await asyncio.to_thread(self.engine._setup_gpu_worker, saved_config)

            if self.engine.scheduler and self.engine._started:
                logger.info("C++调度器重启成功")
                return True
            else:
                logger.error("C++调度器重启后状态异常")
                return False

        except Exception as e:
            logger.error(f"重启C++调度器失败: {e}")
            return False
