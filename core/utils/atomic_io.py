"""
统一的原子文件 I/O 模块

提供线程安全、异步友好的原子写入功能，融合了以下实现的优点：
- memory/core/persistence.py: 线程安全临时文件名 + 指数退避重试 + Windows 错误码检测
- memory/core/async_persistence.py: 异步支持
- core/services/active_care/storage.py: fsync 保证数据持久化

特性：
1. 临时文件命名：线程+进程安全
2. 指数退避重试：覆盖 Windows 杀毒软件/索引器锁
3. fsync 支持：可选的数据持久化保证
4. Windows 错误码检测：winerror 5/32
5. 同步/异步双版本
"""

from __future__ import annotations
from core.utils.logger import get_logger

import asyncio
import json

import os
import threading
import time
from pathlib import Path
from typing import Any, Union

logger = get_logger(__name__)

try:
    import aiofiles
    import aiofiles.os
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False


# ============================================================================
# 公共工具函数
# ============================================================================

def _should_retry_fs_error(e: Exception) -> bool:
    """判断文件系统错误是否应该重试"""
    if isinstance(e, PermissionError):
        return True
    if isinstance(e, OSError):
        winerror = getattr(e, "winerror", None)
        if winerror in {5, 32}:
            return True
        if getattr(e, "errno", None) in {13}:
            return True
    return False


def _ensure_parent_dir(file_path: str) -> None:
    """确保父目录存在"""
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _generate_temp_path(file_path: str) -> str:
    """生成线程+进程+调用唯一的临时文件名

    注意：asyncio 协程共享同一线程，仅用 thread_id+pid 仍会冲突，
    因此追加 uuid 保证每次调用唯一。
    """
    import uuid
    return f"{file_path}.tmp_{threading.get_ident()}_{os.getpid()}_{uuid.uuid4().hex}"


# 陈旧临时文件阈值：正常写入应在数秒内完成，_retry_os_replace 最多重试约 25 秒
# 设为 5 分钟足够安全，不会误删正在写入的临时文件
_STALE_TEMP_FILE_TTL_SECONDS = 300


def _cleanup_stale_temp_files(file_path: str) -> None:
    """清理目标文件的陈旧临时文件残留

    当进程在写入过程中被强制终止（如 Ctrl+C、任务管理器结束进程）时，
    临时文件会残留。本函数清理修改时间超过 _STALE_TEMP_FILE_TTL_SECONDS 的临时文件，
    避免垃圾文件无限堆积。

    只清理与 file_path 同前缀的临时文件（{basename}.tmp_*），
    不会误删其他文件的临时文件。
    """
    try:
        parent = os.path.dirname(file_path)
        if not parent:
            return
        base_name = os.path.basename(file_path)
        prefix = f"{base_name}.tmp_"
        now = time.time()
        for entry in os.listdir(parent):
            if not entry.startswith(prefix):
                continue
            entry_path = os.path.join(parent, entry)
            try:
                mtime = os.path.getmtime(entry_path)
                age = now - mtime
                if age > _STALE_TEMP_FILE_TTL_SECONDS:
                    os.remove(entry_path)
                    logger.debug(
                        "清理陈旧临时文件: %s (age=%.0fs)", entry_path, age
                    )
            except OSError:
                # 文件可能正被其他进程使用，跳过
                continue
    except Exception:
        # 清理失败不影响主流程
        pass


# ============================================================================
# 同步版本
# ============================================================================

