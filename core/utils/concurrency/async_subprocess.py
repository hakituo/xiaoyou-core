"""异步子进程工具：保证超时/异常时清理子进程，避免孤儿进程泄漏。

P0-18 修复：原 `asyncio.create_subprocess_exec` + `asyncio.wait_for` 组合
在超时/异常路径上不会 kill 子进程，导致 nvidia-smi 等子进程成为孤儿
持续占用进程表与 PIPE 文件描述符。本工具统一封装 kill+wait 清理逻辑。
"""
from __future__ import annotations
from core.utils.logger import get_logger

import asyncio

from pathlib import Path
from typing import Optional, Union

logger = get_logger(__name__)


async def run_subprocess_with_timeout(
    args: list[str],
    *,
    timeout: float,
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[dict] = None,
) -> tuple[int, bytes, bytes]:
    """运行子进程，超时或异常时确保 kill+wait 清理。

    Args:
        args: 子进程命令与参数列表（与 asyncio.create_subprocess_exec 一致）
        timeout: 超时秒数
        cwd: 子进程工作目录
        env: 子进程环境变量

    Returns:
        (returncode, stdout_bytes, stderr_bytes)

    Raises:
        asyncio.TimeoutError: 超时（子进程已被 kill+wait 清理）
        Exception: 其他异常（子进程也已被清理）
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode if proc.returncode is not None else -1, stdout, stderr
    except asyncio.TimeoutError:
        await _safe_kill(proc)
        raise
    except Exception:
        await _safe_kill(proc)
        raise


async def _safe_kill(proc: asyncio.subprocess.Process) -> None:
    """安全 kill+wait 子进程，吞掉所有异常，确保不阻塞。"""
    try:
        if proc.returncode is None:
            proc.kill()
    except ProcessLookupError:
        # 进程已退出，无需处理
        pass
    except Exception as e:
        logger.debug(f"kill 子进程失败（忽略）: {type(e).__name__}: {e}")
    try:
        await proc.wait()
    except Exception as e:
        logger.debug(f"wait 子进程失败（忽略）: {type(e).__name__}: {e}")
