import asyncio
import os
import threading
import sys
import signal
import time
import psutil
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.utils.common import get_project_root

from core.core_engine.lifecycle_manager import get_lifecycle_manager
from core.core_engine.service_registry import initialize_default_services
from core.core_engine.event_bus import EventBus
from core.async_monitor import get_performance_monitor, initialize_monitoring
from core.services.discovery.udp_beacon import start_discovery_beacon, stop_discovery_beacon
from core.utils.async_tasks import spawn_bg_task
from core.utils.logger import get_logger

logger = get_logger(__name__)
event_bus = EventBus()


def _force_kill_self():
    """
    强力终止当前进程及其所有子进程
    """
    try:
        pid = os.getpid()
        # 尝试使用 psutil 获取进程树
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            os._exit(0)
            return

        # 获取所有子进程
        try:
            children = parent.children(recursive=True)
        except Exception:
            children = []

        # 1. 直接强制杀死所有子进程
        for p in children:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception:
                pass

        # 2. 杀死自己
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Force kill failed: {e}")

    # 兜底
    try:
        os._exit(0)
    except Exception:
        raise SystemExit(0)


_win_console_handler_installed = False
_win_console_handler = None
_win_console_kernel32 = None
_shutdown_triggered = False
_shutdown_lock = threading.Lock()
_main_loop: asyncio.AbstractEventLoop | None = None


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    """返回主事件循环引用。

    供子线程（如 nightly processor 调度线程）通过 `asyncio.run_coroutine_threadsafe`
    将协程调度回主 loop 执行，避免新建 event loop 导致 aiohttp 的
    ClientTimeout 在流式 async generator 跨层 yield 时丢失 task 上下文。
    """
    return _main_loop


def _install_windows_console_close_handler(loop: asyncio.AbstractEventLoop):
    global _win_console_handler_installed, _win_console_handler, _win_console_kernel32
    if _win_console_handler_installed:
        return
    if os.name != "nt":
        return

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _win_console_kernel32 = kernel32

        HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        CTRL_C_EVENT = 0
        CTRL_BREAK_EVENT = 1
        CTRL_CLOSE_EVENT = 2
        CTRL_LOGOFF_EVENT = 5
        CTRL_SHUTDOWN_EVENT = 6

        def _request_shutdown(reason: str):
            global _shutdown_triggered
            with _shutdown_lock:
                if _shutdown_triggered:
                    return
                _shutdown_triggered = True

            logger.warning(f"接收到退出信号({reason})，准备关闭...")

            force_exit_timeout = None
            try:
                from config.integrated_config import get_settings

                force_exit_timeout = float(
                    get_settings().server.force_exit_timeout_seconds
                )
            except Exception:
                force_exit_timeout = None

            force_exit_event = threading.Event()

            if force_exit_timeout is not None and force_exit_timeout > 0:

                def _force_exit_watchdog():
                    if not force_exit_event.wait(force_exit_timeout):
                        _force_kill_self()

                threading.Thread(target=_force_exit_watchdog, daemon=True).start()

            def _schedule():
                async def _do_shutdown():
                    force_exit_event.set()
                    logger.warning(
                        f"接收到控制台退出事件({reason})，正在快速释放资源并退出..."
                    )
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(get_lifecycle_manager().shutdown_all()),
                            timeout=5.0,
                        )
                    except Exception:
                        pass

                    try:
                        import gc

                        gc.collect()
                    except Exception:
                        pass

                    try:
                        torch_mod = sys.modules.get("torch")
                        if torch_mod is not None:
                            cuda = getattr(torch_mod, "cuda", None)
                            if (
                                cuda is not None
                                and callable(getattr(cuda, "is_available", None))
                                and cuda.is_available()
                            ):
                                if callable(getattr(cuda, "empty_cache", None)):
                                    cuda.empty_cache()
                                if callable(getattr(cuda, "ipc_collect", None)):
                                    cuda.ipc_collect()
                    except Exception:
                        pass

                    _force_kill_self()

                spawn_bg_task(_do_shutdown(), name="shutdown")

            try:
                loop.call_soon_threadsafe(_schedule)
            except Exception:
                threading.Thread(target=_force_kill_self, daemon=True).start()

        def _handler(ctrl_type: int):
            if ctrl_type in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                _request_shutdown("CTRL_CLOSE/LOGOFF/SHUTDOWN")
                return True
            if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
                _request_shutdown("CTRL_C/CTRL_BREAK")
                return True
            return False

        handler = HANDLER_ROUTINE(_handler)
        ok = bool(kernel32.SetConsoleCtrlHandler(handler, True))
        if ok:
            _win_console_handler = handler
            _win_console_handler_installed = True
            logger.info("Windows 控制台退出处理器已安装")

        def _signal_handler(signum, frame):
            _request_shutdown(f"SIGNAL_{signum}")

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, _signal_handler)
        except Exception as e:
            logger.warning(f"安装信号处理器失败: {e}")
    except Exception as e:
        logger.warning(f"安装 Windows 控制台退出处理器失败: {e}")


