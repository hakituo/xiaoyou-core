#!/usr/bin/env python3
"""验证 Web/Tunnel/后端入口没有再次发生端口与目录漂移。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    vite = read("clients/frontend/aveline-web/vite.config.ts")
    api_config = read("clients/frontend/aveline-web/src/api/config.ts")
    settings_view = read("clients/frontend/aveline-web/src/components/SettingsView.tsx")
    server_settings = read("config/settings_server.py")
    static_files = read("core/utils/static_files.py")
    start_pet = read("start_scripts/start_pet.bat")
    launcher = read("launcher.py")
    build_exe = read("build_exe.py")
    spec = read("XiaoyouCore.spec")
    ports_doc = read("docs/important/PORTS.md")

    require("port: 3000" in vite, "Vite 前端端口必须固定为 3000")
    require("strictPort: true" in vite, "Vite 必须禁止端口被占用时自动漂移")
    require("5173" not in vite, "Vite 配置不应再出现历史 5173")
    require("port === '3000'" in api_config, "前端环境识别必须以 3000 为开发端口")
    require("5173" not in api_config, "前端 API 配置不应再出现历史 5173")
    require("window.location.port === '3000'" in settings_view, "设置页必须以 3000 识别开发前端")
    require("5173" not in settings_view, "设置页不应再接受历史 5173")

    require("serve_frontend: bool" in server_settings, "ServerSettings 缺少前端托管显式开关")
    require("default=False" in server_settings, "普通运行默认必须保持前后端分离")
    require("5173" not in server_settings, "服务端 CORS 默认值不应继续保留 5173")

    require('"role": "backend-api"' in static_files, "8000 根路由应明确标识 backend-api")
    require("_should_serve_frontend" in static_files, "前端托管必须经过显式模式判断")
    require("Aveline_UI" not in static_files, "静态托管不应再扫描历史 Aveline_UI 目录")

    require("clients\\frontend\\aveline-web" in start_pet, "桌面启动脚本必须指向 aveline-web")
    require("Aveline_UI" not in start_pet, "桌面启动脚本仍引用历史 Aveline_UI")
    require("./clients/frontend/aveline-web" in launcher, "GUI launcher 默认前端目录必须指向 aveline-web")
    require("Aveline_UI" not in launcher, "GUI launcher 仍引用历史 Aveline_UI")
    require("range(8000, 8050)" not in launcher, "GUI launcher 不应允许后端端口漂移")
    require('"aveline-web", "dist"' in build_exe, "build_exe.py 必须打包 aveline-web/dist")
    require("Aveline_UI" not in build_exe, "build_exe.py 仍引用历史 Aveline_UI")
    require("aveline-web\\\\dist" in spec, "PyInstaller spec 必须打包 aveline-web/dist")
    require("Aveline_UI" not in spec, "PyInstaller spec 仍引用历史 Aveline_UI")

    require("Web Frontend** | **3000" in ports_doc, "端口文档未声明前端 3000")
    require("Backend API** | **8000" in ports_doc, "端口文档未声明后端 8000")

    print("[OK] frontend/network entrypoint contract verified")


if __name__ == "__main__":
    main()
