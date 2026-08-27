from core.utils.logger import get_logger
import os
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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
    env_frontend_dir = os.environ.get("XIAOYOU_FRONTEND_DIST", "").strip()
    candidates = []
    if env_frontend_dir:
        candidates.append(env_frontend_dir)

    candidates.extend(
        [
            os.path.join(project_root, "clients", "frontend", "aveline-web", "dist"),
            os.path.join(project_root, "clients", "frontend", "Aveline_UI", "dist"),
            os.path.join(project_root, "clients", "frontend", "dist"),
            os.path.join(project_root, "clients", "frontend", "out"),
        ]
    )

    frontend_root = os.path.join(project_root, "clients", "frontend")
    if os.path.isdir(frontend_root):
        try:
            for entry in os.scandir(frontend_root):
                if not entry.is_dir():
                    continue
                for output_dir in ("dist", "out"):
                    candidates.append(os.path.join(entry.path, output_dir))
        except Exception as e:
            logger.warning(f"扫描前端目录失败: {e}")

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


def mount_static_files(app: FastAPI):
    """挂载静态资源文件，包括前端、生成资源目录和输出目录"""
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
        # 必须先挂载特定路径，再挂载根路径 /
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

        # 4. 挂载前端静态文件 (放在最后，因为它拦截 /)
        if getattr(sys, "frozen", False):
            # PyInstaller mode
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

        if os.path.exists(frontend_dir):
            logger.info(f"挂载前端静态文件: {frontend_dir}")

            # 移动端路由支持
            @app.get("/app")
            async def mobile_app():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            # 根路由支持 (显式定义以确保 index.html 被正确返回)
            @app.get("/")
            async def read_root():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            # 挂载前端静态目录到 /
            # 注意：必须使用 HTTPOnlyStaticFiles。该挂载点是 catch-all，
            # 未命中 websocket 路由的 WS 连接会落到这里。
            app.mount(
                "/",
                HTTPOnlyStaticFiles(directory=frontend_dir, html=True),
                name="frontend",
            )
        else:
            fallback_paths = [
                os.path.join(project_root, "clients", "frontend", "aveline-web", "dist"),
                os.path.join(project_root, "clients", "frontend", "Aveline_UI", "dist"),
                os.path.join(project_root, "clients", "frontend", "dist"),
                os.path.join(project_root, "clients", "frontend", "out"),
            ]
            logger.warning(
                "前端静态文件目录不存在，Web 界面可能无法访问。"
                f" 当前路径: {frontend_dir or '未匹配到可用目录'};"
                f" 预期候选: {', '.join(fallback_paths)}"
            )

    except Exception as e:
        logger.error(f"挂载静态文件失败: {e}")
