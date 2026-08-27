#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务注册表
定义和注册所有默认服务到生命周期管理器
"""

from core.utils.logger import get_logger
import time
import asyncio


from core.core_engine.service_helpers import _is_env_enabled
from core.core_engine.service_singletons import (
    get_vision_module,
    initialize_aveline_service,
    shutdown_aveline_service,
    initialize_active_care_service,
    shutdown_active_care_service,
)

logger = get_logger(__name__)


async def initialize_default_services():
    """初始化默认服务"""
    from core.utils.logger import get_logger
    from core.core_engine.lifecycle_manager import get_lifecycle_manager

    _logger = get_logger(__name__)
    lifecycle = get_lifecycle_manager()

    _logger.info("正在预注册核心服务...")

    if _is_env_enabled("XIAOYOU_PRELOAD_VISION"):
        if _is_env_enabled("XIAOYOU_DISABLE_IMAGE"):
            _logger.info("检测到 XIAOYOU_DISABLE_IMAGE=1，跳过 VisionModule 预加载")
        else:
            get_vision_module()
    else:
        _logger.info("未启用 VisionModule 预加载")

    _logger.info("核心服务预注册完成")

    # --- 资源管理器 (优先级 1) ---
    async def init_resource_manager():
        from core.resource_manager import get_resource_manager
        rm = get_resource_manager()
        await rm.start()

    async def shutdown_resource_manager():
        from core.resource_manager import get_resource_manager
        rm = get_resource_manager()
        await rm.stop()

    lifecycle.register_service(
        name="resource_manager",
        initialize_func=init_resource_manager,
        shutdown_func=shutdown_resource_manager,
        priority=1,
        preload_modules=["core.resource_manager"],
    )

    # --- 日志脱敏 (优先级 1) ---
    async def init_log_sanitizer():
        from core.utils.errors.log_sanitizer import initialize_sanitizer
        await initialize_sanitizer()

    async def shutdown_log_sanitizer():
        from core.utils.errors.log_sanitizer import shutdown_sanitizer
        await shutdown_sanitizer()

    lifecycle.register_service(
        name="log_sanitizer",
        initialize_func=init_log_sanitizer,
        shutdown_func=shutdown_log_sanitizer,
        priority=1,
        preload_modules=["core.utils.log_sanitizer"],
    )

    # --- 错误收集器 (优先级 1，需在 log_sanitizer 之后) ---
    # 捕获所有 ERROR+ 日志，写入 logs/errors/ 和根目录 errors_YYYYMMDD.json
    async def init_error_collector():
        from core.utils.error_collector import install
        await install()

    async def shutdown_error_collector():
        from core.utils.error_collector import uninstall
        await uninstall()

    lifecycle.register_service(
        name="error_collector",
        initialize_func=init_error_collector,
        shutdown_func=shutdown_error_collector,
        priority=1,
        preload_modules=["core.utils.error_collector"],
    )

    # --- CPU 处理器 (优先级 1) ---
    async def init_cpu_processor():
        from core.services.scheduler.task.task_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        await scheduler.start()

    async def shutdown_cpu_processor_fn():
        from core.services.scheduler.task.task_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        await scheduler.stop()

    lifecycle.register_service(
        name="cpu_processor",
        initialize_func=init_cpu_processor,
        shutdown_func=shutdown_cpu_processor_fn,
        priority=1,
        preload_modules=["core.services.scheduler.task.task_scheduler"],
    )

    # --- 配置管理器 (优先级 2) ---
    async def init_config_manager():
        from core.core_engine.config_manager import get_config_manager
        await asyncio.to_thread(get_config_manager)

    async def shutdown_config_manager():
        return

    lifecycle.register_service(
        name="config_manager",
        initialize_func=init_config_manager,
        shutdown_func=shutdown_config_manager,
        priority=2,
    )

    # --- 搜索缓存管理器 (优先级 2) ---
    async def init_search_cache_manager():
        from core.cache.async_cache_manager import get_search_cache_manager
        await get_search_cache_manager().initialize()

    async def shutdown_search_cache_manager():
        try:
            from core.cache.async_cache_manager import get_search_cache_manager
            await get_search_cache_manager().close()
        except Exception:
            return

    lifecycle.register_service(
        name="search_cache_manager",
        initialize_func=init_search_cache_manager,
        shutdown_func=shutdown_search_cache_manager,
        priority=2,
    )

    # --- 缓存系统 (优先级 2) ---
    async def init_cache_system():
        from core.async_cache import initialize_cache
        await initialize_cache()

    async def shutdown_cache_system():
        from core.async_cache import shutdown_cache
        await shutdown_cache()

    lifecycle.register_service(
        name="cache_system",
        initialize_func=init_cache_system,
        shutdown_func=shutdown_cache_system,
        priority=2,
    )

    # --- 系统内存管理器 (优先级 2) ---
    async def init_memory_manager_wrapper():
        from core.services.monitoring.system_memory_service import initialize_system_memory_manager
        await asyncio.to_thread(initialize_system_memory_manager)

    async def shutdown_memory_manager_wrapper():
        from core.services.monitoring.system_memory_service import shutdown_system_memory_manager
        await shutdown_system_memory_manager()

    lifecycle.register_service(
        name="system_memory_manager",
        initialize_func=init_memory_manager_wrapper,
        shutdown_func=shutdown_memory_manager_wrapper,
        priority=2,
    )

    # --- 图片管理器 (优先级 2，与缓存/配置并行) ---
    async def init_image_manager_wrapper():
        return

    async def shutdown_image_manager_wrapper():
        from core.image.image_manager import shutdown_image_manager_instance
        await shutdown_image_manager_instance()

    lifecycle.register_service(
        name="image_manager",
        initialize_func=init_image_manager_wrapper,
        shutdown_func=shutdown_image_manager_wrapper,
        priority=2,
    )

    # --- 任务调度器 (优先级 2，与缓存/配置并行) ---
    async def init_task_scheduler():
        from core.services.scheduler.task.task_scheduler_adapter import initialize_scheduler
        await initialize_scheduler()

    async def shutdown_task_scheduler():
        from core.services.scheduler.task.task_scheduler_adapter import shutdown_scheduler
        await shutdown_scheduler()

    lifecycle.register_service(
        name="task_scheduler",
        initialize_func=init_task_scheduler,
        shutdown_func=shutdown_task_scheduler,
        priority=2,
    )

    # --- 监控系统 (优先级 2，与缓存/配置并行) ---
    async def init_monitoring():
        from core.async_monitor import initialize_monitoring
        await initialize_monitoring()

    async def shutdown_monitoring_fn():
        from core.async_monitor import shutdown_monitoring
        await shutdown_monitoring()

    lifecycle.register_service(
        name="monitoring_system",
        initialize_func=init_monitoring,
        shutdown_func=shutdown_monitoring_fn,
        priority=2,
        preload_modules=["core.async_monitor"],
    )

    # --- 免疫系统 (优先级 3) ---
    async def init_immune_system():
        from core.services.immune.service import initialize_immune_system
        await initialize_immune_system()

    async def shutdown_immune_system():
        from core.services.immune.service import shutdown_immune_system
        await shutdown_immune_system()

    lifecycle.register_service(
        name="immune_system",
        initialize_func=init_immune_system,
        shutdown_func=shutdown_immune_system,
        priority=3,
        preload_modules=["core.services.immune.service"],
    )

    # --- WebSocket 适配器 (优先级 3) ---
    async def init_websocket_adapter():
        from core.interfaces.websocket.fastapi_websocket_adapter import initialize_websocket_adapter
        await initialize_websocket_adapter()

    async def shutdown_websocket_adapter_fn():
        from core.interfaces.websocket.fastapi_websocket_adapter import shutdown_websocket_adapter
        await shutdown_websocket_adapter()

    lifecycle.register_service(
        name="websocket_adapter",
        initialize_func=init_websocket_adapter,
        shutdown_func=shutdown_websocket_adapter_fn,
        priority=3,
        preload_modules=["core.interfaces.websocket.adapters"],
    )

    # --- TTS/STT 服务 (优先级 3) ---
    async def init_tts_service():
        if _is_env_enabled("XIAOYOU_DISABLE_TTS"):
            return
        try:
            from core.voice import get_tts_manager
            manager = await get_tts_manager()
            if manager:
                # 只创建 Manager 实例，不加载模型
                # 模型会在首次调用 synthesize 时按需加载
                logger.info("TTS Manager created (lazy init, model will load on first use)")
        except Exception as e:
            _logger.warning(f"TTS服务初始化失败: {e}")

    async def shutdown_tts_service():
        try:
            from core.voice import shutdown_tts, shutdown_stt
            await shutdown_tts()
            await shutdown_stt()
        except Exception as e:
            _logger.warning(f"TTS/STT服务关闭失败: {e}")

    lifecycle.register_service(
        name="tts_stt_service",
        initialize_func=init_tts_service,
        shutdown_func=shutdown_tts_service,
        priority=3,
        preload_modules=["core.voice"],
    )

    # --- Aveline 服务 (优先级 3，仅创建实例+后台任务，与其他服务并行) ---
    lifecycle.register_service(
        name="aveline_service",
        initialize_func=initialize_aveline_service,
        shutdown_func=shutdown_aveline_service,
        priority=3,
        preload_modules=["core.services.aveline.service"],
    )

    # --- 主动关怀服务 (优先级 3，后台初始化不阻塞启动) ---
    lifecycle.register_service(
        name="active_care_service",
        initialize_func=initialize_active_care_service,
        shutdown_func=shutdown_active_care_service,
        priority=3,
        preload_modules=["core.services.active_care.service"],
    )

    # --- 自动修复服务 (优先级 3) ---
    async def init_auto_heal():
        _t0 = time.perf_counter()
        from core.services.auto_heal.heal_service import initialize_auto_heal
        logger.info("auto_heal: import %.3fs", time.perf_counter() - _t0)
        await initialize_auto_heal()

    async def shutdown_auto_heal():
        from core.services.auto_heal.heal_service import shutdown_auto_heal
        await shutdown_auto_heal()

    lifecycle.register_service(
        name="auto_heal_service",
        initialize_func=init_auto_heal,
        shutdown_func=shutdown_auto_heal,
        priority=3,
        preload_modules=["core.services.auto_heal.heal_service"],
    )

    # --- 日志清理 (优先级 3) ---
    async def init_log_cleanup():
        from core.utils.log_cleanup import log_cleanup_loop
        task = asyncio.create_task(log_cleanup_loop())
        lifecycle._log_cleanup_task = task

    async def shutdown_log_cleanup():
        task = getattr(lifecycle, "_log_cleanup_task", None)
        if task and not task.done():
            task.cancel()

    lifecycle.register_service(
        name="log_cleanup",
        initialize_func=init_log_cleanup,
        shutdown_func=shutdown_log_cleanup,
        priority=3,
    )

    _logger.info("默认服务注册完成")
