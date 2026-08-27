#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI主应用入口
高性能异步AI Agent核心系统
"""

import os
import sys
import time
from datetime import datetime

# [内存泄漏追踪] DISABLED: tracemalloc 在此进程上不适用
# tracemalloc.start() 会追踪所有分配，但 take_snapshot() 会复制所有记录到一个 list，
# 98万分配 × 每条 tuple = 7.6GB 的 list。tracemalloc 自身就是最大的内存消耗者。
# 改用 /sample-lists 和 /top-objects API 定位泄漏（不依赖 tracemalloc）。
# import tracemalloc as _tm
# if not _tm.is_tracing():
#     _tm.start(1)

# RTX 5070 Compatibility Patch
if "GGML_CUDA_ENABLE_UNIFIED_MEMORY" not in os.environ:
    os.environ["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"
# os.environ["GGML_CUDA_NO_GRAPHS"] = "1" # Optional, Unified Memory seems enough with layers=0

# [内存优化] 限制 PyTorch CPU 缓存分配器的最大缓存大小
# 默认行为：torch 缓存分配器会把释放的 CPU 内存留在缓存里复用，不归还给 OS，
# 导致 RSS 只增不减。设置 max_split_size_mb 防止大块内存被无限缓存。
# 注意：这个环境变量必须在 import torch 之前设置才有效。
if "PYTORCH_NO_CUDA_MEMORY_CACHING" not in os.environ:
    os.environ["PYTORCH_NO_CUDA_MEMORY_CACHING"] = "1"
# CPU 分配器最大缓存块大小（MB），超过此大小的分配不缓存
if "PYTORCH_CPU_ALLOCATOR_MAX_SPLIT_SIZE_MB" not in os.environ:
    os.environ["PYTORCH_CPU_ALLOCATOR_MAX_SPLIT_SIZE_MB"] = "32"

import importlib
import socket
import atexit
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from core.utils.websocket_logging import RecoverableWebSocketDisconnectFilter

# 加载环境变量 (优先加载 .env)
load_dotenv(override=True)

# [CRITICAL] 强制国内镜像与离线模式 (必须在所有 HF 相关库导入前)
# 优先从环境变量读取，否则使用默认值
_hf_endpoint = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_ENDPOINT"] = _hf_endpoint
# 如果你想完全禁止联网下载，可以取消下面两行的注释
# os.environ["TRANSFORMERS_OFFLINE"] = "1"
# os.environ["HF_HUB_OFFLINE"] = "1"

# 初始化日志系统 (越早越好，确保所有日志格式统一)
_t_import_start = time.perf_counter()
_logger_mod = importlib.import_module("core.utils.logger")
init_logging_system = _logger_mod.init_logging_system
init_logging_system()
get_logger = _logger_mod.get_logger
logger = get_logger(__name__)
logger.info("[导入计时] core.utils.logger: %.3fs", time.perf_counter() - _t_import_start)

# 初始化配置
_t_import_start = time.perf_counter()
ConfigManager = importlib.import_module("core.core_engine.config_manager").ConfigManager
config_manager = ConfigManager()
config = config_manager.get_all_config()
logger.info("[导入计时] config_manager: %.3fs", time.perf_counter() - _t_import_start)

_t_import_start = time.perf_counter()
EventBus = importlib.import_module("core.core_engine.event_bus").EventBus
logger.info("[导入计时] event_bus: %.3fs", time.perf_counter() - _t_import_start)

_t_import_start = time.perf_counter()
request_performance_middleware = importlib.import_module(
    "core.async_monitor"
).request_performance_middleware
logger.info("[导入计时] async_monitor: %.3fs", time.perf_counter() - _t_import_start)

_t_import_start = time.perf_counter()
mount_static_files = importlib.import_module(
    "core.utils.static_files"
).mount_static_files
logger.info("[导入计时] static_files: %.3fs", time.perf_counter() - _t_import_start)

# 路由导入
_t_import_start = time.perf_counter()
_routers_mod = importlib.import_module("routers")
api_v1_router = _routers_mod.api_v1_router
openai_compat_router = _routers_mod.openai_compat_router
obsidian_router = _routers_mod.obsidian_router
logger.info("[导入计时] routers (全部): %.3fs", time.perf_counter() - _t_import_start)

_t_import_start = time.perf_counter()
demo_router = importlib.import_module("routers.demo").router
logger.info("[导入计时] demo_router: %.3fs", time.perf_counter() - _t_import_start)

# 重构后的模块导入
_t_import_start = time.perf_counter()
global_exception_handler = importlib.import_module(
    "core.utils.error_handlers"
).global_exception_handler
lifespan = importlib.import_module("core.lifecycle.lifespan").lifespan
logger.info("[导入计时] error_handlers + lifespan: %.3fs", time.perf_counter() - _t_import_start)

# 安全中间件导入
_t_import_start = time.perf_counter()
security_middleware = importlib.import_module(
    "core.middleware.security"
).security_middleware
strict_origin_middleware = importlib.import_module(
    "core.middleware.security"
).strict_origin_middleware
request_logging_middleware = importlib.import_module(
    "core.middleware.security"
).request_logging_middleware
logger.info("[导入计时] security middleware: %.3fs", time.perf_counter() - _t_import_start)

# 全局事件总线
event_bus = EventBus()

# 创建FastAPI应用
app = FastAPI(
    title="XiaoYou AI Core",
    description="High-performance Asynchronous AI Agent Core",
    version="2.3.0",
    lifespan=lifespan,
)

# 注册中间件
# 1. CORS
server_config = config.get("server", {}) if isinstance(config, dict) else {}
allowed_origins_str = server_config.get("allowed_origins", "*")
if allowed_origins_str == "*":
    allow_origins = ["*"]
else:
    allow_origins = [origin.strip() for origin in allowed_origins_str.split(",")]


# 3. 动态 Origin 校验中间件 (针对 Cloudflare 穿透场景)
@app.middleware("http")
async def strict_origin_middleware_wrapper(request: Request, call_next):
    return await strict_origin_middleware(request, call_next, allow_origins)


# P2-7: CORS 规范禁止 allow_origins=["*"] + allow_credentials=True 的组合，
# 当配置为通配符时显式关闭 credentials，避免浏览器拒绝带 cookie 的跨域请求；
# 配置为具体 origin 列表时才允许 credentials。
_allow_credentials = "*" not in allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,  # 从配置加载允许的来源
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 安全中间件
app.middleware("http")(security_middleware)


# 3. 性能监控中间件
@app.middleware("http")
async def performance_middleware(request: Request, call_next):
    # 过滤掉非 HTTP 请求（如 WebSocket），防止断言错误
    if request.scope.get("type") != "http":
        return await call_next(request)
    return await request_performance_middleware(request, call_next)


# 4. 请求日志中间件
app.middleware("http")(request_logging_middleware)


# 注册异常处理器
app.add_exception_handler(Exception, global_exception_handler)


# 注册API路由
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


app.include_router(api_v1_router)
app.include_router(openai_compat_router)
app.include_router(obsidian_router)
app.include_router(demo_router)

mount_static_files(app)


def _build_uvicorn_file_log_config():
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.getcwd()
    )
    now = datetime.now()
    log_dir = os.path.join(base_dir, "logs", str(now.year), str(now.month), str(now.day))
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "server.log")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "recoverable_websocket_disconnect": {
                "()": RecoverableWebSocketDisconnectFilter,
            },
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filename": log_file,
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
                "filters": ["recoverable_websocket_disconnect"],
            },
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "INFO",
                "stream": "ext://sys.stderr",
                "filters": ["recoverable_websocket_disconnect"],
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["file", "console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["file", "console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["file", "console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
        "root": {"handlers": ["file", "console"], "level": "INFO"},
    }


def _print_startup_summary(host: str, port: int, preferred_port: int, reload: bool):
    local_url = f"http://127.0.0.1:{port}"
    bind_url = f"http://{host}:{port}" if host not in {"0.0.0.0", "::"} else local_url
    print("")
    print("==================================================")
    print("XiaoYou Core is starting")
    print(f"Local:   {local_url}")
    if bind_url != local_url:
        print(f"Bind:    {bind_url}")
    if int(port) != int(preferred_port):
        print(f"Port:    {preferred_port} was busy, switched to {port}")
    print(f"Reload:  {'on' if reload else 'off'}")
    print("Logs:    console shows info/warnings/errors; details are in ./logs")
    print("==================================================")
    print("")


def _make_reuse_socket(host: str, port: int) -> "socket.socket":
    """创建一个允许地址复用的监听 socket。

    关键：设置 SO_REUSEADDR=1，使本进程退出后端口能立即被新实例复用，
    避免 Windows 下 TIME_WAIT / 僵尸进程导致"端口仍被占用、重启连不上"的问题。
    Linux 额外设置 SO_REUSEPORT 以支持多进程负载均衡与瞬时复用。
    注意：Windows 不要用 SO_REUSEADDR=0（那会禁止复用），本项目需要=1。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT") and os.name != "nt":
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind((host, int(port)))
    s.listen(2048)
    return s


