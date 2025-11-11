@echo off

REM 小优AI本地部署启动脚本
REM 此脚本用于启动本地部署的小优AI服务

echo ====================================
echo 小优AI 本地部署模式启动脚本
echo ====================================

REM 检查虚拟环境是否存在
if not exist "venv\Scripts\activate.bat" (
    echo 错误: 虚拟环境不存在，请先运行环境设置脚本
    pause
    exit /b 1
)

REM 激活虚拟环境
echo 激活虚拟环境...
call venv\Scripts\activate.bat

REM 设置本地部署环境变量
echo 设置本地部署环境变量...
set DEVICE=cuda
set MODEL_DIR=./models
set WHISPER_MODEL_PATH=./models/whisper-large-v3

REM 显示启动信息
echo 准备启动服务...
echo 设备: %DEVICE%
echo 模型目录: %MODEL_DIR%
echo WebSocket端口: 8765
echo API端口: 8000

echo.
echo 按Ctrl+C可停止服务
echo ====================================
echo 启动服务...

REM 启动服务器
python start_server.py --no-auto-download

REM 暂停以便查看错误信息
pause