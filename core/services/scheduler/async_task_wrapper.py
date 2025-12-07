# -*- coding: utf-8 -*-
"""
异步任务包装器
提供统一的任务化接口，将耗时操作（如TTS、STT）包装为可跟踪的任务
"""
import asyncio
import logging
import uuid
from typing import Callable, Any, Optional, Dict, Union, List
from dataclasses import dataclass, field
from enum import Enum

from core.services.scheduler.task_scheduler import (
    get_global_scheduler,
    get_current_task_id,
    TaskPriority,
    TaskStatus,
    TaskInfo
)
from core.utils.logger import get_logger

logger = get_logger("AsyncTaskWrapper")


class TaskType(Enum):
    """任务类型枚举"""
    CPU = "cpu"           # CPU密集型任务
    GPU = "gpu"           # GPU密集型任务
    IO = "io"             # IO密集型任务
    TTS = "tts"           # 文本转语音任务
    STT = "stt"           # 语音转文本任务
    IMAGE = "image"       # 图像处理任务
    LLM = "llm"           # 大语言模型任务


@dataclass
class EnhancedTaskInfo(TaskInfo):
    """增强的任务信息"""
    task_type: Optional[TaskType] = None
    progress: float = 0.0  # 任务进度，0.0-1.0
    metadata: Dict[str, Any] = field(default_factory=dict)  # 任务元数据


