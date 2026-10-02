import asyncio
import os
import subprocess
from pathlib import Path

import psutil


async def is_forge_ready(manager) -> bool:
    if not manager.forge_client:
        return False
    try:
        return bool(await asyncio.to_thread(manager.forge_client.ping, 2.0))
    except Exception:
        return False


async def start_forge_process(manager, get_settings, logger) -> bool:
    settings = get_settings()
    forge_dir = Path(getattr(settings.model, "forge_dir", "") or "").expanduser()
    if not forge_dir:
        return False
    if not forge_dir.is_absolute():
        forge_dir = Path.cwd() / forge_dir

    if os.name == "nt":
        candidates = ["webui-user.bat", "webui.bat"]
    else:
        candidates = ["webui.sh", "webui-user.sh"]

    script_path = None
    for name in candidates:
        candidate = forge_dir / name
        if candidate.exists():
            script_path = candidate
            break

    if script_path is None:
        logger.warning("[Forge] 未找到启动脚本，目录=%s", str(forge_dir))
        return False

    def _spawn():
        if os.name == "nt":
            return subprocess.Popen(
                str(script_path),
                cwd=str(forge_dir),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        return subprocess.Popen(
            ["bash", str(script_path)],
            cwd=str(forge_dir),
            start_new_session=True,
        )

    try:
        proc = await asyncio.to_thread(_spawn)
        manager._forge_process = proc
        manager._forge_process_pid = getattr(proc, "pid", None)
        manager._forge_process_started = True
        logger.info("[Forge] 已尝试拉起进程：%s", str(script_path))
        return True
    except Exception as e:
        logger.warning("[Forge] 拉起进程失败：%s", e)
        return False


async def terminate_forge_process(manager) -> None:
    if not manager._forge_process_started:
        return

    pid = manager._forge_process_pid
    if not pid and manager._forge_process is not None:
        try:
            pid = int(manager._forge_process.pid)
        except Exception:
            pid = None

    if not pid:
        return

    def _terminate_tree(target_pid: int):
        try:
            parent = psutil.Process(target_pid)
        except psutil.NoSuchProcess:
            return
        except Exception:
            return

        try:
            children = parent.children(recursive=True)
        except Exception:
            children = []

        targets = [parent, *children]
        for proc in targets:
            try:
                proc.terminate()
            except Exception:
                pass

        try:
            psutil.wait_procs(targets, timeout=3)
        except Exception:
            pass

        for proc in targets:
            try:
                if proc.is_running():
                    proc.kill()
            except Exception:
                pass

    await asyncio.to_thread(_terminate_tree, pid)
    manager._forge_process = None
    manager._forge_process_pid = None
    manager._forge_process_started = False


async def ensure_forge_ready(manager, timeout_seconds: float, get_settings, logger) -> bool:
    if await is_forge_ready(manager):
        return True

    settings = get_settings()
    auto_start = bool(getattr(settings.model, "forge_auto_start", False))
    if not auto_start:
        return False

    async with manager._forge_start_lock:
        if await is_forge_ready(manager):
            return True

        now = asyncio.get_running_loop().time()
        if (now - float(manager._forge_last_start_ts)) >= 3.0:
            manager._forge_last_start_ts = now
            started = await start_forge_process(manager, get_settings, logger)
            if not started:
                return False

        try:
            timeout_seconds = float(timeout_seconds)
        except Exception:
            timeout_seconds = 180.0
        if timeout_seconds <= 0:
            timeout_seconds = 180.0

        deadline = asyncio.get_running_loop().time() + timeout_seconds
        start_wait_ts = asyncio.get_running_loop().time()
        last_log_ts = 0.0
        while asyncio.get_running_loop().time() < deadline:
            if await is_forge_ready(manager):
                elapsed = asyncio.get_running_loop().time() - start_wait_ts
                logger.info("[Forge] 服务已就绪，总计耗时: %.1fs", elapsed)
                return True

            current_wait = asyncio.get_running_loop().time() - start_wait_ts
            if current_wait - last_log_ts >= 10.0:
                logger.info("[Forge] 正在等待服务就绪... 已耗时: %.1fs", current_wait)
                last_log_ts = current_wait

            await asyncio.sleep(1.0)

        return await is_forge_ready(manager)


async def warmup_forge_api(manager, logger) -> None:
    try:
        logger.info("[Forge Warmup] API warmup started")
        await asyncio.to_thread(manager.forge_client.get_models)
        await asyncio.to_thread(manager.forge_client._get_current_model_filename)
        logger.info("[Forge Warmup] API warmup finished")
    except Exception as e:
        logger.warning("[Forge Warmup] API warmup failed: %s", e)
