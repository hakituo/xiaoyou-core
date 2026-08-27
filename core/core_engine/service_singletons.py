#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务服务单例管理
管理 Aveline、Vision、ActiveCare 等服务的单例实例
"""

from core.utils.logger import get_logger
from core.utils.async_tasks import spawn_bg_task
import time
import asyncio

logger = get_logger(__name__)

# 全局单例实例
_aveline_service = None
_vision_module = None


def get_aveline_service():
    """获取全局Aveline服务实例（懒加载）"""
    global _aveline_service
    if _aveline_service is None:
        return initialize_aveline_service_sync()
    return _aveline_service


def get_vision_module():
    """获取视觉模块实例 (单例模式)"""
    global _vision_module
    if _vision_module is None:
        try:
            logger.info("正在初始化 VisionModule...")
            from core.modules.vision.module import VisionModule

            _vision_module = VisionModule()
            logger.info("VisionModule 初始化成功")
        except Exception as e:
            logger.error(f"VisionModule 初始化失败: {e}", exc_info=True)
            return None
    return _vision_module


def initialize_aveline_service_sync():
    """同步构造Aveline服务（轻量，仅创建实例，不执行异步初始化）"""
    global _aveline_service
    try:
        from core.services.aveline.service import AvelineService
        from core.utils.logger import get_logger

        _logger = get_logger(__name__)

        if _aveline_service is None:
            _logger.info("Aveline服务同步构造（轻量）...")
            _aveline_service = AvelineService()
            _logger.info("Aveline服务同步构造成功（需后续调用 initialize() 完成异步初始化）")
        return _aveline_service
    except Exception as e:
        import traceback

        print(f"Aveline服务同步构造失败: {e}")
        traceback.print_exc()
        return None


async def initialize_aveline_service():
    """生命周期初始化Aveline服务"""
    global _aveline_service
    from core.utils.logger import get_logger

    _logger = get_logger(__name__)

    try:
        if _aveline_service is None:
            _logger.info("开始初始化Aveline服务...")
            _t0 = time.perf_counter()
            from core.services.aveline.service import AvelineService
            _logger.info("AvelineService import: %.3fs", time.perf_counter() - _t0)

            _t1 = time.perf_counter()
            _aveline_service = AvelineService()
            _logger.info("AvelineService() 轻量构造: %.3fs", time.perf_counter() - _t1)

        if hasattr(_aveline_service, "initialize"):
            _t2 = time.perf_counter()
            await _aveline_service.initialize()
            _logger.info("AvelineService.initialize(): %.3fs", time.perf_counter() - _t2)

        _logger.info("Aveline服务初始化成功")
        return _aveline_service
    except Exception as e:
        _logger.error(f"Aveline服务初始化失败: {type(e).__name__}: {str(e)}")
        import traceback

        _logger.error(f"详细错误堆栈:\n{traceback.format_exc()}")
        try:
            if _aveline_service is None:
                from core.services.aveline.service import AvelineService

                _aveline_service = AvelineService()
            return _aveline_service
        except Exception:
            return None


async def shutdown_aveline_service():
    """关闭Aveline服务"""
    global _aveline_service
    from core.utils.logger import get_logger

    _logger = get_logger(__name__)

    try:
        if _aveline_service:
            _logger.info("开始关闭Aveline服务...")
            if hasattr(_aveline_service, "shutdown"):
                if asyncio.iscoroutinefunction(_aveline_service.shutdown):
                    await _aveline_service.shutdown()
                else:
                    _aveline_service.shutdown()
            _aveline_service = None
            _logger.info("Aveline服务关闭成功")
    except Exception as e:
        _logger.error(f"Aveline服务关闭失败: {str(e)}")


async def initialize_vision_module():
    """初始化视觉模块"""
    global _vision_module
    try:
        from core.modules.vision.module import VisionModule

        if _vision_module is None:
            _vision_module = VisionModule()
        return _vision_module
    except Exception:
        return None


async def shutdown_vision_module():
    """关闭视觉模块"""
    global _vision_module
    try:
        if _vision_module is None:
            return
        if hasattr(_vision_module, "unload_model"):
            await _vision_module.unload_model()
    except Exception:
        pass
    finally:
        _vision_module = None


async def initialize_active_care_service():
    """初始化主动关怀服务（后台执行，不阻塞启动）"""
    async def _bg_init():
        from core.services.active_care.core.service import get_active_care_service
        from core.utils.config_accessor import get_active_care_config
        from config.integrated_config import get_settings

        settings = get_settings()
        enable_proactive = bool(
            get_active_care_config("active_care_enabled", default=True, settings=settings)
        )
        service = get_active_care_service(enable_proactive_checker=enable_proactive)
        await service.initialize()
        logger.info("active_care_service 后台初始化完成")

    spawn_bg_task(_bg_init(), name="active_care_bg_init")
    logger.info("active_care_service 初始化已调度到后台")


async def shutdown_active_care_service():
    """关闭主动关怀服务"""
    from core.services.active_care.core.service import get_active_care_service

    service = get_active_care_service()
    await service.shutdown()