class AsyncTaskWrapper:
    """
    异步任务包装器
    提供统一的任务化接口，支持进度跟踪、取消、状态查询等功能
    """
    
    def __init__(self):
        self._scheduler = get_global_scheduler()
        self._tasks: Dict[str, EnhancedTaskInfo] = {}
        self._lock = asyncio.Lock()
        self._progress_callbacks: Dict[str, List[Callable]] = {}
    
    async def submit_tts_task(
        self,
        text: str,
        speaker_wav: Optional[str] = None,
        language: str = "zh",
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        **kwargs
    ) -> str:
        """
        提交TTS任务
        
        Args:
            text: 要转换的文本
            speaker_wav: 说话人参考音频
            language: 语言代码
            priority: 任务优先级
            **kwargs: 其他参数
            
        Returns:
            任务ID
        """
        from core.voice import text_to_speech
        
        async def tts_task_wrapper():
            """TTS任务包装器，支持进度跟踪"""
            task_id = get_current_task_id()
            if not task_id:
                logger.warning("tts_task_wrapper running without task context")
                # Fallback or dummy task_id? If context is missing, progress updates might fail silently or we can skip them.
                # For now, just log warning. progress updates will fail if task_id is None.
            
            try:
                if task_id:
                    # 更新进度
                    await self.update_progress(task_id, 0.1, "开始TTS处理")
                    await self.update_progress(task_id, 0.2, "初始化TTS引擎")
                
                result = await text_to_speech(
                    text=text,
                    speaker_wav=speaker_wav,
                    language=language,
                    **kwargs
                )
                
                if task_id:
                    await self.update_progress(task_id, 0.9, "TTS处理完成")
                
                return {
                    "audio_data": result,
                    "text": text,
                    "language": language
                }
            except Exception as e:
                if task_id:
                    logger.error(f"TTS任务 {task_id} 执行失败: {str(e)}", exc_info=True)
                else:
                    logger.error(f"TTS任务执行失败: {str(e)}", exc_info=True)
                raise
        
        # 创建增强的任务信息
        task_id = await self._submit_task(
            func=tts_task_wrapper,
            name="tts_task",
            task_type=TaskType.TTS,
            priority=priority,
            args=(),
            metadata={
                "text": text[:100] + "..." if len(text) > 100 else text,
                "language": language,
                "has_speaker": speaker_wav is not None
            }
        )
        
        return task_id
    
    async def submit_stt_task(
        self,
        audio_file: str,
        language: str = "zh-CN",
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        **kwargs
    ) -> str:
        """
        提交STT任务
        
        Args:
            audio_file: 音频文件路径
            language: 语言代码
            priority: 任务优先级
            **kwargs: 其他参数
            
        Returns:
            任务ID
        """
        # 延迟导入避免循环依赖
        from multimodal.stt_connector import get_stt_connector
        
        async def stt_task_wrapper():
            """STT任务包装器，支持进度跟踪"""
            task_id = get_current_task_id()
            
            try:
                if task_id:
                    # 更新进度
                    await self.update_progress(task_id, 0.1, "开始STT处理")
                
                # 获取STT连接器
                stt_connector = get_stt_connector()
                if task_id:
                    await self.update_progress(task_id, 0.2, "初始化STT引擎")
                
                # 执行STT
                result = await stt_connector.transcribe(
                    audio_file=audio_file,
                    language=language,
                    **kwargs
                )
                if task_id:
                    await self.update_progress(task_id, 0.9, "STT处理完成")
                
                return {
                    "text": result,
                    "audio_file": audio_file
                }
            except Exception as e:
                if task_id:
                    logger.error(f"STT任务 {task_id} 执行失败: {str(e)}", exc_info=True)
                else:
                    logger.error(f"STT任务执行失败: {str(e)}", exc_info=True)
                raise
        
        # 创建增强的任务信息
        task_id = await self._submit_task(
            func=stt_task_wrapper,
            name="stt_task",
            task_type=TaskType.STT,
            priority=priority,
            args=(),
            metadata={
                "audio_file": audio_file,
                "language": language
            }
        )
        
        return task_id
    
    async def submit_image_task(
        self,
        func: Callable,
        name: str,
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        args: tuple = (),
        kwargs: dict = None,
        metadata: dict = None
    ) -> str:
        """
        提交图像处理任务
        
        Args:
            func: 处理函数
            name: 任务名称
            priority: 任务优先级
            args: 函数位置参数
            kwargs: 函数关键字参数
            metadata: 任务元数据
            
        Returns:
            任务ID
        """
        return await self._submit_task(
            func=func,
            name=name,
            task_type=TaskType.IMAGE,
            priority=priority,
            args=args,
            kwargs=kwargs or {},
            metadata=metadata or {}
        )
    
    async def _submit_task(
        self,
        func: Callable,
        name: str,
        task_type: TaskType,
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        args: tuple = (),
        kwargs: dict = None,
        metadata: dict = None
    ) -> str:
        """
        内部方法：提交任务
        """
        # 提交任务到调度器
        task_id = await self._scheduler.schedule_task(
            func=func,
            name=name,
            priority=priority,
            args=args,
            kwargs=kwargs or {}
        )
        
        # 创建增强的任务信息
        base_info = await self._scheduler.get_task_status(task_id)
        if base_info:
            enhanced_info = EnhancedTaskInfo(
                task_id=base_info.task_id,
                name=base_info.name,
                priority=base_info.priority,
                created_at=base_info.created_at,
                status=base_info.status,
                result=base_info.result,
                error=base_info.error,
                start_time=base_info.start_time,
                end_time=base_info.end_time,
                cancel_requested=base_info.cancel_requested,
                task_type=task_type,
                progress=0.0,
                metadata=metadata or {}
            )
            
            async with self._lock:
                self._tasks[task_id] = enhanced_info
            
            logger.info(f"任务已提交 - ID: {task_id}, 类型: {task_type.name}, 名称: {name}")
        
        return task_id
    
    async def get_task_info(self, task_id: str) -> Optional[EnhancedTaskInfo]:
        """
        获取增强的任务信息
        
        Args:
            task_id: 任务ID
            
        Returns:
            增强的任务信息，如果任务不存在返回None
        """
        async with self._lock:
            if task_id not in self._tasks:
                return None
            
            # 更新基础信息
            base_info = await self._scheduler.get_task_status(task_id)
            if base_info:
                enhanced_info = self._tasks[task_id]
                enhanced_info.status = base_info.status
                enhanced_info.result = base_info.result
                enhanced_info.error = base_info.error
                enhanced_info.start_time = base_info.start_time
                enhanced_info.end_time = base_info.end_time
                enhanced_info.cancel_requested = base_info.cancel_requested
                
                return enhanced_info
        
        return None
    
    async def update_progress(
        self,
        task_id: str,
        progress: float,
        message: Optional[str] = None
    ) -> bool:
        """
        更新任务进度
        
        Args:
            task_id: 任务ID
            progress: 进度值（0.0-1.0）
            message: 进度消息
            
        Returns:
            是否更新成功
        """
        async with self._lock:
            if task_id not in self._tasks:
                return False
            
            # 确保进度值在有效范围内
            progress = max(0.0, min(1.0, progress))
            
            # 更新进度
            self._tasks[task_id].progress = progress
            if message:
                self._tasks[task_id].metadata['progress_message'] = message
            
            # 触发进度回调
            if task_id in self._progress_callbacks:
                for callback in self._progress_callbacks[task_id]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(task_id, progress, message)
                        else:
                            callback(task_id, progress, message)
                    except Exception as e:
                        logger.error(f"进度回调执行失败: {str(e)}", exc_info=True)
            
            logger.debug(f"任务 {task_id} 进度更新: {progress:.1%} - {message}")
            return True
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否取消成功
        """
        result = await self._scheduler.cancel_task(task_id)
        if result:
            logger.info(f"任务已取消 - ID: {task_id}")
        return result
    
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        等待任务完成并获取结果
        
        Args:
            task_id: 任务ID
            timeout: 等待超时时间
            
        Returns:
            任务结果
            
        Raises:
            TimeoutError: 任务超时
            Exception: 任务执行失败
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # 检查超时
            if timeout and asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"任务 {task_id} 执行超时")
            
            # 获取任务信息
            task_info = await self.get_task_info(task_id)
            if not task_info:
                raise ValueError(f"任务 {task_id} 不存在")
            
            # 检查任务状态
            if task_info.status == TaskStatus.COMPLETED:
                return task_info.result
            elif task_info.status == TaskStatus.FAILED:
                raise Exception(f"任务执行失败: {task_info.error}")
            elif task_info.status == TaskStatus.CANCELLED:
                raise Exception(f"任务已取消")
            
            # 等待一段时间后再次检查
            await asyncio.sleep(0.1)
    
    def register_progress_callback(
        self,
        task_id: str,
        callback: Callable[[str, float, Optional[str]], None]
    ) -> None:
        """
        注册进度回调
        
        Args:
            task_id: 任务ID
            callback: 进度回调函数，签名为(task_id, progress, message)
        """
        asyncio.create_task(self._register_progress_callback(task_id, callback))
    
    async def _register_progress_callback(
        self,
        task_id: str,
        callback: Callable[[str, float, Optional[str]], None]
    ) -> None:
        """
        内部方法：注册进度回调
        """
        async with self._lock:
            if task_id not in self._progress_callbacks:
                self._progress_callbacks[task_id] = []
            self._progress_callbacks[task_id].append(callback)
    
    async def get_active_tasks(self) -> Dict[str, EnhancedTaskInfo]:
        """
        获取所有活跃任务
        
        Returns:
            任务ID到增强任务信息的映射
        """
        result = {}
        active_task_ids = set((await self._scheduler.get_active_tasks()).keys())
        
        async with self._lock:
            for task_id, info in self._tasks.items():
                if task_id in active_task_ids:
                    # 更新状态
                    base_info = await self._scheduler.get_task_status(task_id)
                    if base_info:
                        info.status = base_info.status
                    result[task_id] = info
        
        return result
    
    async def clean_completed_tasks(self, max_age: float = 3600) -> int:
        """
        清理已完成的旧任务
        
        Args:
            max_age: 最大保留时间（秒）
            
        Returns:
            清理的任务数量
        """
        cleaned_count = 0
        current_time = asyncio.get_event_loop().time()
        
        async with self._lock:
            expired_task_ids = []
            
            for task_id, task_info in self._tasks.items():
                # 检查任务是否已完成、失败或取消，并且已经超过保留时间
                if (task_info.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] and 
                    task_info.end_time and 
                    current_time - task_info.end_time > max_age):
                    expired_task_ids.append(task_id)
            
            # 移除过期任务
            for task_id in expired_task_ids:
                del self._tasks[task_id]
                if task_id in self._progress_callbacks:
                    del self._progress_callbacks[task_id]
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 个已完成的旧任务")
        
        return cleaned_count


# 全局异步任务包装器实例
_global_task_wrapper: Optional[AsyncTaskWrapper] = None


def get_global_task_wrapper() -> AsyncTaskWrapper:
    """
    获取全局异步任务包装器实例
    
    Returns:
        全局异步任务包装器实例
    """
    global _global_task_wrapper
    if _global_task_wrapper is None:
        _global_task_wrapper = AsyncTaskWrapper()
    return _global_task_wrapper


async def initialize_task_wrapper():
    """
    初始化全局任务包装器
    """
    # 任务包装器不需要特殊初始化，使用时自动创建
    pass


async def shutdown_task_wrapper():
    """
    关闭全局任务包装器
    """
    global _global_task_wrapper
    if _global_task_wrapper is not None:
        # 清理所有任务
        await _global_task_wrapper.clean_completed_tasks(0)
        _global_task_wrapper = None


# 便捷函数
def submit_tts_task(
    text: str,
    speaker_wav: Optional[str] = None,
    language: str = "zh",
    priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
    **kwargs
) -> str:
    """
    便捷函数：提交TTS任务
    """
    return asyncio.create_task(
        get_global_task_wrapper().submit_tts_task(
            text=text,
            speaker_wav=speaker_wav,
            language=language,
            priority=priority,
            **kwargs
        )
    )


def submit_stt_task(
    audio_file: str,
    language: str = "zh-CN",
    priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
    **kwargs
) -> str:
    """
    便捷函数：提交STT任务
    """
    return asyncio.create_task(
        get_global_task_wrapper().submit_stt_task(
            audio_file=audio_file,
            language=language,
            priority=priority,
            **kwargs
        )
    )


def get_task_info(task_id: str) -> Optional[EnhancedTaskInfo]:
    """
    便捷函数：获取任务信息
    """
    return asyncio.create_task(get_global_task_wrapper().get_task_info(task_id))


def cancel_task(task_id: str) -> bool:
    """
    便捷函数：取消任务
    """
    return asyncio.create_task(get_global_task_wrapper().cancel_task(task_id))


def wait_for_task(task_id: str, timeout: Optional[float] = None) -> Any:
    """
    便捷函数：等待任务完成
    """
    return asyncio.create_task(get_global_task_wrapper().wait_for_task(task_id, timeout))
