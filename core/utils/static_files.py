import os
import sys
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.utils.logger import get_logger

logger = get_logger(__name__)


class HTTPOnlyStaticFiles(StaticFiles):
    """仅处理 HTTP 请求的静态文件应用。

    Starlette 的 Mount 按路径前缀匹配，不区分 scope["type"]。
    当 StaticFiles 挂载在 "/" 上时，任何未命中 websocket 路由的 WS 连接
    都会落到这里，触发 StaticFiles 内部的 `assert scope["type"] == "http"`，
    导致 ASGI 层抛出 AssertionError。

    这里显式拦截非 HTTP 的 scope：对 websocket 直接发送 close，
    对其它类型静默返回，避免污染日志与中断事件循环。
    """

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")

        if scope_type == "websocket":
            logger.warning(
                "拒绝未匹配的 WebSocket 连接（落入静态文件挂载点）: path=%s",
                scope.get("path"),
            )
            # 必须先接收 websocket.connect 事件，才能合法地发送 close
            try:
                await receive()
            except Exception:
                pass
            await send({"type": "websocket.close", "code": 1000})
            return

        if scope_type != "http":
            logger.debug("忽略静态文件挂载点收到的非 HTTP 请求: type=%s", scope_type)
            return

        await super().__call__(scope, receive, send)


def _resolve_dev_frontend_dir(project_root: str) -> str:
    """解析当前唯一 Web 前端的构建目录。"""
    env_frontend_dir = os.environ.get("XIAOYOU_FRONTEND_DIST", "").strip()
    candidates = []
    if env_frontend_dir:
        candidates.append(env_frontend_dir)

    candidates.extend(
        [
            os.path.join(project_root, "clients", "frontend", "aveline-web", "dist"),
            os.path.join(project_root, "clients", "frontend", "dist"),
            os.path.join(project_root, "clients", "frontend", "out"),
        ]
    )

    checked = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.normpath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        index_file = os.path.join(normalized, "index.html")
        if os.path.isdir(normalized) and os.path.exists(index_file):
            return normalized

    return ""


def _should_serve_frontend(explicit: Optional[bool] = None) -> bool:
    """判断 8000 是否同时托管前端。

    普通开发/Tunnel 模式保持前后端分离：3000 是 Web，8000 是 API。
    PyInstaller 打包产物仍维持单端口模式，避免破坏桌面发行包。
    """
    if getattr(sys, "frozen", False):
        return True
    if explicit is not None:
        return bool(explicit)

    try:
        from config.integrated_config import get_settings

        return bool(get_settings().server.serve_frontend)
    except Exception as exc:
        logger.warning("读取 server.serve_frontend 失败，按前后端分离模式启动: %s", exc)
        return False


def mount_static_files(app: FastAPI, serve_frontend: Optional[bool] = None):
    """挂载后端静态资源；前端托管仅在显式/打包单端口模式启用。"""
    try:
        # 1. 确定项目根目录
        if getattr(sys, "frozen", False):
            # PyInstaller 环境
            project_root = os.path.dirname(sys.executable)
        else:
            # 开发环境
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )

        # 2. 挂载后端静态资源 (Generated Images, etc.)
        static_dir = os.path.join(project_root, "static")
        if not os.path.exists(static_dir):
            os.makedirs(static_dir, exist_ok=True)

        logger.info(f"挂载后端静态资源: {static_dir} -> /static")
        app.mount(
            "/static",
            HTTPOnlyStaticFiles(directory=static_dir),
            name="backend_static",
        )

        # 3. 挂载 output 目录 (用于兼容旧版路径 /output/image/...)
        output_dir = os.path.join(project_root, "output")
        logger.info(f"挂载输出目录: {output_dir} -> /output")
        app.mount(
            "/output",
            HTTPOnlyStaticFiles(directory=output_dir, check_dir=False),
            name="output_static",
        )

        # 4. 普通运行时 8000 是纯后端入口，不再因为 dist 存在就自动托管前端。
        if not _should_serve_frontend(serve_frontend):

            @app.get("/", include_in_schema=False)
            async def backend_root():
                return JSONResponse(
                    {
                        "service": "xiaoyou-core",
                        "role": "backend-api",
                        "api_prefix": "/api/v1",
                        "frontend_hosted": False,
                    }
                )

            logger.info(
                "前后端分离模式: Web 使用 localhost:3000，FastAPI 8000 不托管前端"
            )
            return

        # 5. 单端口模式：打包发行版或显式 server.serve_frontend=true。
        if getattr(sys, "frozen", False):
            if hasattr(sys, "_MEIPASS"):
                # onefile mode
                frontend_dir = os.path.join(sys._MEIPASS, "static")
            else:
                # onedir mode
                frontend_dir = os.path.join(os.path.dirname(sys.executable), "static")
                if not os.path.exists(frontend_dir):
                    frontend_dir = os.path.join(
                        os.path.dirname(sys.executable), "_internal", "static"
                    )
        else:
            frontend_dir = _resolve_dev_frontend_dir(project_root)

        if frontend_dir and os.path.exists(frontend_dir):
            logger.info(f"单端口模式挂载前端静态文件: {frontend_dir}")

            @app.get("/app")
            async def mobile_app():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            @app.get("/")
            async def read_root():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            app.mount(
                "/",
                HTTPOnlyStaticFiles(directory=frontend_dir, html=True),
                name="frontend",
            )
        else:
            fallback_paths = [
                os.path.join(project_root, "clients", "frontend", "aveline-web", "dist"),
                os.path.join(project_root, "clients", "frontend", "dist"),
                os.path.join(project_root, "clients", "frontend", "out"),
            ]
            logger.warning(
                "已启用前端托管，但前端静态文件目录不存在。"
                f" 当前路径: {frontend_dir or '未匹配到可用目录'};"
                f" 预期候选: {', '.join(fallback_paths)}"
            )

    except Exception as e:
        logger.error(f"挂载静态文件失败: {e}")