def _run_server(app, host, port, reload, log_config, graceful_timeout):
    """以 uvicorn.Server 形式启动，确保 Ctrl+C 时端口立即释放。

    与直接 uvicorn.run() 的区别：
    1. 预建带 SO_REUSEADDR 的 socket 传入，重启可瞬时复用端口；
    2. uvicorn 0.40+ 通过 capture_signals() 接管 Ctrl+C/SIGTERM，
       收到信号后立即关闭监听 socket 并优雅退出（端口即刻释放），
       lifespan 的资源清理在退出流程内完成；
    3. atexit 兜底，异常退出也强制关闭监听端口。
    """
    listen_socket = _make_reuse_socket(host, port)

    config = uvicorn.Config(
        app,
        host=host,
        port=int(port),
        reload=reload,
        log_level="info",
        log_config=log_config,
        ws_ping_interval=30.0,
        ws_ping_timeout=60.0,
        timeout_graceful_shutdown=float(graceful_timeout),
    )
    server = uvicorn.Server(config)

    _closed = False

    def _release_port():
        nonlocal _closed
        if _closed:
            return
        _closed = True
        # uvicorn 关闭监听 socket 后即释放端口；此处兜底，防止异常路径下残留
        try:
            if getattr(server, "server", None) is not None:
                server.server.close()
        except Exception:
            pass
        try:
            listen_socket.close()
        except Exception:
            pass

    # 异常退出兜底关闭端口
    atexit.register(_release_port)

    # 把预建（已设 SO_REUSEADDR）的 socket 传给 uvicorn.run(sockets=...)，
    # 让 uvicorn 直接使用它监听，而不自己 bind host:port（否则会忽略我们的
    # socket 选项，并可能在退出时立刻被新实例抢不到）。
    # 信号由 uvicorn 的 capture_signals() 统一处理：Ctrl+C 后立即关闭监听端口。
    try:
        server.run(sockets=[listen_socket])
    finally:
        _release_port()


