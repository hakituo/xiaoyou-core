import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

def mount_static_files(app: FastAPI):
    """挂载前端静态文件"""
    try:
        # 假设当前文件在 core/utils/static_files.py
        # project_root = d:\AI\xiaoyou-core
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        frontend_dir = os.path.join(project_root, "frontend", "Aveline_UI", "dist")
        
        if os.path.exists(frontend_dir):
            logger.info(f"挂载前端静态文件: {frontend_dir}")
            
            # 移动端路由
            @app.get("/app")
            async def mobile_app():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            # 根路由
            @app.get("/")
            async def read_root():
                return FileResponse(os.path.join(frontend_dir, "index.html"))

            # 静态文件挂载 (Frontend)
            app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
        else:
            logger.warning(f"前端静态文件目录不存在: {frontend_dir}")
            
        # 挂载后端静态资源 (Generated Images, etc.)
        static_dir = os.path.join(project_root, "static")
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
        
        # Ensure images/generated exists
        img_gen_dir = os.path.join(static_dir, "images", "generated")
        if not os.path.exists(img_gen_dir):
            os.makedirs(img_gen_dir)
            
        logger.info(f"挂载后端静态资源: {static_dir} -> /static")
        app.mount("/static", StaticFiles(directory=static_dir), name="backend_static")
        
    except Exception as e:
        logger.error(f"挂载静态文件失败: {e}")