def _retry_os_replace(
    src: str, dst: str, *, attempts: int = 10, use_fsync: bool = False
) -> None:
    """
    指数退避重试文件替换

    Args:
        src: 源文件路径
        dst: 目标文件路径
        attempts: 最大重试次数
        use_fsync: 是否在替换前调用 fsync
    """
    # 指数退避：总等待约 25 秒，足以覆盖杀毒软件扫描和 Windows 索引器锁
    delays = [0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 6.4, 6.4]
    last_err: Exception | None = None

    for i in range(max(1, int(attempts))):
        try:
            if use_fsync:
                # 在替换前将源文件数据刷到磁盘
                try:
                    fd = os.open(src, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError as fsync_err:
                    logger.debug("_retry_os_replace fsync 失败（可忽略）: %s", fsync_err)
            os.replace(src, dst)
            return
        except Exception as e:
            last_err = e
            if (i >= len(delays)) or (not _should_retry_fs_error(e)):
                raise
            time.sleep(delays[i])

    if last_err is not None:
        raise last_err


def safe_json_dump(
    data: Any,
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    use_fsync: bool = False,
) -> None:
    """
    同步安全写入 JSON 文件（原子写入）

    Args:
        data: 要写入的数据
        file_path: 文件路径
        encoding: 文件编码
        use_fsync: 是否调用 fsync 保证数据持久化
    """
    file_path_str = str(file_path)
    _ensure_parent_dir(file_path_str)
    # 清理上次崩溃可能残留的陈旧临时文件
    _cleanup_stale_temp_files(file_path_str)
    temp_path = _generate_temp_path(file_path_str)

    try:
        with open(temp_path, "w", encoding=encoding) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as fsync_err:
                # 某些 Windows / 沙箱环境下 fileno 可能不可用，忽略后继续走替换。
                logger.debug("safe_json_dump fsync 失败（可忽略）: %s", fsync_err)
        _retry_os_replace(temp_path, file_path_str, use_fsync=use_fsync)
    except PermissionError:
        # 原子替换最终仍失败，回退到直接写入（非原子但保证数据不丢失）
        try:
            with open(file_path_str, "w", encoding=encoding) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def safe_json_load(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: Any = None,
) -> Any:
    """
    同步安全读取 JSON 文件

    Args:
        file_path: 文件路径
        encoding: 文件编码
        default: 读取失败时的默认值

    Returns:
        解析后的数据，或 default
    """
    file_path_str = str(file_path)
    if not os.path.exists(file_path_str):
        return default

    try:
        with open(file_path_str, "r", encoding=encoding) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def safe_write_text(
    text: str,
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    use_fsync: bool = False,
) -> None:
    """
    同步安全写入纯文本文件（原子写入）

    与 safe_json_dump 相同的原子写入策略（临时文件 + os.replace + 重试），
    但用于纯文本内容（如 MEMORY.md、日志文件等）。

    Args:
        text: 要写入的文本内容
        file_path: 文件路径
        encoding: 文件编码
        use_fsync: 是否调用 fsync 保证数据持久化
    """
    file_path_str = str(file_path)
    _ensure_parent_dir(file_path_str)
    _cleanup_stale_temp_files(file_path_str)
    temp_path = _generate_temp_path(file_path_str)

    try:
        with open(temp_path, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as fsync_err:
                logger.debug("safe_write_text fsync 失败（可忽略）: %s", fsync_err)
        _retry_os_replace(temp_path, file_path_str, use_fsync=use_fsync)
    except PermissionError:
        # 原子替换最终仍失败，回退到直接写入（非原子但保证数据不丢失）
        try:
            with open(file_path_str, "w", encoding=encoding) as f:
                f.write(text)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def safe_read_text(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: str = "",
) -> str:
    """
    同步安全读取纯文本文件

    Args:
        file_path: 文件路径
        encoding: 文件编码
        default: 读取失败时的默认值

    Returns:
        文件内容字符串，或 default
    """
    file_path_str = str(file_path)
    if not os.path.exists(file_path_str):
        return default

    try:
        with open(file_path_str, "r", encoding=encoding) as f:
            return f.read()
    except OSError:
        return default


# ============================================================================
# 异步版本
# ============================================================================

async def _async_retry_os_replace(
    src: str, dst: str, *, attempts: int = 6, use_fsync: bool = False
) -> None:
    """异步重试文件替换"""
    delays = [0.03, 0.06, 0.12, 0.24, 0.48, 0.96]
    last_err: Exception | None = None

    # 检查源文件是否存在
    if not os.path.exists(src):
        raise FileNotFoundError(f"临时文件不存在: {src}")

    for i in range(max(1, int(attempts))):
        try:
            if use_fsync:
                # 安全地执行 fsync，处理可能的文件描述符错误
                try:
                    fd = os.open(src, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError as fsync_err:
                    # 忽略 fsync 错误，继续尝试替换
                    logger.debug(f"fsync 失败（可忽略）: {fsync_err}")

            # 统一使用 os.replace（通过线程池异步执行），避免 aiofiles.os.replace 在 Windows 上的问题
            await asyncio.to_thread(os.replace, src, dst)
            return
        except Exception as e:
            last_err = e
            if (i >= len(delays)) or (not _should_retry_fs_error(e)):
                raise
            await asyncio.sleep(delays[i])

    if last_err is not None:
        raise last_err


async def async_safe_json_dump(
    data: Any,
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    use_fsync: bool = False,
) -> None:
    """
    异步安全写入 JSON 文件（原子写入）

    Args:
        data: 要写入的数据
        file_path: 文件路径
        encoding: 文件编码
        use_fsync: 是否调用 fsync 保证数据持久化
    """
    file_path_str = str(file_path)
    _ensure_parent_dir(file_path_str)
    # 使用线程+进程唯一的临时文件名，避免多个 ActiveCareStorage 实例并发写入同一目标文件时
    # 共用 .tmp 导致竞态（一个实例替换走 .tmp 后，另一个实例 os.replace 报 WinError 2）
    # 同时清理上次崩溃可能残留的陈旧临时文件
    _cleanup_stale_temp_files(file_path_str)
    temp_path = _generate_temp_path(file_path_str)

    if AIOFILES_AVAILABLE:
        try:
            async with aiofiles.open(temp_path, "w", encoding=encoding) as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                await f.flush()
                if use_fsync:
                    # 使用底层同步文件对象的 fileno()，避免异步上下文中的文件描述符问题
                    sync_file = getattr(f, '_file', None)
                    if sync_file is not None:
                        os.fsync(sync_file.fileno())
                    else:
                        os.fsync(f.fileno())
            await _async_retry_os_replace(temp_path, file_path_str, use_fsync=use_fsync)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    await aiofiles.os.remove(temp_path)
                except Exception:
                    pass
            raise
    else:
        # 回退到同步版本
        await asyncio.to_thread(safe_json_dump, data, file_path, encoding, use_fsync)


async def async_safe_json_load(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: Any = None,
) -> Any:
    """
    异步安全读取 JSON 文件

    Args:
        file_path: 文件路径
        encoding: 文件编码
        default: 读取失败时的默认值

    Returns:
        解析后的数据，或 default
    """
    file_path_str = str(file_path)
    if not os.path.exists(file_path_str):
        return default

    try:
        if AIOFILES_AVAILABLE:
            async with aiofiles.open(file_path_str, "r", encoding=encoding) as f:
                content = await f.read()
                return json.loads(content)
        else:
            return await asyncio.to_thread(safe_json_load, file_path, encoding, default)
    except (json.JSONDecodeError, OSError):
        return default


async def async_safe_write_text(
    text: str,
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    use_fsync: bool = False,
) -> None:
    """
    异步安全写入纯文本文件（原子写入）

    与 async_safe_json_dump 相同的原子写入策略，但用于纯文本内容。

    Args:
        text: 要写入的文本内容
        file_path: 文件路径
        encoding: 文件编码
        use_fsync: 是否调用 fsync 保证数据持久化
    """
    file_path_str = str(file_path)
    _ensure_parent_dir(file_path_str)
    _cleanup_stale_temp_files(file_path_str)
    temp_path = _generate_temp_path(file_path_str)

    if AIOFILES_AVAILABLE:
        try:
            async with aiofiles.open(temp_path, "w", encoding=encoding) as f:
                await f.write(text)
                await f.flush()
                if use_fsync:
                    sync_file = getattr(f, '_file', None)
                    if sync_file is not None:
                        os.fsync(sync_file.fileno())
                    else:
                        os.fsync(f.fileno())
            await _async_retry_os_replace(temp_path, file_path_str, use_fsync=use_fsync)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    await aiofiles.os.remove(temp_path)
                except Exception:
                    pass
            raise
    else:
        # 回退到同步版本
        await asyncio.to_thread(safe_write_text, text, file_path, encoding, use_fsync)


async def async_safe_read_text(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: str = "",
) -> str:
    """
    异步安全读取纯文本文件

    Args:
        file_path: 文件路径
        encoding: 文件编码
        default: 读取失败时的默认值

    Returns:
        文件内容字符串，或 default
    """
    file_path_str = str(file_path)
    if not os.path.exists(file_path_str):
        return default

    try:
        if AIOFILES_AVAILABLE:
            async with aiofiles.open(file_path_str, "r", encoding=encoding) as f:
                return await f.read()
        else:
            return await asyncio.to_thread(safe_read_text, file_path, encoding, default)
    except OSError:
        return default