if __name__ == "__main__":
    try:
        logger.info("启动应用服务器...")
        host = config.get("server", {}).get("host", "0.0.0.0")
        port = config.get("server", {}).get("port", 8000)
        preferred_port = port
        reload = config.get("server", {}).get("reload", False)

        graceful_shutdown_timeout = 10.0
        try:
            from config.integrated_config import get_settings

            graceful_shutdown_timeout = float(
                get_settings().server.shutdown_timeout_seconds
            )
        except Exception:
            graceful_shutdown_timeout = 10.0

        try:
            if os.name == "nt" and bool(reload):
                scheduler_cfg = (
                    config.get("scheduler", {}) if isinstance(config, dict) else {}
                )
                model_cfg = config.get("model", {}) if isinstance(config, dict) else {}

                use_cpp = bool(scheduler_cfg.get("use_cpp", False))
                text_path = str(model_cfg.get("text_path", "") or "")
                might_use_gpu = use_cpp or text_path.lower().endswith(".gguf")

                if might_use_gpu:
                    logger.warning(
                        "Windows 下开启 reload 可能导致子进程残留与显存不释放，已自动关闭 reload。"
                    )
                    reload = False
        except Exception:
            pass

        def _pick_available_port(
            bind_host: str, preferred_port: int, max_tries: int = 20
        ) -> int:
            import socket

            def _can_bind(p: int) -> bool:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                    s.bind((bind_host, p))
                    return True
                except OSError:
                    return False
                finally:
                    try:
                        s.close()
                    except Exception:
                        pass

            for candidate in range(
                int(preferred_port), int(preferred_port) + int(max_tries)
            ):
                if _can_bind(candidate):
                    return candidate
            return int(preferred_port)

        chosen_port = _pick_available_port(host, port, max_tries=50)
        if chosen_port != port:
            logger.warning(f"端口 {port} 已被占用，自动切换到 {chosen_port}")
            print(
                f"WARNING: Default port {port} is in use. Switched to {chosen_port}. Check for zombie processes."
            )
            port = chosen_port

        _print_startup_summary(host, port, preferred_port, reload)

        # Check if running in frozen mode (PyInstaller)
        import sys

        if getattr(sys, "frozen", False):
            reload = False  # Disable reload in frozen mode
            log_config = None
            try:
                if sys.stderr is None or sys.stdout is None:
                    log_config = _build_uvicorn_file_log_config()
            except Exception:
                log_config = _build_uvicorn_file_log_config()
            try:
                import threading
                import webbrowser
                import time

                def _open_ui():
                    time.sleep(1.2)
                    webbrowser.open(f"http://127.0.0.1:{port}/", new=2)

                threading.Thread(target=_open_ui, daemon=True).start()
            except Exception:
                pass
            # Pass app instance directly
            _run_server(
                app,
                host=host,
                port=port,
                reload=reload,
                log_config=log_config,
                graceful_timeout=graceful_shutdown_timeout + 2.0,
            )
        # 统一传 app 对象（不传字符串 "main:app"）
        # 传字符串时 uvicorn 会 spawn 子进程重新 import，Windows 上 Ctrl+C 信号
        # 无法传递到子进程，导致僵尸进程残留、端口占用。传 app 对象则在本进程内运行。
        log_config = _build_uvicorn_file_log_config()
        _run_server(
            app,
            host=host,
            port=port,
            reload=False,  # 传 app 对象不支持 reload；需要热重载时用 CLI: uvicorn main:app --reload
            log_config=log_config,
            graceful_timeout=graceful_shutdown_timeout + 2.0,
        )
    except Exception as e:
        logger.critical(f"Critical Startup Error: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        try:
            import sys

            if getattr(sys, "stdin", None) is not None:
                input("Press Enter to exit...")
        except Exception:
            pass
