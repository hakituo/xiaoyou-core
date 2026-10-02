#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生命周期管理器
统一管理所有异步服务的初始化和关闭
"""

import asyncio
import sys
import time
import importlib
from typing import Dict, Any, List, Callable, Awaitable, Optional

from core.contracts import HealthStatus, ServiceRuntimeState
from core.utils.logger import get_logger

logger = get_logger("LIFECYCLE")


class ServiceLifecycle:
    """服务生命周期管理类"""

    def __init__(self):
        self._initialized = False
        self._shutdown = False
        self._services: Dict[str, Dict[str, Any]] = {}
        self._startup_order: List[str] = []
        self._shutdown_order: List[str] = []
        self._priority_groups: Dict[int, List[str]] = {}
        # P1-3: 跟踪初始化失败的服务，避免"初始化失败仍标记为成功"的误判
        # _initialized=True 仅表示"初始化流程已执行"，has_critical_failures 才反映是否有失败
        self._failed_services: List[str] = []
        self._init_errors: Dict[str, str] = {}

    def register_service(
        self,
        name: str,
        initialize_func: Callable[[], Awaitable[None]],
        shutdown_func: Callable[[], Awaitable[None]],
        priority: int = 100,
        preload_modules: Optional[List[str]] = None,
    ):
        """注册服务

        Args:
            name: 服务名称
            initialize_func: 初始化函数
            shutdown_func: 关闭函数
            priority: 优先级，数字越小优先级越高
            preload_modules: 需要预加载的模块列表（并行初始化时在线程池中提前导入）
        """
        self._services[name] = {
            "name": name,
            "initialize": initialize_func,
            "shutdown": shutdown_func,
            "priority": priority,
            "initialized": False,
            "ever_initialized": False,
            "preload_modules": preload_modules or [],
        }

        self._rebuild_order()
        logger.info(f"服务已注册: {name} (优先级: {priority})")

    def _rebuild_order(self):
        """根据优先级重建启动/关闭顺序"""
        sorted_services = sorted(
            self._services.values(), key=lambda x: x["priority"]
        )
        self._startup_order = [s["name"] for s in sorted_services]
        self._shutdown_order = [s["name"] for s in reversed(sorted_services)]

    async def initialize_all(self):
        """
        初始化所有服务（同优先级并行，跨优先级串行）
        并行模式下先串行预加载模块，再并行执行异步初始化
        """
        if self._initialized:
            logger.warning("生命周期管理器已经初始化")
            return

        self._shutdown = False
        logger.info("开始初始化所有服务...")
        total_start = time.perf_counter()
        timings: Dict[str, float] = {}

        try:
            from itertools import groupby

            priority_groups = []
            for priority, group in groupby(
                self._startup_order,
                key=lambda name: self._services[name]["priority"],
            ):
                priority_groups.append((priority, list(group)))

            self._priority_groups = {p: names for p, names in priority_groups}

            for priority, service_names in priority_groups:
                if len(service_names) == 1:
                    name = service_names[0]
                    config = self._services[name]
                    try:
                        logger.info(f"初始化服务: {name}")
                        svc_start = time.perf_counter()
                        await config["initialize"]()
                        svc_elapsed = time.perf_counter() - svc_start
                        timings[name] = svc_elapsed
                        config["initialized"] = True
                        config["ever_initialized"] = True
                        logger.info(f"服务初始化成功: {name} ({svc_elapsed:.3f}s)")
                    except asyncio.CancelledError:
                        logger.warning(f"初始化服务被取消: {name}")
                        # P1-3: 取消也属于失败，需记录
                        self._failed_services.append(name)
                        self._init_errors[name] = "初始化被取消"
                        continue
                    except Exception as e:
                        logger.error(
                            f"初始化服务失败: {name}. 错误: {str(e)}", exc_info=True
                        )
                        # P1-3: 记录失败服务及其错误，避免"失败仍标记为成功"的误判
                        self._failed_services.append(name)
                        self._init_errors[name] = str(e)
                else:
                    logger.info(
                        f"并行初始化优先级 {priority} 的 {len(service_names)} 个服务: {service_names}"
                    )
                    tier_start = time.perf_counter()

                    all_preload = []
                    for sn in service_names:
                        for mod in self._services[sn].get("preload_modules", []):
                            if mod not in all_preload and mod not in sys.modules:
                                all_preload.append(mod)
                    if all_preload:
                        preload_start = time.perf_counter()
                        # P1-1: 使用 asyncio.to_thread 替代 get_event_loop().run_in_executor
                        # 避免 asyncio.get_event_loop() 在 Python 3.10+ 的弃用警告
                        preload_tasks = [
                            asyncio.to_thread(importlib.import_module, mod)
                            for mod in all_preload
                        ]
                        await asyncio.gather(*preload_tasks, return_exceptions=True)
                        logger.info(
                            f"模块并行预加载完成 ({time.perf_counter() - preload_start:.3f}s): {all_preload}"
                        )

                    async def _init_one(name: str):
                        config = self._services[name]
                        try:
                            logger.info(f"初始化服务: {name}")
                            svc_start = time.perf_counter()
                            await config["initialize"]()
                            svc_elapsed = time.perf_counter() - svc_start
                            timings[name] = svc_elapsed
                            config["initialized"] = True
                            config["ever_initialized"] = True
                            logger.info(f"服务初始化成功: {name} ({svc_elapsed:.3f}s)")
                        except asyncio.CancelledError:
                            logger.warning(f"初始化服务被取消: {name}")
                            # P1-3: 取消也属于失败，需记录
                            self._failed_services.append(name)
                            self._init_errors[name] = "初始化被取消"
                        except Exception as e:
                            logger.error(
                                f"初始化服务失败: {name}. 错误: {str(e)}", exc_info=True
                            )
                            # P1-3: 记录失败服务及其错误
                            self._failed_services.append(name)
                            self._init_errors[name] = str(e)

                    await asyncio.gather(*[_init_one(name) for name in service_names])
                    tier_elapsed = time.perf_counter() - tier_start
                    logger.info(
                        f"优先级 {priority} 并行初始化完成 ({tier_elapsed:.3f}s)"
                    )

            # P1-3: 显式汇总失败服务，避免"初始化失败仍静默标记为成功"
            if self._failed_services:
                logger.warning(
                    "初始化流程完成但有 %d 个服务失败: %s",
                    len(self._failed_services),
                    self._failed_services,
                )
            self._initialized = True
            total_elapsed = time.perf_counter() - total_start
            sorted_timings = sorted(timings.items(), key=lambda x: x[1], reverse=True)
            logger.info("所有服务初始化完成 (%.3fs)", total_elapsed)
            logger.info("=== 启动耗时排行 ===")
            for name, elapsed in sorted_timings:
                pct = (elapsed / total_elapsed * 100) if total_elapsed > 0 else 0
                logger.info("  %-30s %8.3fs (%5.1f%%)", name, elapsed, pct)
            # 各优先级耗时汇总
            logger.info("=== 优先级耗时 ===")
            for p in sorted(self._priority_groups.keys()):
                names = self._priority_groups[p]
                tier_total = sum(timings.get(n, 0) for n in names)
                logger.info("  优先级 %d: %.3fs (%s)", p, tier_total, ", ".join(names))
            logger.info("====================")

        except Exception as e:
            logger.error(f"初始化过程出错: {str(e)}", exc_info=True)
            await self.shutdown_all()
            raise

    async def shutdown_all(self):
        """关闭所有服务"""
        if self._shutdown:
            logger.warning("生命周期管理器已经关闭")
            return

        self._shutdown = True
        per_service_timeout: Optional[float] = None
        try:
            from config.integrated_config import get_settings

            per_service_timeout = float(
                get_settings().server.shutdown_service_timeout_seconds
            )
        except Exception:
            per_service_timeout = None

        logger.info("开始关闭所有服务...")

        try:
            from core.services.scheduler.cpp_scheduler_engine import (
                get_scheduler_engine, _engine_started
            )
            if _engine_started:
                engine = get_scheduler_engine(auto_start=False)
                if engine and engine.enabled:
                    logger.info("关闭 cpp_scheduler_engine...")
                    await engine.stop()
        except Exception:
            pass

        try:
            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()
            if rm.is_memory_critical():
                logger.warning("检测到系统内存占用极高，执行紧急预清理以加速退出...")
                await rm.emergency_cleanup()
        except Exception:
            pass

        try:
            MEMORY_INTENSIVE_KEYWORDS = {"llm", "scheduler", "image", "vision", "tts", "stt"}

            intensive_tasks = []
            other_tasks = []

            for service_name in self._shutdown_order:
                service_config = self._services[service_name]
                if not service_config["initialized"]:
                    continue

                is_intensive = any(
                    keyword in service_name.lower()
                    for keyword in MEMORY_INTENSIVE_KEYWORDS
                )
                if is_intensive:
                    intensive_tasks.append((service_name, service_config))
                else:
                    other_tasks.append((service_name, service_config))

            for service_name, service_config in intensive_tasks:
                await self._shutdown_single_service(
                    service_name, service_config, per_service_timeout
                )

            for service_name, service_config in other_tasks:
                await self._shutdown_single_service(
                    service_name, service_config, per_service_timeout
                )

            # 关闭未注册到 lifecycle 但持有 aiohttp session 的全局客户端
            try:
                from core.llm.infer_service_client import get_infer_client
                client = get_infer_client()
                await client.shutdown()
            except Exception:
                pass

            self._initialized = False
            logger.info("所有服务关闭完成")

        except Exception as e:
            logger.error(f"关闭过程出错: {str(e)}", exc_info=True)
            raise

    async def _shutdown_single_service(
        self, name: str, config: Dict[str, Any], timeout: Optional[float]
    ):
        """关闭单个服务及其异常处理"""
        try:
            logger.info(f"关闭服务: {name}")
            shutdown_coro = config["shutdown"]()
            if timeout is not None and timeout > 0:
                await asyncio.wait_for(shutdown_coro, timeout=timeout)
            else:
                await shutdown_coro
            config["initialized"] = False
            logger.info(f"服务关闭成功: {name}")
        except asyncio.CancelledError:
            logger.warning(f"关闭服务被取消: {name}")
        except asyncio.TimeoutError:
            logger.error(f"关闭服务超时: {name}")
        except Exception as e:
            logger.error(f"关闭服务失败: {name}. 错误: {str(e)}", exc_info=True)

    def get_status(self) -> Dict[str, Any]:
        """获取所有服务的状态"""
        status = {
            "manager_initialized": self._initialized,
            "manager_shutdown": self._shutdown,
            # P1-3: 暴露失败服务列表与错误信息，避免"失败仍标记为成功"的误判
            "has_critical_failures": bool(self._failed_services),
            "failed_services": list(self._failed_services),
            "init_errors": dict(self._init_errors),
            "services": {},
        }

        for name, service_config in self._services.items():
            initialized = bool(service_config["initialized"])
            ever_initialized = bool(service_config.get("ever_initialized", False))
            status["services"][name] = {
                "initialized": initialized,
                "ever_initialized": ever_initialized,
                "state": (
                    ServiceRuntimeState.INITIALIZED.value
                    if initialized
                    else ServiceRuntimeState.STOPPED.value
                ),
                "priority": service_config["priority"],
                # P1-3: 单服务级别暴露初始化错误
                "init_error": self._init_errors.get(name),
            }

        return status

    async def check_health(self) -> Dict[str, Any]:
        """检查所有服务的健康状态"""
        health_status = {"status": HealthStatus.HEALTHY.value, "services": {}}

        for name, service_config in self._services.items():
            service_health = {
                "status": HealthStatus.HEALTHY.value
                if service_config["initialized"]
                else HealthStatus.UNHEALTHY.value
            }
            health_status["services"][name] = service_health

            if not service_config["initialized"]:
                health_status["status"] = HealthStatus.UNHEALTHY.value

        return health_status

    async def restart_service(self, name: str) -> bool:
        """重启指定服务"""
        if self._shutdown:
            logger.warning(f"生命周期管理器正在关闭，跳过服务重启: {name}")
            return False

        if name not in self._services:
            logger.warning(f"尝试重启未知服务: {name}")
            return False

        service_config = self._services[name]

        try:
            if service_config["initialized"]:
                try:
                    logger.warning(f"重启服务: {name} (先关闭)")
                    await service_config["shutdown"]()
                finally:
                    service_config["initialized"] = False

            logger.warning(f"重启服务: {name} (再初始化)")
            await service_config["initialize"]()
            service_config["initialized"] = True
            service_config["ever_initialized"] = True
            logger.info(f"服务重启成功: {name}")
            return True
        except Exception as e:
            logger.error(f"服务重启失败: {name}. 错误: {str(e)}", exc_info=True)
            return False


# 全局单例
_lifecycle_manager = ServiceLifecycle()


def get_lifecycle_manager() -> ServiceLifecycle:
    """获取全局生命周期管理器实例"""
    return _lifecycle_manager