def _uninstall_windows_console_close_handler():
    global _win_console_handler_installed, _win_console_handler
    if not _win_console_handler_installed:
        return
    if os.name != "nt":
        return

    try:
        if _win_console_kernel32 is not None and _win_console_handler is not None:
            _win_console_kernel32.SetConsoleCtrlHandler(_win_console_handler, False)
    except Exception:
        pass
    finally:
        _win_console_handler_installed = False
        _win_console_handler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    logger.info(">>> STARTUP EVENT STARTED <<<")
    _startup_t0 = time.perf_counter()
    telegram_adapter = None
    telegram_task: asyncio.Task | None = None

    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
        _install_windows_console_close_handler(_main_loop)
    except Exception:
        pass

    # 初始化默认服务
    _t = time.perf_counter()
    await initialize_default_services()
    logger.info("[启动计时] initialize_default_services: %.3fs", time.perf_counter() - _t)

    # 初始化所有注册的服务
    _t = time.perf_counter()
    await get_lifecycle_manager().initialize_all()
    logger.info("[启动计时] initialize_all: %.3fs", time.perf_counter() - _t)
    logger.info(">>> initialize_all RETURNED, proceeding to post-init <<<")

    # 预启动 C++ 调度器引擎（放到线程池避免阻塞事件循环，防止 WebSocket 连接因懒加载阻塞而断开）
    try:
        from core.services.scheduler.cpp_scheduler_engine import ensure_scheduler_started
        _t = time.perf_counter()
        await asyncio.to_thread(ensure_scheduler_started)
        logger.info("[启动计时] scheduler_engine 预启动: %.3fs", time.perf_counter() - _t)
    except Exception as e:
        logger.warning(f"预启动 C++ 调度器引擎失败: {e}")

    # 注：嵌入模型预加载已统一移至 ChatAgent.initialize() 末尾启动，
    # 避免与 ChatAgent 创建（register_all_tools + 大量 import）抢 GIL。

    # 启动 UDP 服务发现信标（供安卓自动发现）
    logger.info(">>> Starting discovery beacon <<<")
    try:
        from config.integrated_config import get_settings
        http_port = int(get_settings().server.port)
        await start_discovery_beacon(http_port)
        logger.info(f">>> UDP DISCOVERY BEACON STARTED (port {http_port}) <<<")
    except Exception as e:
        logger.warning(f"启动 UDP 发现信标失败: {e}")

    logger.info(">>> APPLICATION SETUP COMPLETED <<<")

    # 启动生活模拟监控
    try:
        from core.services.life_simulation.service import get_life_simulation_service

        logger.info(">>> STARTING LIFE SIMULATION <<<")
        await get_life_simulation_service().start_monitor()
        logger.info(">>> LIFE SIMULATION STARTED <<<")
    except Exception as e:
        logger.error(f"启动生活模拟监控失败: {e}")

    # 启动夜间处理器（记忆蒸馏 + 日记生成）
    try:
        from memory.nightly_processor import NightlyProcessor

        logger.info(">>> STARTING NIGHTLY PROCESSOR <<<")
        # 创建全局单例，应用启动时自动启动定时任务
        nightly_processor = NightlyProcessor()
        # 保存到模块级别，便于关闭时停止
        import memory.nightly_processor as np_module
        np_module._global_processor = nightly_processor
        logger.info(">>> NIGHTLY PROCESSOR STARTED (daily at 23:00) <<<")
    except Exception as e:
        logger.error(f"启动夜间处理器失败: {e}")

    # 启动时检查上月月度总结是否缺失，缺失且有足够数据则异步补生成
    # 异步执行避免阻塞启动；月末夜间任务偶尔因 bug/服务挂掉而漏跑，这里兜底
    try:
        from core.services.journal.monthly_summary_backfill import (
            backfill_last_month_if_missing,
        )
        spawn_bg_task(backfill_last_month_if_missing(), name="monthly_backfill")
        logger.info("已调度月度总结补跑检查任务")
    except Exception as e:
        logger.warning(f"启动月度总结补跑检查失败: {e}")

    # 确保今天的每日单词日志文件存在（用户背单词用，启动时预创建空文件）
    try:
        from core.tools.study.english.daily_word_log import get_daily_word_log
        get_daily_word_log().ensure_today_file()
    except Exception as e:
        logger.warning(f"创建今日单词日志文件失败: {e}")

    # 启动背单词复习提醒器（定时统计待复习量，超阈值触发提醒；通道留接口）
    try:
        from core.tools.study.english.vocab_review_reminder import (
            get_vocab_review_reminder,
        )
        get_vocab_review_reminder().start()
        logger.info("背单词复习提醒器已挂载")
    except Exception as e:
        logger.warning(f"启动背单词复习提醒器失败: {e}")

    # 确保监控服务已启动
    try:
        from core.core_engine.config_manager import ConfigManager

        config = ConfigManager().get_all_config()
        monitor = get_performance_monitor()
        # 如果monitor未初始化或线程未运行
        if (
            monitor is None
            or not monitor.monitor_thread
            or not monitor.monitor_thread.is_alive()
        ):
            logger.info("检测到监控服务未启动，正在强制启动...")
            await initialize_monitoring(config)
            logger.info("监控服务强制启动完成")
    except Exception as e:
        logger.error(f"强制启动监控服务失败: {e}")

    logger.info("所有路由已注册完成")
    for route in app.routes:
        if hasattr(route, "path"):
            logger.info(
                f"Registered Route: {route.path} [{','.join(route.methods) if hasattr(route, 'methods') else ''}]"
            )

    # Telegram 由主程序托管，开关来自 app.yaml 的 telegram.enabled。
    try:
        from clients.bots.telegram.settings import ENABLED as _TG_ENABLED, TELEGRAM_BOT_TOKEN as _TG_TOKEN
        if _TG_ENABLED and _TG_TOKEN:
            from clients.bots.telegram.adapter import TelegramAdapter
            telegram_adapter = TelegramAdapter()
            telegram_task = spawn_bg_task(
                telegram_adapter.run(), name="telegram_adapter"
            )
            logger.info("Telegram 适配器托管任务已提交，等待轮询器就绪")
        elif _TG_ENABLED and not _TG_TOKEN:
            logger.warning("Telegram 适配器 enabled=true 但未配置 TELEGRAM_BOT_TOKEN，跳过启动")
        else:
            logger.info("Telegram 适配器未启用（app.yaml telegram.enabled=false）")
    except Exception as e:
        logger.warning(f"启动 Telegram 适配器失败: {e}")

    spawn_bg_task(event_bus.publish("app.startup_completed"), name="startup_event")
    startup_elapsed = time.perf_counter() - _startup_t0
    logger.info("FastAPI应用启动完成 (总耗时: %.3fs)", startup_elapsed)

    try:
        from config.integrated_config import get_settings
        _ready_host = get_settings().server.host or "0.0.0.0"
        _ready_port = get_settings().server.port or 8000
    except Exception:
        _ready_host, _ready_port = "0.0.0.0", 8000
    print(f"XiaoYou Core ready on http://{_ready_host}:{_ready_port} ({startup_elapsed:.3f}s)", flush=True)

    # 启动内存监控看门狗（从配置读取开关）
    try:
        yaml_path = get_project_root() / "config" / "yaml" / "app.yaml"
        if yaml_path.exists():
            from config.yaml_loader import load_resolved_yaml_config_from_disk

            yaml_config, _, _ = load_resolved_yaml_config_from_disk(yaml_path)
            wd_config = yaml_config.get("memory_watchdog", {})
            if wd_config.get("enabled", False):
                from core.utils.memory_watchdog import get_memory_watchdog
                watchdog = get_memory_watchdog(
                    check_interval=wd_config.get("check_interval", 60.0),
                    growth_threshold_mb=wd_config.get("growth_threshold_mb", 300.0),
                    growth_threshold_percent=wd_config.get("growth_threshold_percent", 10.0),
                )
                watchdog.start()
                logger.info("内存监控看门狗已启动 (异步模式)")
            else:
                logger.debug("内存监控看门狗已禁用 (memory_watchdog.enabled=false)")
    except Exception as e:
        logger.warning(f"启动内存监控看门狗失败: {e}")

    yield

    logger.info(">>> SHUTDOWN EVENT STARTED <<<")

    # 停止 Telegram 适配器
    try:
        if telegram_adapter:
            await telegram_adapter.stop()
        if telegram_task:
            try:
                await asyncio.wait_for(asyncio.shield(telegram_task), timeout=5.0)
            except asyncio.TimeoutError:
                telegram_task.cancel()
                try:
                    await telegram_task
                except asyncio.CancelledError:
                    pass
        if telegram_adapter:
            logger.info("Telegram 适配器已停止")
    except Exception as e:
        logger.warning(f"停止 Telegram 适配器失败: {e}")

    # 停止夜间处理器
    try:
        import memory.nightly_processor as np_module
        if hasattr(np_module, '_global_processor') and np_module._global_processor:
            np_module._global_processor.stop()
            logger.info("夜间处理器已停止")
    except Exception as e:
        logger.warning(f"停止夜间处理器失败: {e}")

    # 停止 UDP 发现信标
    try:
        await stop_discovery_beacon()
        logger.info("UDP 发现信标已停止")
    except Exception as e:
        logger.warning(f"停止 UDP 信标失败: {e}")

    # 停止内存监控看门狗
    try:
        from core.utils.memory_watchdog import stop_memory_watchdog
        stop_memory_watchdog()
        logger.info("内存监控看门狗已停止")
    except Exception as e:
        logger.debug(f"停止内存监控看门狗失败: {e}")

    shutdown_timeout = None
    force_exit_timeout = None
    try:
        from config.integrated_config import get_settings

        shutdown_timeout = float(get_settings().server.shutdown_timeout_seconds)
        force_exit_timeout = float(get_settings().server.force_exit_timeout_seconds)
    except Exception:
        shutdown_timeout = None
        force_exit_timeout = None

    shutdown_done = threading.Event()

    if force_exit_timeout is not None and force_exit_timeout > 0:

        def _shutdown_watchdog():
            if not shutdown_done.wait(force_exit_timeout):
                _force_kill_self()

        threading.Thread(target=_shutdown_watchdog, daemon=True).start()

    try:
        # 在关闭开始前进行内存检查
        try:
            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()
            if rm.is_memory_critical():
                logger.warning("系统内存占用过高，正在切换至紧急退出模式...")
        except Exception:
            pass

        shutdown_task = asyncio.create_task(get_lifecycle_manager().shutdown_all())
        if shutdown_timeout is not None and shutdown_timeout > 0:
            try:
                await asyncio.wait_for(
                    asyncio.shield(shutdown_task), timeout=shutdown_timeout
                )
            except asyncio.TimeoutError:
                logger.error("服务关闭超时，准备强制退出")
        else:
            await asyncio.shield(shutdown_task)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"关闭过程中发生异常: {e}")
    finally:
        # 无论如何都要尝试清理内存和显存
        try:
            # 停止背单词复习提醒器（关闭 APScheduler 后台线程）
            from core.tools.study.english.vocab_review_reminder import (
                get_vocab_review_reminder,
            )
            get_vocab_review_reminder().stop()
        except Exception:
            pass
        try:
            import gc

            gc.collect()

            import sys

            torch_mod = sys.modules.get("torch")
            if torch_mod is not None:
                cuda = getattr(torch_mod, "cuda", None)
                if (
                    cuda is not None
                    and callable(getattr(cuda, "is_available", None))
                    and cuda.is_available()
                ):
                    cuda.empty_cache()
                    logger.info("已清理 CUDA 缓存")
        except Exception:
            pass

        shutdown_done.set()
        _uninstall_windows_console_close_handler()
        logger.info(">>> APPLICATION SHUTDOWN COMPLETED <<<")

        # [CRITICAL] 强制终止进程树，解决幽灵进程问题
        # 在所有清理逻辑完成后，直接杀死当前进程和所有子进程
        # 防止 uvicorn 或其他第三方库(如 transformers/pytorch)的残留线程阻止进程退出
        _force_kill_self()
